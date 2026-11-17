"""Checks that the package installs and that .gitignore keeps the files the plan needs."""

import subprocess
from pathlib import Path

import bifrost

ROOT = Path(__file__).resolve().parents[1]


def test_package_imports() -> None:
    # Fails if the build system or src layout is broken.
    assert bifrost.__doc__


def _is_ignored(path: str) -> bool:
    # `git check-ignore` exits 0 when the path is ignored, 1 when it is not.
    result = subprocess.run(["git", "check-ignore", "-q", path], check=False, cwd=ROOT)
    return result.returncode == 0


def test_fixtures_and_results_are_tracked() -> None:
    assert not _is_ignored("tests/fixtures/tiny_interactions.csv")
    assert not _is_ignored("tests/fixtures/tiny_books.parquet")
    assert not _is_ignored("results/metrics.csv")


def test_raw_data_stays_ignored() -> None:
    assert _is_ignored("data/raw/goodreads_interactions_young_adult.json.gz")
    assert _is_ignored("data/personal/Book_Tracker.csv")
