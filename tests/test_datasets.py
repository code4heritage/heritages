"""データリポジトリの発見と読み出し。"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_dataset, record
from heritage_site.datasets import DataError, Dataset, discover, iter_rows


def test_discover_lists_datasets_in_repository_name_order(data_dir: Path) -> None:
    assert [dataset.repo for dataset in discover(data_dir)] == [
        "national-treasures",
        "special-historic-sites",
        "special-places-of-scenic-beauty",
    ]


def test_discover_skips_directories_without_meta(data_dir: Path) -> None:
    """データの無い器を削除しても (ADR 0013)、サイト側は何もしなくてよい。"""
    make_dataset(
        data_dir,
        "preservation-districts",
        {"13_tokyo.jsonl": []},
        write_meta=False,
    )
    assert "preservation-districts" not in [dataset.repo for dataset in discover(data_dir)]


def test_discover_rejects_a_directory_without_any_dataset(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(DataError, match="1 つも無い"):
        discover(empty)


def test_iter_rows_reads_files_in_name_order(data_dir: Path) -> None:
    dataset = discover(data_dir)[0]
    rows = list(iter_rows(dataset, 0))
    assert [(row.path, row.line, row.managed_id) for row in rows] == [
        ("data/13_tokyo.jsonl", 1, "00004367"),
        ("data/26_kyoto.jsonl", 1, "00001234"),
        ("data/26_kyoto.jsonl", 2, "00001235"),
    ]


def test_missing_coordinates_are_absent_not_zero(data_dir: Path) -> None:
    """キーが無い = 値なし。0 として地図の原点に置いてしまわない。"""
    rows = list(iter_rows(discover(data_dir)[0], 0))
    without = next(row for row in rows if row.managed_id == "00001235")
    assert (without.latitude, without.longitude) == (None, None)
    assert not without.has_coordinates


def test_one_sided_coordinates_count_as_missing(tmp_path: Path) -> None:
    directory = tmp_path / "data-repos"
    directory.mkdir()
    make_dataset(
        directory,
        "half",
        {"13_tokyo.jsonl": [record("101", "00000001", latitude=35.0)]},
        counts={"records": 1, "files": 1, "with_coordinates": 0},
    )
    row = next(iter(iter_rows(discover(directory)[0], 0)))
    assert not row.has_coordinates
    # 片方だけ残さない。残すと、地図を描く側が素直に読んだときに嘘の点が出る。
    assert (row.latitude, row.longitude) == (None, None)


def test_broken_json_names_the_line(tmp_path: Path) -> None:
    directory = tmp_path / "data-repos"
    directory.mkdir()
    root = make_dataset(directory, "broken", {"13_tokyo.jsonl": [record("101", "00000001")]})
    (root / "data" / "13_tokyo.jsonl").write_text("{\n", encoding="utf-8")
    with pytest.raises(DataError, match=r"broken/data/13_tokyo\.jsonl:1"):
        list(iter_rows(discover(directory)[0], 0))


def test_the_place_prefers_the_address(data_dir: Path) -> None:
    make_dataset(
        data_dir,
        "with-address",
        {
            "13_tokyo.jsonl": [
                record("101", "1", address="東京都台東区", storage_facility="東京国立博物館")
            ]
        },
    )
    [row] = iter_rows(_dataset(data_dir, "with-address"), 0)
    assert row.place == "東京都台東区"


def test_the_place_falls_back_to_what_the_row_has(data_dir: Path) -> None:
    """所在地を持たない行を空欄で並べない (Issue #23)。

    美術工芸品には所有者が公開されていない行が 7,114 ある。所蔵館や所有者は
    残っていることが多いので、**その行が持っているもの**で居場所を示す。
    """
    make_dataset(
        data_dir,
        "fine-arts",
        {
            "13_tokyo.jsonl": [
                record("201", "1", storage_facility="根津美術館", owner="根津美術館"),
                record("201", "2", owner="個人"),
                record("201", "3"),
            ]
        },
    )
    rows = list(iter_rows(_dataset(data_dir, "fine-arts"), 0))
    assert [row.place for row in rows] == ["根津美術館", "個人", ""]


def test_the_place_names_the_holders_when_there_is_no_location(data_dir: Path) -> None:
    """無形文化財では**誰が認定されているか**が居場所にあたる (Issue #23)。

    総合認定には 493 人を数えるものがある。一覧の 1 行には並べられないので
    先頭だけを出して残りは数で示す — 詳細を開けば全員が表で読める。
    """
    make_dataset(
        data_dir,
        "important-intangible-cultural-properties",
        {
            "99_unspecified.jsonl": [
                record("303", "1", holders=[{"kind": "保持者", "name": "伊藤赤水"}]),
                record(
                    "303",
                    "2",
                    holders=[
                        {"kind": "保持者", "name": "大城政子"},
                        {"kind": "保持者", "name": "喜納幸子"},
                        {"kind": "保持者", "name": "梶原ミエ子"},
                        {"kind": "保持者", "name": "山内太圭子"},
                    ],
                ),
                # 保持団体は代表者ではなく団体そのものが名乗る。
                record(
                    "303",
                    "3",
                    holders=[{"kind": "保持団体", "name": "日本文化財漆協会"}],
                ),
            ]
        },
    )
    rows = list(iter_rows(_dataset(data_dir, "important-intangible-cultural-properties"), 0))
    assert [row.place for row in rows] == [
        "伊藤赤水",
        "大城政子、喜納幸子 ほか 2 件",
        "日本文化財漆協会",
    ]


def _dataset(data_dir: Path, repo: str) -> Dataset:
    [found] = [dataset for dataset in discover(data_dir) if dataset.repo == repo]
    return found
