"""Combine genre subsets into one fiction-only set, counting each work once.

Works from every subset are merged on work_id, classified from their top shelves,
and kept only if they carry a fiction tag and no non-fiction tag. Positives from
every subset are merged on (reader, work). See DECISIONS.md and SPEC.md.
"""

import argparse
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb

log = logging.getLogger(__name__)

# How many of a work's most-voted shelves are looked at when deciding its kind.
# Shelves tied with the last one are looked at too (see _classify).
TOP_SHELVES = 10

# The tag lists decide what counts as fiction. They are the author's to edit.
# Ambiguous words (history, science) can mislabel a novel; see DECISIONS.md.
FICTION_TAGS = (
    "fiction",
    "ya-fiction",
    "young-adult-fiction",
    "novels",
    "novel",
    "fantasy",
    "romance",
    "dystopian",
    "dystopia",
    "science-fiction",
    "sci-fi",
    "mystery",
    "thriller",
    "paranormal",
    "contemporary",
    "historical-fiction",
    "horror",
    "urban-fantasy",
    "paranormal-romance",
    "realistic-fiction",
    "adventure",
    "supernatural",
    "magic",
    "vampires",
    "retellings",
    "fairy-tales",
)
NONFICTION_TAGS = (
    "non-fiction",
    "nonfiction",
    "non-fic",
    "memoir",
    "biography",
    "autobiography",
    "self-help",
    "history",
    "science",
    "textbook",
    "textbooks",
    "psychology",
    "philosophy",
    "education",
    "reference",
)


@dataclass(frozen=True)
class FictionStats:
    works_in: int  # works across all subsets, shared ones counted once per subset
    works_union: int  # distinct works
    works_shared: int  # works that appear in more than one subset
    fiction: int  # fiction tag, no non-fiction tag (kept)
    nonfiction: int  # non-fiction tag, no fiction tag
    mixed: int  # both kinds of tag
    neither: int  # no fiction tag and no non-fiction tag
    works_kept: int
    positives_in: int  # positives across subsets, a shared pair counted once per subset
    positives_union: int  # distinct (reader, work) pairs
    positives_kept: int  # pairs whose work is kept


def _q(path: Path) -> str:
    # Single-quote a path for DuckDB SQL (paths here are ours, not user input).
    return "'" + str(path).replace("'", "''") + "'"


def _tags(tags: Sequence[str]) -> str:
    return ", ".join("'" + t.replace("'", "''") + "'" for t in tags)


def _union(paths: Sequence[Path], select: str) -> str:
    # One SELECT per file, tagged with its position so ties go to the earlier file.
    parts = [
        f"SELECT {i} AS src, {select} FROM read_parquet({_q(p)})"
        for i, p in enumerate(paths)
    ]
    return " UNION ALL BY NAME ".join(parts)


def _make_works(con: duckdb.DuckDBPyConnection, works: Sequence[Path]) -> None:
    # One row per work. A shared work keeps the more-rated row, then the earlier file's.
    cols = (
        "work_id, book_id, title, title_without_series, description, language_code, "
        "publication_year, ratings_count, popular_shelves"
    )
    con.execute(f"""
        CREATE TEMP TABLE w AS
        SELECT * EXCLUDE (src) FROM ({_union(works, cols)})
        QUALIFY row_number() OVER (
            PARTITION BY work_id ORDER BY coalesce(ratings_count, -1) DESC, src
        ) = 1
    """)


