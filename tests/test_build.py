"""配信ディレクトリの組み立て。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from conftest import make_dataset, record
from heritage_site.build import build
from heritage_site.datasets import DataError

TODAY = date(2026, 8, 13)
SITE_DIR = Path(__file__).resolve().parents[1] / "site"


def _build(data_dir: Path, out: Path, **kwargs: object) -> object:
    return build(data_dir, out, site_dir=SITE_DIR, today=TODAY, **kwargs)  # type: ignore[arg-type]


def test_build_writes_the_index_and_copies_the_data(data_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "dist"
    report = _build(data_dir, out)

    assert not report.failed  # type: ignore[attr-defined]
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert index["totals"] == {
        "records": 5,
        "distinct": 4,
        "shared": 1,
        "with_coordinates": 4,
        "mapped": 4,
    }
    assert [dataset["repo"] for dataset in index["datasets"]] == [
        "national-treasures",
        "special-historic-sites",
        "special-places-of-scenic-beauty",
    ]
    assert (out / "index.html").is_file()
    assert (out / "datasets/national-treasures/data/26_kyoto.jsonl").is_file()


def test_data_is_copied_byte_for_byte(data_dir: Path, tmp_path: Path) -> None:
    """サイトが見せているのはデータリポジトリのあの行そのもの (ADR 0015)。"""
    out = tmp_path / "dist"
    _build(data_dir, out)
    source = data_dir / "national-treasures/data/26_kyoto.jsonl"
    copied = out / "datasets/national-treasures/data/26_kyoto.jsonl"
    assert copied.read_bytes() == source.read_bytes()


def test_index_carries_the_metadata_verbatim(data_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "dist"
    _build(data_dir, out)
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    original = json.loads((data_dir / "national-treasures/meta.json").read_text(encoding="utf-8"))
    assert index["datasets"][0]["meta"] == original


def test_points_exclude_rows_without_coordinates(data_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "dist"
    _build(data_dir, out)
    points = json.loads((out / "points.json").read_text(encoding="utf-8"))
    assert points["fields"][0] == "dataset"
    assert all(len(point) == len(points["fields"]) for point in points["points"])
    assert "00001235" not in {point[2] for point in points["points"]}


def test_points_exclude_coordinates_outside_japan(data_dir: Path, tmp_path: Path) -> None:
    make_dataset(
        data_dir,
        "registered-tangible-cultural-properties",
        {"03_iwate.jsonl": [record("101", "00013209", latitude=39.54161944, longitude=39.541475)]},
    )
    out = tmp_path / "dist"
    report = _build(data_dir, out)
    points = json.loads((out / "points.json").read_text(encoding="utf-8"))
    assert "00013209" not in {point[2] for point in points["points"]}
    # 地図から外しても、行そのものは配る。一覧には出せる。
    assert (out / "datasets/registered-tangible-cultural-properties/data/03_iwate.jsonl").is_file()
    assert report.with_coordinates > report.mapped  # type: ignore[attr-defined]


def test_build_is_deterministic(data_dir: Path, tmp_path: Path) -> None:
    """同じ入力なら同じバイト列。データが変わらない月に差分を立てない。"""
    first, second = tmp_path / "a", tmp_path / "b"
    _build(data_dir, first)
    _build(data_dir, second)
    for name in ("index.json", "points.json"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_failed_checks_write_nothing(data_dir: Path, tmp_path: Path) -> None:
    """壊れた索引で上書きするより、既に配信されているものを残す方が安全。"""
    make_dataset(data_dir, "stale", {"13_tokyo.jsonl": []}, accessed_date="2020-01-01")
    out = tmp_path / "dist"
    report = _build(data_dir, out)
    assert report.failed  # type: ignore[attr-defined]
    assert not out.exists()


def test_check_only_writes_nothing(data_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "dist"
    report = _build(data_dir, out, write=False)
    assert not report.failed  # type: ignore[attr-defined]
    assert not out.exists()


def test_rebuild_removes_stale_output(data_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "dist"
    _build(data_dir, out)
    (out / "leftover.json").write_text("{}", encoding="utf-8")
    _build(data_dir, out)
    assert not (out / "leftover.json").exists()


def test_build_refuses_to_empty_an_unrelated_directory(data_dir: Path, tmp_path: Path) -> None:
    """`--out` の打ち間違いで手元のディレクトリを消さない。"""
    out = tmp_path / "mine"
    out.mkdir()
    (out / "大事なもの.txt").write_text("消さないで", encoding="utf-8")
    with pytest.raises(DataError, match="このビルドの生成物でもない"):
        _build(data_dir, out)
    assert (out / "大事なもの.txt").is_file()
