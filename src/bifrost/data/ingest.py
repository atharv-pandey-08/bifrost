"""Turn raw Goodreads .json.gz files into typed Parquet files.

Ingest keeps every row it can parse. Choosing which rows count as positives
is a later step, so changing that rule never means re-reading the raw files.
"""

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import duckdb

log = logging.getLogger(__name__)

# Goodreads date_added looks like "Fri Aug 25 13:55:02 -0700 2017".
DATE_FORMAT = "%a %b %d %H:%M:%S %z %Y"

# Only the columns we use. review_id, review text, read_at and started_at are
# left out: see DECISIONS.md (noise, or too often missing or impossible).
INTERACTION_COLUMNS = (
    "{'user_id': 'VARCHAR', 'book_id': 'VARCHAR', 'is_read': 'BOOLEAN', "
    "'rating': 'BIGINT', 'date_added': 'VARCHAR', 'date_updated': 'VARCHAR'}"
)
BOOK_COLUMNS = (
    "{'book_id': 'VARCHAR', 'work_id': 'VARCHAR', 'title': 'VARCHAR', "
    "'title_without_series': 'VARCHAR', 'description': 'VARCHAR', "
    "'language_code': 'VARCHAR', 'publication_year': 'VARCHAR', "
    "'ratings_count': 'VARCHAR', 'average_rating': 'VARCHAR', "
    "'popular_shelves': 'STRUCT(count VARCHAR, name VARCHAR)[]'}"
)


@dataclass(frozen=True)
class IngestStats:
    rows_read: int
    rows_dropped: int  # rows with a missing or unparseable date_added
    rows_written: int


def _q(path: Path) -> str:
    # Single-quote a path for DuckDB SQL (paths here are ours, not user input).
    return "'" + str(path).replace("'", "''") + "'"


def _read_json(src: Path, columns: str) -> str:
    return f"read_json({_q(src)}, format='newline_delimited', columns={columns})"


def ingest_interactions(src: Path, dst: Path) -> IngestStats:
    """Write interactions to Parquet, dropping rows without a usable date_added."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    stage = dst.with_suffix(".stage.parquet")
    con = duckdb.connect()
    # Pass 1 reads the slow gzip once and keeps every row; bad dates become NULL.
    # try_strptime returns NULL instead of raising, and %z makes it timezone-aware.
    con.execute(f"""
        COPY (
            SELECT user_id, book_id, is_read, rating::UTINYINT AS rating,
                   try_strptime(date_added, '{DATE_FORMAT}') AS date_added,
                   try_strptime(date_updated, '{DATE_FORMAT}') AS date_updated
            FROM {_read_json(src, INTERACTION_COLUMNS)}
        ) TO {_q(stage)} (FORMAT parquet)
    """)
    # Pass 2 is cheap (columnar): count, then write only rows with a date.
    read, kept = con.execute(
        f"SELECT count(*), count(date_added) FROM read_parquet({_q(stage)})"
    ).fetchone()
    con.execute(f"""
        COPY (SELECT * FROM read_parquet({_q(stage)}) WHERE date_added IS NOT NULL)
        TO {_q(dst)} (FORMAT parquet)
    """)
    stage.unlink()
    stats = IngestStats(read, read - kept, kept)
    log.info("interactions: %s", stats)
    return stats


def ingest_books(src: Path, dst: Path) -> int:
    """Write the books table to Parquet with numbers as real numbers."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    # try_cast turns blank strings into NULL instead of failing.
    con.execute(f"""
        COPY (
            SELECT book_id, work_id, title, title_without_series, description,
                   language_code,
                   try_cast(publication_year AS INTEGER) AS publication_year,
                   try_cast(ratings_count AS INTEGER) AS ratings_count,
                   try_cast(average_rating AS DOUBLE) AS average_rating,
                   popular_shelves
            FROM {_read_json(src, BOOK_COLUMNS)}
        ) TO {_q(dst)} (FORMAT parquet)
    """)
    (n,) = con.execute(f"SELECT count(*) FROM read_parquet({_q(dst)})").fetchone()
    log.info("books: %s rows", n)
    return n


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a Goodreads genre subset.")
    parser.add_argument("--genre", default="poetry", help="e.g. poetry, young_adult")
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, default=Path("data/interim"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    g = args.genre
    ingest_books(
        args.raw / f"goodreads_books_{g}.json.gz", args.out / f"books_{g}.parquet"
    )
    ingest_interactions(
        args.raw / f"goodreads_interactions_{g}.json.gz",
        args.out / f"interactions_{g}.parquet",
    )


if __name__ == "__main__":
    main()
