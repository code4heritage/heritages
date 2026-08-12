"""ビルド時の不変条件。

「壊れたら止まる」ことをテストで固定する。止まらない検査は無いのと同じなので、
1 件ずつ壊して `error` が出ることを確かめる。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from conftest import make_dataset, record
from heritage_site import checks
from heritage_site.datasets import discover, iter_rows

TODAY = date(2026, 8, 13)


def _run(data_dir: Path, **kwargs: object) -> list[checks.Finding]:
    datasets = discover(data_dir)
    rows = [row for index, dataset in enumerate(datasets) for row in iter_rows(dataset, index)]
    return checks.run(datasets, rows, today=TODAY, **kwargs)  # type: ignore[arg-type]


def _errors(findings: list[checks.Finding], name: str) -> list[checks.Finding]:
    return [f for f in findings if f.check == name and f.level == "error"]


def test_healthy_data_has_no_errors(data_dir: Path) -> None:
    findings = _run(data_dir)
    assert not checks.has_errors(findings), [f.message for f in findings]


def test_unsupported_schema_version_fails(data_dir: Path) -> None:
    make_dataset(data_dir, "future", {"13_tokyo.jsonl": []}, schema_version=99)
    assert _errors(_run(data_dir), "schema_version")


def test_stale_accessed_date_fails(data_dir: Path) -> None:
    """月次の差分更新が止まったことに気付く唯一の仕掛け (ADR 0018)。"""
    make_dataset(data_dir, "stale", {"13_tokyo.jsonl": []}, accessed_date="2026-01-01")
    assert _errors(_run(data_dir), "accessed_date")


def test_accessed_date_within_the_window_passes(data_dir: Path) -> None:
    make_dataset(data_dir, "recent", {"13_tokyo.jsonl": []}, accessed_date="2026-07-05")
    assert not _errors(_run(data_dir, max_age_days=45), "accessed_date")


def test_unreadable_accessed_date_fails(data_dir: Path) -> None:
    make_dataset(data_dir, "odd", {"13_tokyo.jsonl": []}, accessed_date="2026年8月12日")
    assert _errors(_run(data_dir), "accessed_date")


def test_record_count_mismatch_fails(data_dir: Path) -> None:
    make_dataset(
        data_dir,
        "miscounted",
        {"13_tokyo.jsonl": [record("101", "00000001")]},
        counts={"records": 2, "files": 1, "with_coordinates": 0},
    )
    assert _errors(_run(data_dir), "counts")


def test_per_file_count_mismatch_fails(data_dir: Path) -> None:
    make_dataset(
        data_dir,
        "miscounted-file",
        {"13_tokyo.jsonl": [record("101", "00000001")]},
        declared_files=[{"path": "data/13_tokyo.jsonl", "records": 5}],
    )
    assert _errors(_run(data_dir), "counts")


def test_undeclared_file_fails(data_dir: Path) -> None:
    """meta.json に無いファイルを配ると、件数と中身が静かにずれる。"""
    make_dataset(
        data_dir,
        "extra-file",
        {"13_tokyo.jsonl": [record("101", "00000001")]},
        declared_files=[],
        counts={"records": 1, "files": 0, "with_coordinates": 0},
    )
    assert _errors(_run(data_dir), "files")


def test_declared_but_missing_file_fails(data_dir: Path) -> None:
    make_dataset(
        data_dir,
        "ghost-file",
        {},
        declared_files=[{"path": "data/13_tokyo.jsonl", "records": 1}],
        counts={"records": 0, "files": 1, "with_coordinates": 0},
    )
    assert _errors(_run(data_dir), "files")


def test_empty_required_field_fails(data_dir: Path) -> None:
    make_dataset(data_dir, "nameless", {"13_tokyo.jsonl": [record("101", "00000001", name="")]})
    assert _errors(_run(data_dir), "required_fields")


def test_shared_key_with_conflicting_url_fails(data_dir: Path) -> None:
    """同じ棟が違う原本を指していたら、複合指定ではなく別物を同じキーで数えている。"""
    make_dataset(
        data_dir,
        "special-natural-monuments",
        {"13_tokyo.jsonl": [record("401", "00009999", url="https://example.invalid/other")]},
    )
    assert _errors(_run(data_dir), "shared_keys")


def test_shared_key_with_the_same_url_passes(data_dir: Path) -> None:
    """複合指定そのものは正常。114 件あるので、これを弾いてはいけない (ADR 0012)。"""
    assert not _errors(_run(data_dir), "shared_keys")


def test_same_key_repeated_inside_one_dataset_is_not_a_conflict(data_dir: Path) -> None:
    """棟に展開される分類は 1 指定が複数行になる。同じデータセット内の重複は正常。"""
    make_dataset(
        data_dir,
        "important-cultural-properties",
        {
            "13_tokyo.jsonl": [
                record("102", "00007777", name="本堂"),
                record("102", "00007777", name="山門"),
            ]
        },
    )
    assert not _errors(_run(data_dir), "shared_keys")


def test_missing_coordinates_beyond_the_ratio_fails(data_dir: Path) -> None:
    findings = _run(data_dir, max_missing_coordinate_ratio=0.0, min_missing_coordinates=0)
    assert _errors(findings, "coordinates")


def test_missing_coordinates_within_the_ratio_only_reports(data_dir: Path) -> None:
    findings = _run(data_dir, max_missing_coordinate_ratio=0.5, min_missing_coordinates=0)
    reported = [f for f in findings if f.check == "coordinates"]
    assert [f.level for f in reported] == ["info"]


def test_a_few_missing_coordinates_do_not_fail_a_small_dataset(data_dir: Path) -> None:
    """件数の少ないデータセットでは比率が暴れる。件数の裏付けが要る。"""
    findings = _run(data_dir, max_missing_coordinate_ratio=0.0)
    assert not _errors(findings, "coordinates")


def test_coordinates_outside_japan_warn_without_failing(data_dir: Path) -> None:
    """上流の誤字 1 件で毎月の反映を止めない。報せて地図から除くだけにする。"""
    make_dataset(
        data_dir,
        "registered-tangible-cultural-properties",
        {
            "03_iwate.jsonl": [
                # 経度欄に緯度が入っている実在の誤り (登録有形文化財 00013209)。
                record("101", "00013209", latitude=39.54161944, longitude=39.541475),
            ]
        },
    )
    findings = _run(data_dir)
    bbox = [f for f in findings if f.check == "bbox"]
    assert [f.level for f in bbox] == ["warning"]
    assert not checks.has_errors(findings)
    assert "00013209" in bbox[0].examples[0]
