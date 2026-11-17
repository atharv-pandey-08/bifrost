"""Tests for bifrost.data.fiction, using tiny made-up Parquet files."""

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd

from bifrost.data.fiction import build_fiction_set


def _t(day: int) -> datetime:
    return datetime(2017, 8, day, tzinfo=UTC)


def _shelves(*pairs: tuple[str, int]) -> list[dict]:
    # Goodreads stores shelf counts as strings.
    return [{"count": str(n), "name": name} for name, n in pairs]


def _work(work: str, shelves: list[dict], ratings: int | None = 10) -> dict:
    return {
        "work_id": work,
        "book_id": f"b{work}",
        "title": f"t{work}",
        "title_without_series": f"t{work}",
        "description": "",
        "language_code": "eng",
        "publication_year": 2001,
        "ratings_count": ratings,
        "popular_shelves": shelves,
    }


def _pos(
    user: str, work: str, day: int = 1, rating: int = 4, updated_day: int | None = None
) -> dict:
    return {
        "user_id": user,
        "work_id": work,
        "rating": rating,
        "date_added": _t(day),
        "date_updated": _t(updated_day or day),
    }


# An empty list would write a Parquet file with no columns, so name them explicitly.
POS_COLUMNS = ["user_id", "work_id", "rating", "date_added", "date_updated"]

FIC = _shelves(("fantasy", 9), ("to-read", 50))
NONFIC = _shelves(("memoir", 9), ("to-read", 50))
MIXED = _shelves(("fantasy", 9), ("history", 8), ("to-read", 50))
NEITHER = _shelves(("to-read", 50), ("young-adult", 40))


def _run(tmp: Path, files: list[tuple[list[dict], list[dict]]]):
    works, positives = [], []
    for i, (w, p) in enumerate(files):
        pd.DataFrame(w).to_parquet(tmp / f"w{i}.parquet")
        pd.DataFrame(p, columns=POS_COLUMNS).to_parquet(tmp / f"p{i}.parquet")
        works.append(tmp / f"w{i}.parquet")
        positives.append(tmp / f"p{i}.parquet")
    return build_fiction_set(
        works, positives, tmp / "works.parquet", tmp / "positives.parquet"
    )


def _q(path: Path, sql: str) -> list[tuple]:
    return duckdb.sql(sql.format(p=f"'{path}'")).fetchall()


def test_only_fiction_only_works_are_kept(tmp_path: Path) -> None:
    works = [
        _work("w1", FIC),
        _work("w2", NONFIC),
        _work("w3", MIXED),
        _work("w4", NEITHER),
        _work("w5", []),
    ]
    pos = [_pos("u", w) for w in ("w1", "w2", "w3", "w4", "w5")]
    stats = _run(tmp_path, [(works, pos)])
    assert _q(tmp_path / "works.parquet", "SELECT work_id FROM {p}") == [("w1",)]
    assert (stats.fiction, stats.nonfiction, stats.mixed, stats.neither) == (1, 1, 1, 2)
    assert (stats.works_union, stats.works_kept) == (5, 1)
    assert (stats.positives_union, stats.positives_kept) == (5, 1)


def test_only_the_top_ten_shelves_count(tmp_path: Path) -> None:
    nine = [
        (f"g{i}", 100 - i) for i in range(9)
    ]  # nine generic shelves outvote the tags below
    ten = [*nine, ("g9", 91)]
    works = [
        _work(
            "w1", _shelves(*ten, ("fantasy", 1))
        ),  # fiction tag at rank 11: ignored -> neither
        _work(
            "w2", _shelves(*nine, ("fantasy", 50), ("memoir", 1))
        ),  # fiction at rank 10 counts, memoir at 11 does not
        _work(
            "w3", _shelves(*nine, ("memoir", 50), ("fantasy", 1))
        ),  # non-fiction at rank 10 counts, fiction at 11 does not
    ]
    stats = _run(tmp_path, [(works, [])])
    assert (stats.fiction, stats.nonfiction, stats.neither, stats.mixed) == (1, 1, 1, 0)
    assert _q(tmp_path / "works.parquet", "SELECT work_id FROM {p}") == [("w2",)]


