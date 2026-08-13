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


def _by_area(data_dir: Path, files: dict[str, list[dict[str, Any]]]) -> list[Axis]:
    """地域ごとにファイルを分けたデータセット (データリポジトリと同じ形)。"""
    vocabulary: dict[str, int] = {}
    for rows in files.values():
        for row in rows:
            vocabulary[row["prefecture"]] = vocabulary.get(row["prefecture"], 0) + 1
    make_dataset(data_dir, "a", files, facets={"prefecture": vocabulary})
    return _axes(data_dir)


def test_the_area_axis_is_ordered_by_the_code_not_by_the_count(tmp_path: Path) -> None:
    """所在都道府県は総務省の都道府県コード順 (Issue #7)。

    件数順だと探したい県の位置が予測できず、件数は更新のたびに動くので、
    同じ県が先月と違う場所に来る。コードはデータの側 (ファイル名) にある。
    """
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    axes = _by_area(
        data_dir,
        {
            # 件数順なら 京都府 → 東京都 → 北海道 になる並び。
            "01_hokkaido.jsonl": [record("101", "1", prefecture="北海道")],
            "13_tokyo.jsonl": [record("101", f"1{n}", prefecture="東京都") for n in range(2)],
            "26_kyoto.jsonl": [record("101", f"2{n}", prefecture="京都府") for n in range(3)],
        },
    )
    assert axes[0].values == ("北海道", "東京都", "京都府")
    assert axes[0].order == "area"


def test_the_area_order_does_not_spread_to_other_axes(tmp_path: Path) -> None:
    """地域ごとにファイルが分かれていても、並べ替わるのは所在都道府県だけ。"""
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    make_dataset(
        data_dir,
        "a",
        {
            "01_hokkaido.jsonl": [record("101", "1", prefecture="北海道", types="住宅")],
            "13_tokyo.jsonl": [
                record("101", f"2{n}", prefecture="東京都", types="倉庫") for n in range(2)
            ],
        },
        facets={
            "prefecture": {"北海道": 1, "東京都": 2},
            "types": {"住宅": 1, "倉庫": 2},
        },
    )
    axes = {axis.key: axis for axis in _axes(data_dir)}
    assert axes["prefecture"].order == "area"
    assert axes["types"].order == "count"
    # 種別は件数の多い順のまま (ファイルが 1 つずつでも巻き込まれない)。
    assert axes["types"].values == ("倉庫", "住宅")


def test_the_area_order_falls_back_when_the_naming_breaks(tmp_path: Path) -> None:
    """ファイル名からコードが読めなくなったら件数順へ戻す (Issue #7)。

    この並びはデータリポジトリの命名という別の約束に乗っている。黙って
    コード順のつもりで壊れた並びを出すより、件数順に戻る方がよい。
    """
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    axes = _by_area(
        data_dir,
        {
            "hokkaido.jsonl": [record("101", "1", prefecture="北海道")],
            "tokyo.jsonl": [record("101", f"1{n}", prefecture="東京都") for n in range(2)],
        },
    )
    assert axes[0].values == ("東京都", "北海道")
    assert axes[0].order == "count"


def test_two_areas_in_one_file_is_not_an_area_axis(tmp_path: Path) -> None:
    """1 つのファイルに 2 つの値が入っていれば、コードは値を決められない。"""
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    axes = _by_area(
        data_dir,
        {
            "13_tokyo.jsonl": [
                record("101", "1", prefecture="東京都"),
                record("101", "2", prefecture="北海道"),
            ],
        },
    )
    assert axes[0].order == "count"


def test_the_period_axis_keeps_its_own_order(tmp_path: Path) -> None:
    """地域の見分けが時代を巻き込まないこと。"""
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    make_dataset(
        data_dir,
        "a",
        {
            "01_hokkaido.jsonl": [record("102", "1", period="明治", western_year="1887")],
            "13_tokyo.jsonl": [record("102", "2", period="江戸", western_year="1750")],
        },
        facets={"period": {"明治": 1, "江戸": 1}},
    )
    axis = _axes(data_dir)[0]
    assert axis.values == ("江戸", "明治")
    assert axis.order == "period"
