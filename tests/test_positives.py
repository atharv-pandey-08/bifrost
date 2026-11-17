"""Tests for bifrost.data.positives, using tiny made-up Parquet files."""

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd

from bifrost.data.positives import build_positives


def _t(day: int, hour: int = 0) -> datetime:
    return datetime(2017, 8, day, hour, tzinfo=UTC)


def _inter(
    user: str,
    book: str,
    read: bool = True,
    rating: int = 4,
    added: datetime | None = None,
    updated: datetime | None = None,
) -> dict:
    added = added or _t(1)
    return {
        "user_id": user,
        "book_id": book,
        "is_read": read,
        "rating": rating,
        "date_added": added,
        "date_updated": updated or added,
    }


def _book(book: str, work: str, ratings: int | None = 10) -> dict:
    return {
        "book_id": book,
        "work_id": work,
        "title": f"t{book}",
        "title_without_series": f"t{book}",
        "description": "",
        "language_code": "eng",
        "publication_year": 2001,
        "ratings_count": ratings,
        "average_rating": 4.0,
        "popular_shelves": [],
    }


def _run(tmp: Path, inter: list[dict], books: list[dict]):
    pd.DataFrame(inter).to_parquet(tmp / "i.parquet")
    pd.DataFrame(books).to_parquet(tmp / "b.parquet")
    stats = build_positives(
        tmp / "i.parquet", tmp / "b.parquet", tmp / "p.parquet", tmp / "w.parquet"
    )
    return stats


def _rows(path: Path, sql: str) -> list[tuple]:
    return duckdb.sql(sql.format(p=f"'{path}'")).fetchall()


def test_unread_dropped_and_unrated_read_kept(tmp_path: Path) -> None:
    stats = _run(
        tmp_path,
        [
            _inter("u", "1"),
            _inter("u", "2", read=False, rating=0),
            _inter("u", "3", rating=0),
        ],
        [_book("1", "w1"), _book("2", "w2"), _book("3", "w3")],
    )
    assert (stats.reads_in, stats.rows_out) == (2, 2)
    assert _rows(
        tmp_path / "p.parquet", "SELECT work_id, rating FROM {p} ORDER BY work_id"
    ) == [("w1", 4), ("w3", 0)]


def test_editions_merge_to_earliest_row(tmp_path: Path) -> None:
    # Same reader, two editions of work w: keep the earlier shelving and its rating.
    stats = _run(
        tmp_path,
        [
            _inter("u", "1", rating=5, added=_t(2)),
            _inter("u", "2", rating=3, added=_t(1)),
        ],
        [_book("1", "w"), _book("2", "w")],
    )
    assert (stats.reads_in, stats.rows_out, stats.merged) == (2, 1, 1)
    assert _rows(
        tmp_path / "p.parquet", "SELECT rating, epoch(date_added) FROM {p}"
    ) == [(3, _t(1).timestamp())]


def test_same_day_tie_breaks_on_date_updated_then_book_id(tmp_path: Path) -> None:
    inter = [
        _inter("u", "1", rating=1, updated=_t(5)),
        _inter("u", "2", rating=2, updated=_t(3)),
    ]
    _run(tmp_path, inter, [_book("1", "w"), _book("2", "w")])
    assert _rows(tmp_path / "p.parquet", "SELECT rating FROM {p}") == [
        (2,)
    ]  # earlier date_updated wins
    inter = [_inter("u", "10", rating=1), _inter("u", "9", rating=2)]
    _run(tmp_path, inter, [_book("10", "w"), _book("9", "w")])
    assert _rows(tmp_path / "p.parquet", "SELECT rating FROM {p}") == [
        (2,)
    ]  # book 9 < book 10 as numbers


def test_two_readers_on_one_work_stay_separate(tmp_path: Path) -> None:
    stats = _run(
        tmp_path,
        [_inter("a", "1"), _inter("b", "2")],
        [_book("1", "w"), _book("2", "w")],
    )
    assert stats.rows_out == 2


def test_unmapped_book_is_dropped_and_counted(tmp_path: Path) -> None:
    stats = _run(tmp_path, [_inter("u", "1"), _inter("u", "999")], [_book("1", "w1")])
    assert (stats.reads_in, stats.unmapped, stats.rows_out) == (2, 1, 1)


def test_representative_edition_is_most_rated_then_lowest_number(
    tmp_path: Path,
) -> None:
    books = [
        _book("10", "w", ratings=50),
        _book("9", "w", ratings=50),
        _book("3", "w", ratings=5),
        _book("4", "x", ratings=None),
    ]
    _run(tmp_path, [_inter("u", "10")], books)
    assert _rows(
        tmp_path / "w.parquet",
        "SELECT work_id, book_id, n_editions FROM {p} ORDER BY work_id",
    ) == [("w", "9", 3), ("x", "4", 1)]


def test_every_output_work_is_in_the_works_table_and_pairs_are_unique(
    tmp_path: Path,
) -> None:
    inter = [_inter("a", "1"), _inter("a", "2"), _inter("b", "2"), _inter("b", "3")]
    _run(tmp_path, inter, [_book("1", "w"), _book("2", "w"), _book("3", "z")])
    p = tmp_path / "p.parquet"
    assert _rows(p, "SELECT count(*) FROM {p}") == _rows(
        p, "SELECT count(DISTINCT (user_id, work_id)) FROM {p}"
    )
    assert _rows(tmp_path / "w.parquet", "SELECT count(*) FROM {p}") == [(2,)]
    missing = duckdb.sql(
        f"SELECT count(*) FROM '{p}' WHERE work_id NOT IN (SELECT work_id FROM '{tmp_path / 'w.parquet'}')"
    )
    assert missing.fetchall() == [(0,)]