def test_shelves_tied_with_the_tenth_all_count(tmp_path: Path) -> None:
    nine = [(f"g{i}", 100 - i) for i in range(9)]
    works = [
        # "aaa" sorts first, so an alphabetical tie-break would hide "romance"; both tie at 5 votes.
        _work("w1", _shelves(*nine, ("aaa", 5), ("romance", 5))),
        _work(
            "w2", _shelves(*nine, ("aaa", 5), ("memoir", 5))
        ),  # a tied non-fiction tag counts too
        _work(
            "w3", _shelves(*nine, ("aaa", 5), ("romance", 4))
        ),  # one vote lower: outside the window
    ]
    stats = _run(tmp_path, [(works, [])])
    assert (stats.fiction, stats.nonfiction, stats.neither) == (1, 1, 1)
    assert _q(tmp_path / "works.parquet", "SELECT work_id FROM {p}") == [("w1",)]


def test_shelf_order_never_changes_the_class(tmp_path: Path) -> None:
    shelves = [
        *[(f"g{i}", 100 - i) for i in range(9)],
        ("aaa", 5),
        ("romance", 5),
        ("memoir", 5),
    ]
    forward, backward = _shelves(*shelves), _shelves(*reversed(shelves))
    stats = _run(tmp_path, [([_work("w1", forward), _work("w2", backward)], [])])
    assert (stats.mixed, stats.fiction, stats.nonfiction, stats.neither) == (2, 0, 0, 0)


def test_shared_work_counted_once_and_keeps_the_better_rated_row(
    tmp_path: Path,
) -> None:
    a = ([_work("w", FIC, ratings=5), _work("x", FIC)], [])
    b = ([_work("w", FIC, ratings=99)], [])
    stats = _run(tmp_path, [a, b])
    assert (stats.works_in, stats.works_union, stats.works_shared) == (3, 2, 1)
    assert _q(
        tmp_path / "works.parquet", "SELECT ratings_count FROM {p} WHERE work_id='w'"
    ) == [(99,)]


def test_rating_tie_keeps_the_first_files_row(tmp_path: Path) -> None:
    first = _work("w", FIC, ratings=7) | {"title": "first"}
    second = _work("w", FIC, ratings=7) | {"title": "second"}
    _run(tmp_path, [([first], []), ([second], [])])
    assert _q(tmp_path / "works.parquet", "SELECT title FROM {p}") == [("first",)]


def test_shared_reader_and_work_merge_on_the_earliest_date(tmp_path: Path) -> None:
    works = [_work("w", FIC)]
    a = (works, [_pos("u", "w", day=5, rating=2)])
    b = (works, [_pos("u", "w", day=3, rating=4)])
    stats = _run(tmp_path, [a, b])
    assert (stats.positives_in, stats.positives_union, stats.positives_kept) == (
        2,
        1,
        1,
    )
    assert _q(
        tmp_path / "positives.parquet", "SELECT rating, epoch(date_added) FROM {p}"
    ) == [(4, _t(3).timestamp())]


def test_positives_of_dropped_works_are_removed_and_works_without_reads_stay(
    tmp_path: Path,
) -> None:
    works = [_work("keep", FIC), _work("noreads", FIC), _work("drop", NONFIC)]
    pos = [_pos("u", "keep"), _pos("u", "drop"), _pos("v", "drop")]
    stats = _run(tmp_path, [(works, pos)])
    assert _q(tmp_path / "positives.parquet", "SELECT work_id FROM {p}") == [("keep",)]
    assert stats.works_kept == 2  # "noreads" stays in the catalog


def test_every_kept_positive_has_a_kept_work_and_pairs_are_unique(
    tmp_path: Path,
) -> None:
    works = [_work("a", FIC), _work("b", FIC), _work("c", MIXED)]
    pos = [_pos("u", "a"), _pos("u", "b"), _pos("v", "a"), _pos("v", "c")]
    _run(tmp_path, [(works, pos), (works, pos)])
    p, w = tmp_path / "positives.parquet", tmp_path / "works.parquet"
    assert _q(p, "SELECT count(*) - count(DISTINCT (user_id, work_id)) FROM {p}") == [
        (0,)
    ]
    orphans = duckdb.sql(
        f"SELECT count(*) FROM '{p}' WHERE work_id NOT IN (SELECT work_id FROM '{w}')"
    )
    assert orphans.fetchall() == [(0,)]
