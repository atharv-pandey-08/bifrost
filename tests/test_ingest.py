"""Tests for bifrost.data.ingest, using tiny made-up files (not real Goodreads rows)."""

import gzip
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from bifrost.data.ingest import ingest_books, ingest_interactions


def _write_gz(path: Path, rows: list[dict]) -> Path:
    # Goodreads files are gzip-compressed, one JSON object per line.
    with gzip.open(path, "wt") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)
    return path


def _row(book: str, **kw: object) -> dict:
    base = {
        "user_id": "u1",
        "book_id": book,
        "review_id": "r",
        "is_read": True,
        "rating": 4,
        "review_text_incomplete": "",
        "date_added": "Fri Aug 25 13:55:02 -0700 2017",
        "date_updated": "Sat Aug 26 01:00:00 -0700 2017",
        "read_at": "",
        "started_at": "",
    }
    return base | kw


def _read(path: Path, epoch_cols: tuple[str, ...] = ()) -> list[dict]:
    # Timezone-aware dates are returned as epoch seconds, so Python never has to
    # convert them (DuckDB would need the pytz package for that).
    replace = ", ".join(f"epoch({c}) AS {c}" for c in epoch_cols)
    star = f"* REPLACE ({replace})" if replace else "*"
    cur = duckdb.sql(f"SELECT {star} FROM read_parquet('{path}') ORDER BY book_id")
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def test_interactions_drops_bad_dates_and_keeps_the_rest(tmp_path: Path) -> None:
    src = _write_gz(
        tmp_path / "i.json.gz",
        [
            _row("1"),
            _row("2", is_read=False, rating=0),  # to-read rows are kept here
            _row("3", date_added=""),  # missing date: dropped
            _row("4", date_added="not a date"),  # unparseable: dropped
            _row("5", rating=0),  # read but unrated: kept
            _row("6", date_updated="garbled"),  # only the tie-break date is bad
        ],
    )
    stats = ingest_interactions(src, tmp_path / "out.parquet")
    assert (stats.rows_read, stats.rows_dropped, stats.rows_written) == (6, 2, 4)
    assert [
        r["book_id"]
        for r in _read(tmp_path / "out.parquet", ("date_added", "date_updated"))
    ] == [
        "1",
        "2",
        "5",
        "6",
    ]


def test_interactions_types_and_utc_conversion(tmp_path: Path) -> None:
    src = _write_gz(
        tmp_path / "i.json.gz", [_row("1"), _row("6", date_updated="garbled")]
    )
    ingest_interactions(src, tmp_path / "out.parquet")
    first, second = _read(tmp_path / "out.parquet", ("date_added", "date_updated"))
    # 13:55 at UTC-7 is 20:55 UTC; stored as an absolute time.
    assert (
        first["date_added"] == datetime(2017, 8, 25, 20, 55, 2, tzinfo=UTC).timestamp()
    )
    assert first["rating"] == 4
    assert first["is_read"] is True
    assert second["date_updated"] is None  # kept, but null
    assert "review_id" not in first  # noise columns are not carried over


def test_books_types_and_blank_numbers(tmp_path: Path) -> None:
    book = {
        "book_id": "10",
        "work_id": "99",
        "title": "A Title",
        "title_without_series": "A Title",
        "description": "",
        "language_code": "eng",
        "publication_year": "2001",
        "ratings_count": "12",
        "average_rating": "3.5",
        "popular_shelves": [{"count": "3", "name": "ya"}],
    }
    blank = book | {"book_id": "11", "publication_year": "", "ratings_count": ""}
    src = _write_gz(tmp_path / "b.json.gz", [book, blank])
    assert ingest_books(src, tmp_path / "b.parquet") == 2
    a, b = _read(tmp_path / "b.parquet")
    assert (a["ratings_count"], a["average_rating"], a["publication_year"]) == (
        12,
        3.5,
        2001,
    )
    assert b["ratings_count"] is None
    assert b["publication_year"] is None