def _classify(con: duckdb.DuckDBPyConnection) -> None:
    # A work's "window" is its TOP_SHELVES most-voted shelves plus every shelf tied
    # with the last of them, so the result never depends on row order or on how
    # tied shelf names sort. Works with no shelves are "neither".
    con.execute(f"""
        CREATE TEMP TABLE cls AS
        WITH s AS (
            SELECT work_id, x.name AS name, try_cast(x.count AS BIGINT) AS votes
            FROM (SELECT work_id, unnest(popular_shelves) AS x FROM w)
        ), cutoff AS (
            -- votes of the TOP_SHELVES-th shelf (the smallest vote count among the top ones)
            SELECT work_id, min(votes) AS votes FROM (
                SELECT work_id, votes,
                       row_number() OVER (PARTITION BY work_id ORDER BY votes DESC NULLS LAST) AS rk
                FROM s
            ) WHERE rk <= {TOP_SHELVES} GROUP BY work_id
        )
        SELECT w.work_id,
               coalesce(bool_or(s.name IN ({_tags(FICTION_TAGS)}) AND s.votes >= c.votes), false) AS fic,
               coalesce(bool_or(s.name IN ({_tags(NONFICTION_TAGS)}) AND s.votes >= c.votes), false) AS nf
        FROM w LEFT JOIN s USING (work_id) LEFT JOIN cutoff c USING (work_id)
        GROUP BY w.work_id
    """)


def _make_positives(con: duckdb.DuckDBPyConnection, positives: Sequence[Path]) -> None:
    # A reader/work pair in several subsets keeps its earliest shelving (the same rule
    # as the per-genre step). Ties fall back to date_updated, then the earlier file.
    cols = "user_id, work_id, rating, date_added, date_updated"
    con.execute(f"""
        CREATE TEMP TABLE u AS
        SELECT * EXCLUDE (src) FROM ({_union(positives, cols)})
        QUALIFY row_number() OVER (
            PARTITION BY user_id, work_id ORDER BY date_added, date_updated NULLS LAST, src
        ) = 1
    """)


def _scalar(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    (value,) = con.execute(sql).fetchone()
    return int(value or 0)


def _stats(
    con: duckdb.DuckDBPyConnection, works: Sequence[Path], positives: Sequence[Path]
) -> FictionStats:
    count = lambda p: _scalar(con, f"SELECT count(*) FROM read_parquet({_q(p)})")
    works_in, positives_in = sum(map(count, works)), sum(map(count, positives))
    works_union = _scalar(con, "SELECT count(*) FROM w")
    kinds = con.execute("""
        SELECT count(*) FILTER (WHERE fic AND NOT nf), count(*) FILTER (WHERE nf AND NOT fic),
               count(*) FILTER (WHERE fic AND nf), count(*) FILTER (WHERE NOT fic AND NOT nf)
        FROM cls""").fetchone()
    kept = _scalar(
        con, "SELECT count(*) FROM u JOIN cls USING (work_id) WHERE fic AND NOT nf"
    )
    return FictionStats(
        works_in,
        works_union,
        works_in - works_union,
        *kinds,
        kinds[0],
        positives_in,
        _scalar(con, "SELECT count(*) FROM u"),
        kept,
    )


def build_fiction_set(
    works: Sequence[Path],
    positives: Sequence[Path],
    out_works: Path,
    out_positives: Path,
) -> FictionStats:
    """Merge subsets, keep fiction-only works, write both Parquet files, return counts."""
    out_works.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    _make_works(con, works)
    _classify(con)
    _make_positives(con, positives)
    keep = "SELECT work_id FROM cls WHERE fic AND NOT nf"
    con.execute(
        f"COPY (SELECT * FROM w WHERE work_id IN ({keep})) TO {_q(out_works)} (FORMAT parquet)"
    )
    con.execute(
        f"COPY (SELECT * FROM u WHERE work_id IN ({keep})) TO {_q(out_positives)} (FORMAT parquet)"
    )
    stats = _stats(con, works, positives)
    log.info("fiction: %s", stats)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Combine genres into one fiction-only set."
    )
    parser.add_argument(
        "--genres", nargs="+", default=["young_adult", "fantasy_paranormal"]
    )
    parser.add_argument("--dir", type=Path, default=Path("data/interim"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    d = args.dir
    build_fiction_set(
        [d / f"works_{g}.parquet" for g in args.genres],
        [d / f"positives_{g}.parquet" for g in args.genres],
        d / "works.parquet",
        d / "positives.parquet",
    )


if __name__ == "__main__":
    main()
