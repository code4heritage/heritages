"""絞り込みの軸。

軸の表をサイトに持たないので (`meta.json` の `facets` から作る)、ここで
確かめるのは「データがこう来たら軸がこうなる」であって、軸の名前ではない。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from conftest import make_dataset, record
from heritage_site.datasets import discover, iter_rows
from heritage_site.facets import Axis, axis_keys, build_axes


def _axes(data_dir: Path) -> list[Axis]:
    datasets = discover(data_dir)
    keys = axis_keys(datasets)
    rows = [
        row
        for index, dataset in enumerate(datasets)
        for row in iter_rows(dataset, index, facet_keys=keys)
    ]
    return build_axes(datasets, rows, keys)


def _dataset(
    data_dir: Path,
    repo: str,
    rows: list[dict[str, Any]],
    *,
    facets: dict[str, dict[str, int]],
    labels: dict[str, str] | None = None,
) -> None:
    make_dataset(data_dir, repo, {"13_tokyo.jsonl": rows}, facets=facets, labels=labels)


def test_the_axes_come_from_the_metadata(tmp_path: Path) -> None:
    """軸の名前をサイトに持たない。`meta.json` が宣言した軸だけが出る。"""
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    _dataset(
        data_dir,
        "a",
        [record("101", "1", prefecture="東京都", owner="誰か")],
        facets={"prefecture": {"東京都": 1}},
    )
    axes = _axes(data_dir)
    # 行に値があっても、meta.json が軸として宣言していない `owner` は出ない。
    assert [axis.key for axis in axes] == ["prefecture"]
    assert axes[0].values == ("東京都",)


def test_an_axis_with_no_vocabulary_is_dropped(tmp_path: Path) -> None:
    """語彙が空ならその軸ごと出さない (重伝建の `period` は全行空)。

    行を読む前に落とす — 空の軸を数に入れると、軸の並び (宣言している
    データセットの数) まで歪む。
    """
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    _dataset(
        data_dir,
        "a",
        [record("103", "1", prefecture="東京都")],
        facets={"prefecture": {"東京都": 1}, "period": {}},
    )
    assert axis_keys(discover(data_dir)) == ["prefecture"]
    assert [axis.key for axis in _axes(data_dir)] == ["prefecture"]


def test_an_axis_declared_but_never_used_is_dropped(tmp_path: Path) -> None:
    """宣言だけあって行が 1 つも値を持たない軸も、選べないので出さない。"""
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    _dataset(
        data_dir,
        "a",
        [record("101", "1", prefecture="東京都")],
        facets={"prefecture": {"東京都": 1}, "period": {"江戸": 1}},
    )
    assert [axis.key for axis in _axes(data_dir)] == ["prefecture"]


def test_a_row_can_carry_two_values_on_one_axis(tmp_path: Path) -> None:
    """401 の複合指定は種別を 2 つ持つ (ADR 0012)。"""
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    _dataset(
        data_dir,
        "a",
        [record("401", "1", types=["特別名勝", "特別史跡"])],
        facets={"types": {"特別名勝": 1, "特別史跡": 1}},
    )
    axes = _axes(data_dir)
    assert sorted(axes[0].values) == sorted(["特別名勝", "特別史跡"])


def test_the_axes_are_ordered_by_how_many_datasets_declare_them(tmp_path: Path) -> None:
    """種別をまたいで効く軸ほど先に出す。"""
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    _dataset(
        data_dir,
        "a",
        [record("101", "1", prefecture="東京都", owner_type="市区町村")],
        facets={"prefecture": {"東京都": 1}, "owner_type": {"市区町村": 1}},
    )
    _dataset(
        data_dir,
        "b",
        [record("401", "2", prefecture="京都府")],
        facets={"prefecture": {"京都府": 1}},
    )
    assert [axis.key for axis in _axes(data_dir)] == ["prefecture", "owner_type"]


def test_the_values_are_ordered_by_how_many_rows_carry_them(tmp_path: Path) -> None:
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    _dataset(
        data_dir,
        "a",
        [
            record("101", "1", prefecture="東京都"),
            record("101", "2", prefecture="京都府"),
            record("101", "3", prefecture="京都府"),
        ],
        facets={"prefecture": {"東京都": 1, "京都府": 2}},
    )
    assert _axes(data_dir)[0].values == ("京都府", "東京都")


def test_periods_are_ordered_by_the_median_western_year(tmp_path: Path) -> None:
    """**年代表をハードコードしない。**西暦の中央値で並べれば年代順になる。"""
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    _dataset(
        data_dir,
        "a",
        [
            record("102", "1", period="明治", western_year="1887"),
            record("102", "2", period="明治", western_year="1901"),
            record("102", "3", period="鎌倉前期", western_year="1223"),
            record("102", "4", period="江戸中期", western_year="1695"),
            record("102", "5", period="江戸中期", western_year="1700"),
            record("102", "6", period="江戸中期", western_year="1710"),
        ],
        facets={"period": {"明治": 2, "鎌倉前期": 1, "江戸中期": 3}},
    )
    # 件数順なら 江戸中期 → 明治 → 鎌倉前期 になる。年代順が優先される。
    assert _axes(data_dir)[0].values == ("鎌倉前期", "江戸中期", "明治")


def test_a_western_year_written_as_a_range_still_orders_the_period(tmp_path: Path) -> None:
    """原文の 3 割は `1868-1911` `1905頃` のように 1 つの数ではない。"""
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    _dataset(
        data_dir,
        "a",
        [
            record("101", "1", period="明治", western_year="1868-1911"),
            record("101", "2", period="桃山", western_year="1596頃"),
        ],
        facets={"period": {"明治": 1, "桃山": 1}},
    )
    assert _axes(data_dir)[0].values == ("桃山", "明治")


def test_periods_without_a_western_year_come_after_the_dated_ones(tmp_path: Path) -> None:
    """史跡の「中世」「古代」は西暦を持たない。**年代順の中へ推測で混ぜない。**"""
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    _dataset(
        data_dir,
        "a",
        [
            record("401", "1", period="中世"),
            record("401", "2", period="中世"),
            record("401", "3", period="古代"),
            record("102", "4", period="明治", western_year="1887"),
        ],
        facets={"period": {"中世": 2, "古代": 1, "明治": 1}},
    )
    assert _axes(data_dir)[0].values == ("明治", "中世", "古代")


def test_the_label_follows_the_datasets_that_declare_it(tmp_path: Path) -> None:
    """同じ軸を分類ごとに違う名前で呼ぶ (指定基準 / 重文指定基準)。"""
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    for repo, label in (("a", "指定基準"), ("b", "指定基準"), ("c", "重文指定基準")):
        _dataset(
            data_dir,
            repo,
            [record("401", repo, criteria="基準")],
            facets={"criteria": {"基準": 1}},
            labels={"criteria": label},
        )
    assert _axes(data_dir)[0].label == "指定基準"


def test_an_axis_without_a_label_falls_back_to_the_key(tmp_path: Path) -> None:
    """呼び名を推測で書き起こさない。原文が無いと分かる方がよい。"""
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    _dataset(
        data_dir,
        "a",
        [record("101", "1", prefecture="東京都")],
        facets={"prefecture": {"東京都": 1}},
    )
    assert _axes(data_dir)[0].label == "prefecture"
