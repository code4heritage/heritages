"""配信ディレクトリの組み立て。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

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


def _records(out: Path) -> dict[str, Any]:
    payload = json.loads((out / "records.json").read_text(encoding="utf-8"))
    columns = {field: index for index, field in enumerate(payload["fields"])}
    payload["by_key"] = {
        record[columns["managed_id"]]: {field: record[index] for field, index in columns.items()}
        for record in payload["records"]
    }
    return payload


def test_every_row_is_in_the_index(data_dir: Path, tmp_path: Path) -> None:
    """**座標が無い行を黙って落とさない。**地図に出せないだけで一覧には出す。"""
    out = tmp_path / "dist"
    _build(data_dir, out)
    payload = _records(out)
    assert len(payload["records"]) == 5
    assert all(len(record) == len(payload["fields"]) for record in payload["records"])
    without_coordinates = payload["by_key"]["00001235"]
    assert without_coordinates["latitude"] is None
    assert without_coordinates["longitude"] is None


def test_the_index_drops_coordinates_outside_japan(data_dir: Path, tmp_path: Path) -> None:
    """元データの誤りで地図に置けない 1 件も、行としては配る。"""
    make_dataset(
        data_dir,
        "registered-tangible-cultural-properties",
        {"03_iwate.jsonl": [record("101", "00013209", latitude=39.54161944, longitude=39.541475)]},
    )
    out = tmp_path / "dist"
    report = _build(data_dir, out)
    outside = _records(out)["by_key"]["00013209"]
    assert outside["latitude"] is None
    assert (out / "datasets/registered-tangible-cultural-properties/data/03_iwate.jsonl").is_file()
    assert report.with_coordinates > report.mapped  # type: ignore[attr-defined]


def test_the_index_carries_the_search_text(data_dir: Path, tmp_path: Path) -> None:
    make_dataset(
        data_dir,
        "registered-tangible-cultural-properties",
        {
            "01_hokkaido.jsonl": [
                record("101", "00001111", name="ＪＲ小樽駅", name_kana="ジェイアールオタルエキ")
            ]
        },
    )
    out = tmp_path / "dist"
    _build(data_dir, out)
    assert _records(out)["by_key"]["00001111"]["search"] == "jr小樽駅\nじぇいあーるおたるえき"


def test_the_index_carries_the_facet_values_as_numbers(data_dir: Path, tmp_path: Path) -> None:
    """値の名前を行ごとに繰り返さない。番号の指す先は `axes` が持つ。"""
    make_dataset(
        data_dir,
        "natural-monuments",
        {"13_tokyo.jsonl": [record("401", "00002222", prefecture="東京都")]},
        facets={"prefecture": {"東京都": 1}},
    )
    out = tmp_path / "dist"
    _build(data_dir, out)
    payload = _records(out)
    axis = payload["axes"][0]
    assert axis["key"] == "prefecture"
    numbers = payload["by_key"]["00002222"]["facets"][0]
    assert [axis["values"][number] for number in numbers] == ["東京都"]
    # 軸を宣言していないデータセットの行は、その軸の値を持たない。
    assert payload["by_key"]["00001235"]["facets"][0] == []


def test_the_index_takes_the_year_from_a_date_of_any_length(data_dir: Path, tmp_path: Path) -> None:
    """日付は 4 / 7 / 10 文字の可変長。先頭 4 文字がどれでも年になる。"""
    make_dataset(
        data_dir,
        "natural-monuments",
        {
            "13_tokyo.jsonl": [
                record("401", "00003333", designated_date="1922-03-08"),
                record("401", "00004444", designated_date="1922"),
            ]
        },
    )
    out = tmp_path / "dist"
    _build(data_dir, out)
    payload = _records(out)
    assert payload["by_key"]["00003333"]["designated_year"] == "1922"
    assert payload["by_key"]["00004444"]["designated_year"] == "1922"
    # キーが無い = 値なし。日付を持たない行は年も持たない。
    assert payload["by_key"]["00001235"]["designated_year"] == ""


def test_build_is_deterministic(data_dir: Path, tmp_path: Path) -> None:
    """同じ入力なら同じバイト列。データが変わらない月に差分を立てない。"""
    first, second = tmp_path / "a", tmp_path / "b"
    _build(data_dir, first)
    _build(data_dir, second)
    for name in ("index.json", "records.json"):
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
