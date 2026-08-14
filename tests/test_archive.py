"""配布物 (ZIP) の組み立て。"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from conftest import make_dataset, record
from heritage_site.archive import (
    ARCHIVE_NAME,
    FIXED_TIMESTAMP,
    MANIFEST_FILENAME,
    dataset_archive_name,
    pack,
)
from heritage_site.datasets import DataError


def _manifest(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        return json.loads(archive.read(MANIFEST_FILENAME))


def test_pack_writes_everything_and_one_per_dataset(data_dir: Path, tmp_path: Path) -> None:
    report = pack(data_dir, tmp_path / "dist")

    assert report.everything.path.name == ARCHIVE_NAME
    assert [archive.repo for archive in report.per_dataset] == [
        "national-treasures",
        "special-historic-sites",
        "special-places-of-scenic-beauty",
    ]
    # 全部入りは 5 行 (複合指定の 1 件は 2 つの種別それぞれに入っている)。
    assert report.everything.records == 5
    assert all(archive.path.is_file() for archive in report.archives)


def test_everything_is_partitioned_by_repository(data_dir: Path, tmp_path: Path) -> None:
    """全部入りはリポジトリ名で仕切る (展開しても種別が混ざらない)。"""
    report = pack(data_dir, tmp_path / "dist")
    with zipfile.ZipFile(report.everything.path) as archive:
        names = archive.namelist()
    assert "national-treasures/data/26_kyoto.jsonl" in names
    assert "national-treasures/meta.json" in names


def test_per_dataset_archive_is_the_repository_as_it_is(data_dir: Path, tmp_path: Path) -> None:
    """種別ごとのぶんは、展開するとそのデータリポジトリの中身になる。

    各データリポジトリのリリースに置くものなので、リポジトリ名のディレクトリが
    一段挟まると「落として展開したら中身が出る」にならない。
    """
    report = pack(data_dir, tmp_path / "dist")
    only = next(item for item in report.per_dataset if item.repo == "national-treasures")

    assert only.path.name == dataset_archive_name("national-treasures")
    with zipfile.ZipFile(only.path) as archive:
        names = sorted(archive.namelist())
    assert names == [
        MANIFEST_FILENAME,
        "data/13_tokyo.jsonl",
        "data/26_kyoto.jsonl",
        "meta.json",
    ]


def test_data_is_stored_byte_for_byte(data_dir: Path, tmp_path: Path) -> None:
    """配るのはデータリポジトリのあの行そのもの (ADR 0015)。"""
    report = pack(data_dir, tmp_path / "dist")
    source = (data_dir / "national-treasures/data/26_kyoto.jsonl").read_bytes()
    with zipfile.ZipFile(report.everything.path) as archive:
        assert archive.read("national-treasures/data/26_kyoto.jsonl") == source


def test_the_archive_is_deterministic(data_dir: Path, tmp_path: Path) -> None:
    """同じ入力なら同じバイト列。

    実行時刻が混ざると、データが 1 行も変わっていない月にも配布物だけが変わる。
    """
    first = pack(data_dir, tmp_path / "one").everything.path.read_bytes()
    second = pack(data_dir, tmp_path / "two").everything.path.read_bytes()
    assert first == second


def test_no_entry_carries_the_time_it_was_packed(data_dir: Path, tmp_path: Path) -> None:
    """格納時刻が固定されていること自体を見る。

    「2 回作って同じ」だけでは足りない — 同じ秒に作れば実行時刻を書いていても
    一致してしまい、検査をすり抜ける。
    """
    report = pack(data_dir, tmp_path / "dist")
    with zipfile.ZipFile(report.everything.path) as archive:
        stamps = {item.date_time for item in archive.infolist()}
    assert stamps == {FIXED_TIMESTAMP}


def test_the_manifest_counts_the_rows_it_stored(data_dir: Path, tmp_path: Path) -> None:
    report = pack(data_dir, tmp_path / "dist")
    manifest = _manifest(report.everything.path)

    assert manifest["totals"] == {"datasets": 3, "records": 5, "files": 7}
    treasures = next(item for item in manifest["datasets"] if item["repo"] == "national-treasures")
    assert treasures["records"] == 3
    assert treasures["name"] == "国宝（建造物）"
    kyoto = next(item for item in treasures["files"] if item["path"].endswith("26_kyoto.jsonl"))
    assert kyoto["records"] == 2


def test_the_manifest_carries_a_checksum_of_each_file(data_dir: Path, tmp_path: Path) -> None:
    report = pack(data_dir, tmp_path / "dist")
    manifest = _manifest(report.everything.path)
    entry = next(
        item
        for dataset in manifest["datasets"]
        for item in dataset["files"]
        if item["path"] == "national-treasures/data/26_kyoto.jsonl"
    )
    stored = (data_dir / "national-treasures/data/26_kyoto.jsonl").read_bytes()
    assert entry["sha256"] == hashlib.sha256(stored).hexdigest()
    assert entry["size"] == len(stored)


def test_the_manifest_has_no_timestamp(data_dir: Path, tmp_path: Path) -> None:
    """生成日時を持たない。持つと決定性が壊れる (いつ固めたかはタグが持つ)。"""
    manifest = _manifest(pack(data_dir, tmp_path / "dist").everything.path)
    assert "generated_at" not in manifest
    # 代わりに、いつデータを取得したかは種別ごとの利用日が持っている。
    assert all(item["accessed_date"] for item in manifest["datasets"])


def test_the_commit_of_each_source_is_recorded(data_dir: Path, tmp_path: Path) -> None:
    (data_dir / "sources.txt").write_text(
        "national-treasures 0123456789abcdef\n", encoding="utf-8"
    )
    manifest = _manifest(pack(data_dir, tmp_path / "dist").everything.path)

    by_repo = {item["repo"]: item for item in manifest["datasets"]}
    assert by_repo["national-treasures"]["commit"] == "0123456789abcdef"
    # 取得元が分からないぶんは項目ごと落とす (空文字を書かない)。
    assert "commit" not in by_repo["special-historic-sites"]


def test_a_broken_sources_file_is_named(data_dir: Path, tmp_path: Path) -> None:
    (data_dir / "sources.txt").write_text("national-treasures\n", encoding="utf-8")
    with pytest.raises(DataError, match=r"sources\.txt:1"):
        pack(data_dir, tmp_path / "dist")


def test_licence_and_readme_travel_with_the_data(tmp_path: Path) -> None:
    """出典と利用条件が配布物だけで完結するようにする。"""
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    root = make_dataset(data_dir, "only", {"13_tokyo.jsonl": [record("101", "00000001")]})
    (root / "LICENSE").write_text("利用条件", encoding="utf-8")
    (root / "README.md").write_text("# only", encoding="utf-8")

    report = pack(data_dir, tmp_path / "dist")
    with zipfile.ZipFile(report.per_dataset[0].path) as archive:
        names = archive.namelist()
    assert "LICENSE" in names
    assert "README.md" in names
