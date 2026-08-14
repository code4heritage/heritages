"""前回の配布物との突き合わせ。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from conftest import make_dataset, record
from heritage_site.changes import (
    NOTE_EXAMPLES,
    as_markdown,
    as_notes,
    as_payload,
    compare,
    for_dataset,
    write,
    write_for_dataset,
)


@pytest.fixture
def after_dir(data_dir: Path, tmp_path: Path) -> Path:
    """`data_dir` の複製。**ここを変えたぶんが今回の差分になる。**"""
    destination = tmp_path / "after"
    shutil.copytree(data_dir, destination)
    return destination


def _rows(root: Path, filename: str) -> list[dict[str, Any]]:
    path = root / "data" / filename
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write_rows(root: Path, filename: str, rows: list[dict[str, Any]]) -> None:
    (root / "data" / filename).write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


def test_the_first_release_is_a_baseline(data_dir: Path) -> None:
    """比べる相手がいない回。**全件を「追加」として並べたりはしない。**"""
    changes = compare(data_dir, None)
    assert changes.baseline
    assert changes.has_changes
    assert changes.added == []
    assert changes.records == 5
    assert "初回のリリース" in as_notes(changes)


def test_the_same_data_is_not_a_change(data_dir: Path, after_dir: Path) -> None:
    changes = compare(after_dir, data_dir)
    assert not changes.has_changes
    assert (changes.added, changes.removed, changes.changed) == ([], [], [])


def test_a_new_designation_shows_up_as_added(data_dir: Path, after_dir: Path) -> None:
    root = after_dir / "national-treasures"
    _write_rows(
        root,
        "13_tokyo.jsonl",
        [*_rows(root, "13_tokyo.jsonl"), record("102", "00005555", name="新しい国宝")],
    )
    changes = compare(after_dir, data_dir)

    assert [entry.name for entry in changes.added] == ["新しい国宝"]
    assert changes.added[0].dataset == "national-treasures"
    assert changes.has_changes


def test_a_lifted_designation_shows_up_as_removed(data_dir: Path, after_dir: Path) -> None:
    root = after_dir / "national-treasures"
    rows = [row for row in _rows(root, "26_kyoto.jsonl") if row["name"] != "塔"]
    _write_rows(root, "26_kyoto.jsonl", rows)
    changes = compare(after_dir, data_dir)

    assert [entry.name for entry in changes.removed] == ["塔"]


def test_a_changed_field_names_the_label_and_both_values(tmp_path: Path) -> None:
    before, after = _pair(
        tmp_path,
        [record("101", "00000001", name="旧名", address="東京都千代田区")],
        [record("101", "00000001", name="新名", address="東京都港区")],
        labels={"address": "所在地（市区町村）"},
    )
    changes = compare(after, before)

    assert len(changes.changed) == 1
    summaries = [item.summary() for item in changes.changed[0].fields]
    assert "名称: 旧名 → 新名" in summaries
    assert "所在地（市区町村）: 東京都千代田区 → 東京都港区" in summaries


def test_long_text_is_summarised_by_how_much_it_grew(tmp_path: Path) -> None:
    """解説文の前後をノートに並べない (読めない)。全文は `changes.json` に残す。"""
    before, after = _pair(
        tmp_path,
        [record("101", "00000001", description="もとの解説。")],
        [record("101", "00000001", description="もとの解説。書き足したぶん。")],
        labels={"description": "解説文"},
    )
    changes = compare(after, before)

    assert [item.summary() for item in changes.changed[0].fields] == ["解説文が変わった (+8 字)"]
    payload = as_payload(changes)
    assert payload["changed"][0]["fields"][0]["after"] == "もとの解説。書き足したぶん。"


def test_a_missing_field_is_told_apart_from_a_changed_one(tmp_path: Path) -> None:
    before, after = _pair(
        tmp_path,
        [record("101", "00000001", area="10.5 ｍ2")],
        [record("101", "00000001")],
        labels={"area": "面積"},
    )
    changes = compare(after, before)
    assert [item.summary() for item in changes.changed[0].fields] == ["面積が消えた (10.5 ｍ2)"]


def test_a_list_field_is_joined_for_reading(tmp_path: Path) -> None:
    """1 行が複数の値を持つ項目がある (401 の種別・指定基準)。"""
    before, after = _pair(
        tmp_path,
        [record("401", "00000001", types=["名勝"])],
        [record("401", "00000001", types=["名勝", "史跡"])],
        labels={"types": "種別"},
    )
    changes = compare(after, before)
    assert [item.summary() for item in changes.changed[0].fields] == ["種別: 名勝 → 名勝・史跡"]


def test_leaving_one_dataset_of_a_shared_designation_is_visible(
    data_dir: Path, after_dir: Path
) -> None:
    """複合指定は種別ごとに見る。

    同じ棟が複数の種別に現れるので (ADR 0012)、`(台帳ID, 管理対象ID)` だけで
    比べると「特別史跡から外れて特別名勝に残った」が「変更なし」に化ける。
    """
    _write_rows(after_dir / "special-historic-sites", "13_tokyo.jsonl", [])
    changes = compare(after_dir, data_dir)

    assert [(entry.dataset, entry.name) for entry in changes.removed] == [
        ("special-historic-sites", "旧浜離宮庭園")
    ]
    # 特別名勝の側には残っているので、そちらは動かない。
    assert not for_dataset(changes, "special-places-of-scenic-beauty").has_changes


def test_a_new_dataset_is_a_change(data_dir: Path, after_dir: Path) -> None:
    make_dataset(after_dir, "new-kind", {"13_tokyo.jsonl": [record("401", "00007777")]})
    changes = compare(after_dir, data_dir)

    assert changes.datasets_added == ["new-kind"]
    assert changes.has_changes


def test_a_removed_dataset_is_a_change(data_dir: Path, after_dir: Path) -> None:
    shutil.rmtree(after_dir / "special-historic-sites")
    changes = compare(after_dir, data_dir)

    assert changes.datasets_removed == ["special-historic-sites"]
    # 行も消えるが、呼び名は前回の `meta.json` から引ける。
    assert changes.removed[0].dataset_name == "特別史跡"


def test_a_month_that_only_moved_the_accessed_date_is_not_a_change(
    data_dir: Path, after_dir: Path
) -> None:
    """利用日は毎月動く (ADR 0018)。**これを差分に数えると毎月空のリリースが立つ。**"""
    path = after_dir / "national-treasures/meta.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta["source"]["accessed_date"] = "2026-09-02"
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    changes = compare(after_dir, data_dir)
    assert not changes.has_changes
    # 利用日そのものは配布物の説明に使うので、新しい方を採る。
    assert changes.accessed_date == "2026-09-02"


def test_a_dataset_view_only_carries_its_own_rows(data_dir: Path, after_dir: Path) -> None:
    root = after_dir / "national-treasures"
    _write_rows(
        root,
        "13_tokyo.jsonl",
        [*_rows(root, "13_tokyo.jsonl"), record("102", "00005555", name="新しい国宝")],
    )
    _write_rows(after_dir / "special-historic-sites", "13_tokyo.jsonl", [])
    changes = compare(after_dir, data_dir)

    only = for_dataset(changes, "national-treasures")
    assert [entry.name for entry in only.added] == ["新しい国宝"]
    assert only.removed == []
    assert only.records == 4
    assert len(changes.removed) == 1  # 元の差分は減っていない


def test_the_notes_stop_at_the_examples_but_the_full_list_does_not(
    data_dir: Path, after_dir: Path
) -> None:
    """ノートは 125,000 字が上限。全量は `changes.md` へ送る。"""
    root = after_dir / "national-treasures"
    extra = [
        record("102", f"0000{index:04d}", name=f"追加 {index}")
        for index in range(NOTE_EXAMPLES + 5)
    ]
    _write_rows(root, "13_tokyo.jsonl", [*_rows(root, "13_tokyo.jsonl"), *extra])
    changes = compare(after_dir, data_dir)

    notes = as_notes(changes)
    assert notes.count("- **追加 ") == NOTE_EXAMPLES
    assert "ほか 5 件 (全量は `changes.md`)" in notes
    assert as_markdown(changes).count("- **追加 ") == NOTE_EXAMPLES + 5


def test_write_puts_the_cross_type_files_and_one_folder_per_dataset(
    data_dir: Path, after_dir: Path, tmp_path: Path
) -> None:
    changes = compare(after_dir, data_dir)
    out = tmp_path / "dist"
    write(changes, out)
    only = write_for_dataset(
        changes,
        out / "datasets/national-treasures",
        repo="national-treasures",
        archive="national-treasures-jsonl.zip",
    )

    payload = json.loads((out / "changes.json").read_text(encoding="utf-8"))
    assert payload["has_changes"] is False
    assert {item["repo"] for item in payload["datasets"]} == {
        "national-treasures",
        "special-historic-sites",
        "special-places-of-scenic-beauty",
    }
    assert not only.has_changes
    notes = (out / "datasets/national-treasures/notes.md").read_text(encoding="utf-8")
    # 種別ごとのノートは自分の ZIP を案内し、全部入りへの行き先も示す。
    assert "national-treasures-jsonl.zip" in notes
    assert "code4heritage/heritages/releases/latest" in notes


def _pair(
    tmp_path: Path,
    before_rows: list[dict[str, Any]],
    after_rows: list[dict[str, Any]],
    *,
    labels: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    """1 データセットだけの before / after を組む。"""
    paths = []
    for name, rows in (("before", before_rows), ("after", after_rows)):
        directory = tmp_path / name
        directory.mkdir()
        make_dataset(directory, "only", {"13_tokyo.jsonl": rows}, labels=labels)
        paths.append(directory)
    return paths[0], paths[1]
