"""Turn ingested interactions into one positive per (reader, work).

A positive is a row with is_read = 1 (any rating, including 0). Editions of the
same book share a work_id, so a reader who shelved two editions counts once, on
the earliest shelving. Merging here keeps a test book from being another
edition of something already in training. See DECISIONS.md.
"""

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import duckdb

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PositivesStats:
    reads_in: int  # is_read = 1 rows going in
    unmapped: int  # reads whose book is missing from the books table (dropped)
    merged: int  # rows removed because the reader had several editions of a work
    rows_out: int  # one row per (reader, work)


def _q(path: Path) -> str:
    # Single-quote a path for DuckDB SQL (paths here are ours, not user input).
    return "'" + str(path).replace("'", "''") + "'"


def _write_works(con: duckdb.DuckDBPyConnection, books: Path, dst: Path) -> None:
    # One row per work. The representative edition is the most-rated one; ties go
    # to the lower book_id compared as a number ("9" before "10"), then as text.
    con.execute(f"""
        COPY (
            SELECT work_id, book_id, title, title_without_series, description,
                   language_code, publication_year, ratings_count, popular_shelves,
                   n_editions
            FROM (
                SELECT *, count(*) OVER (PARTITION BY work_id) AS n_editions,
                       row_number() OVER (
                           PARTITION BY work_id
                           ORDER BY coalesce(ratings_count, -1) DESC,
                                    try_cast(book_id AS BIGINT), book_id
                       ) AS rn
                FROM read_parquet({_q(books)})
            ) WHERE rn = 1
        ) TO {_q(dst)} (FORMAT parquet)
    """)


def _write_positives(
    con: duckdb.DuckDBPyConnection, inter: Path, books: Path, dst: Path
) -> None:
    # Keep the earliest shelving per (reader, work). Ties on date_added fall back
    # to date_updated (NULLs last), then book_id as a number, so the pick is stable.
    con.execute(f"""
        COPY (
            SELECT i.user_id, b.work_id, i.rating, i.date_added, i.date_updated
            FROM read_parquet({_q(inter)}) i
            JOIN read_parquet({_q(books)}) b USING (book_id)
            WHERE i.is_read
            QUALIFY row_number() OVER (
                PARTITION BY i.user_id, b.work_id
                ORDER BY i.date_added, i.date_updated NULLS LAST,
                         try_cast(i.book_id AS BIGINT), i.book_id
            ) = 1
        ) TO {_q(dst)} (FORMAT parquet)
    """)


def build_positives(
    inter: Path, books: Path, out_positives: Path, out_works: Path
) -> PositivesStats:
    """Write the positives and works Parquet files and return the counts."""
    out_positives.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    _write_works(con, books, out_works)
    _write_positives(con, inter, books, out_positives)
    (reads_in,) = con.execute(
        f"SELECT count(*) FROM read_parquet({_q(inter)}) WHERE is_read"
    ).fetchone()
    (mapped,) = con.execute(
        f"SELECT count(*) FROM read_parquet({_q(inter)}) i "
        f"JOIN read_parquet({_q(books)}) USING (book_id) WHERE i.is_read"
    ).fetchone()
    (rows_out,) = con.execute(
        f"SELECT count(*) FROM read_parquet({_q(out_positives)})"
    ).fetchone()
    stats = PositivesStats(reads_in, reads_in - mapped, mapped - rows_out, rows_out)
    log.info("positives: %s", stats)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build work-level positives for a genre."
    )
    parser.add_argument("--genre", default="poetry", help="e.g. poetry, young_adult")
    parser.add_argument("--dir", type=Path, default=Path("data/interim"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    g, d = args.genre, args.dir
    build_positives(
        d / f"interactions_{g}.parquet",
        d / f"books_{g}.parquet",
        d / f"positives_{g}.parquet",
        d / f"works_{g}.parquet",
    )


if __name__ == "__main__":
    main()
