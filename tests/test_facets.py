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
    name: str | None = None,
) -> None:
    make_dataset(
        data_dir, repo, {"13_tokyo.jsonl": rows}, facets=facets, labels=labels, name=name
    )


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


def _by_criteria(data_dir: Path, values: dict[str, int], **extra: Any) -> list[Axis]:
    """指定基準の値と件数だけを持つデータセット (体系は 1 つ = まとめない)。"""
    rows = [
        record("401", f"{number}-{repeat}", criteria=value, **extra)
        for number, (value, count) in enumerate(values.items())
        for repeat in range(count)
    ]
    _dataset(data_dir, "a", rows, facets={"criteria": values})
    return _axes(data_dir)


def test_criteria_are_ordered_by_the_number_written_in_the_value(tmp_path: Path) -> None:
    """指定基準は原文が番号で並んでいる。**件数順にすると原文の並びが崩れる。**

    番号は値そのものが持っているので、基準の表をサイトに持たずに戻せる。
    """
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    axes = _by_criteria(
        data_dir,
        # 件数順なら 三 → 二 → 一 になる並び。
        {"一．公園、庭園": 1, "二．橋梁、築堤": 2, "三．花樹、花草": 3},
    )
    assert axes[0].values == ("一．公園、庭園", "二．橋梁、築堤", "三．花樹、花草")
    assert axes[0].order == "number"


def test_a_number_past_ten_is_read_as_a_number(tmp_path: Path) -> None:
    """`十一．` は `二．` の後ではなく `十．` の後。文字として並べない。"""
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    axes = _by_criteria(
        data_dir,
        {"十一．展望地点": 3, "二．橋梁、築堤": 2, "十．山岳、丘陵": 1},
    )
    assert axes[0].values == ("二．橋梁、築堤", "十．山岳、丘陵", "十一．展望地点")


def test_a_number_in_brackets_is_read_too(tmp_path: Path) -> None:
    """括弧書きの番号もある。**開きだけ半角**のものも読む (102 の重文指定基準)。"""
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    axes = _by_criteria(
        data_dir,
        {"（三）自然環境における特有の動物": 3, "(一）意匠的に優秀なもの": 1, "（二）洞穴": 2},
    )
    assert axes[0].values == (
        "(一）意匠的に優秀なもの",
        "（二）洞穴",
        "（三）自然環境における特有の動物",
    )


def test_values_without_a_number_come_after_the_numbered_ones(tmp_path: Path) -> None:
    """番号を持たない基準もある (登録有形の登録基準・国宝の重文指定基準)。

    番号順の中へ推測で混ぜない。西暦を持たない時代と同じく後ろへ件数順で回す。
    """
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    axes = _by_criteria(
        data_dir,
        {
            "保護すべき天然記念物に富んだ代表的一定の区域": 9,
            "（二）洞穴": 2,
            "（一）名木、巨樹": 1,
        },
    )
    assert axes[0].values == (
        "（一）名木、巨樹",
        "（二）洞穴",
        "保護すべき天然記念物に富んだ代表的一定の区域",
    )


def test_values_sharing_a_number_stay_in_count_order(tmp_path: Path) -> None:
    """天然記念物の `（一）` は動物・植物・地質鉱物に 1 つずつある。

    番号で決まるのはそこまでで、同じ番号どうしは既定の件数順。
    """
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    axes = _by_criteria(
        data_dir,
        {"（一）名木、巨樹": 1, "（一）岩石、鉱物": 3, "（二）洞穴": 2},
    )
    assert axes[0].values == ("（一）岩石、鉱物", "（一）名木、巨樹", "（二）洞穴")


def test_an_axis_where_a_number_is_the_exception_stays_in_count_order(tmp_path: Path) -> None:
    """番号らしき値がたまたま混ざった軸を巻き込まない。過半で決める。"""
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    _dataset(
        data_dir,
        "a",
        [record("401", "1", types="三．番号のような種別")]
        + [record("401", f"2{n}", types="城跡") for n in range(2)]
        + [record("401", f"3{n}", types="墳墓") for n in range(3)],
        facets={"types": {"三．番号のような種別": 1, "城跡": 2, "墳墓": 3}},
    )
    axes = _axes(data_dir)
    assert axes[0].order == "count"
    assert axes[0].values == ("墳墓", "城跡", "三．番号のような種別")


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


def test_an_axis_whose_values_stick_to_one_dataset_is_grouped(tmp_path: Path) -> None:
    """指定基準は体系ごとに別の語彙が 1 本の軸に混ざっている (Issue #8)。

    どの値がどの体系かは**行から導ける**ので、体系の表をサイトに持たずに済む
    (ADR 0014 / ADR 0015)。種別が増えても判定は追随する。
    """
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    _dataset(
        data_dir,
        "a",
        [record("401", f"a{n}", criteria="一．貝塚、集落跡") for n in range(3)]
        + [record("401", f"a1{n}", criteria="二．都城跡") for n in range(2)],
        facets={"criteria": {"一．貝塚、集落跡": 3, "二．都城跡": 2}},
        name="史跡",
    )
    _dataset(
        data_dir,
        "b",
        [record("401", "b1", criteria="（一）名木、巨樹")],
        facets={"criteria": {"（一）名木、巨樹": 1}},
        name="天然記念物",
    )
    _dataset(
        data_dir,
        "c",
        [record("401", "c1", criteria="一．公園、庭園")],
        facets={"criteria": {"一．公園、庭園": 1}},
        name="名勝",
    )
    [axis] = _axes(data_dir)
    assert [(group.label, group.size) for group in axis.groups] == [
        ("史跡", 2),
        ("名勝", 1),
        ("天然記念物", 1),
    ]
    # 値は体系ごとにまとまる。まとまりが持つのは区間の長さだけで、並びは
    # `values` が正本 (同じ文字列を索引に二度書かない)。
    assert axis.values == ("一．貝塚、集落跡", "二．都城跡", "一．公園、庭園", "（一）名木、巨樹")


def test_a_scheme_is_named_after_where_its_values_show_up_most(tmp_path: Path) -> None:
    """体系の名前は**その値がいちばん多く現れたデータセット** (Issue #8)。

    出どころを並べた名前にすると、特別天然記念物にも出る基準と天然記念物に
    しか出ない基準が別の見出しに割れる (実データでは指定基準が 8 でなく 12 の
    見出しになり、「史跡」を選んだ読み手に「史跡 / 特別史跡」と
    「史跡 / 名勝 / 特別史跡」が並ぶ)。読み手が要るのは**どの体系の基準か**で、
    その基準が他にどこで使われているかではない。
    """
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    _dataset(
        data_dir,
        "a",
        [record("401", f"a{n}", criteria="（一）名木、巨樹") for n in range(3)]
        + [record("401", "a9", criteria="（二）洞穴")],
        facets={"criteria": {"（一）名木、巨樹": 3, "（二）洞穴": 1}},
        name="天然記念物",
    )
    _dataset(
        data_dir,
        "b",
        [record("401", "b1", criteria="（一）名木、巨樹")],
        facets={"criteria": {"（一）名木、巨樹": 1}},
        name="特別天然記念物",
    )
    _dataset(
        data_dir,
        "c",
        [record("401", "c1", criteria="一．貝塚、集落跡")],
        facets={"criteria": {"一．貝塚、集落跡": 1}},
        name="史跡",
    )
    [axis] = _axes(data_dir)
    # 「名木」は特別天然記念物にも出るが、いちばん多いのは天然記念物。
    # そこにしか出ない「洞穴」と同じ見出しにまとまる。
    assert [(group.label, group.size) for group in axis.groups] == [
        ("天然記念物", 2),
        ("史跡", 1),
    ]


def test_an_axis_that_works_across_the_datasets_is_not_grouped(tmp_path: Path) -> None:
    """所在都道府県は 47 値すべてがどの種別にも出る (Issue #8)。

    まとめても見出しに書けるのは「ほぼ全部」だけなので、体系の見出しを付けない。
    """
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    for repo in ("a", "b", "c"):
        _dataset(
            data_dir,
            repo,
            [
                record("101", f"{repo}1", prefecture="東京都"),
                record("101", f"{repo}2", prefecture="京都府"),
            ],
            facets={"prefecture": {"東京都": 1, "京都府": 1}},
        )
    [axis] = _axes(data_dir)
    assert axis.groups == ()


def test_a_composite_designation_does_not_blur_the_schemes(tmp_path: Path) -> None:
    """複合指定は**同じ行が両方のリポジトリに書かれる** (ADR 0012)。

    数に入れると名勝の基準が史跡にも出ていることになり、値が体系をまたいで
    見える (Issue #8 のコメントの実測)。ここでは 3 つのうち 2 つの値が
    2 データセットに出ることになり、**横断の軸と見なされて見出しごと消える**。
    """
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    composite = record("401", "9", criteria=["一．公園、庭園", "一．貝塚、集落跡"])
    _dataset(
        data_dir,
        "a",
        [record("401", "1", criteria="一．貝塚、集落跡"), composite],
        facets={"criteria": {"一．貝塚、集落跡": 2, "一．公園、庭園": 1}},
        name="史跡",
    )
    _dataset(
        data_dir,
        "b",
        [record("401", "2", criteria="一．公園、庭園"), composite],
        facets={"criteria": {"一．公園、庭園": 2, "一．貝塚、集落跡": 1}},
        name="名勝",
    )
    _dataset(
        data_dir,
        "c",
        [record("401", "3", criteria="（一）名木、巨樹")],
        facets={"criteria": {"（一）名木、巨樹": 1}},
        name="天然記念物",
    )
    [axis] = _axes(data_dir)
    # 体系の並びは値の並び次第なので、ここでは 3 つに割れていることだけ見る。
    assert sorted(group.label for group in axis.groups) == ["史跡", "名勝", "天然記念物"]


def test_an_axis_that_only_one_dataset_uses_is_not_grouped(tmp_path: Path) -> None:
    """1 つのデータセットにしか値が無い軸に、体系の見出しは要らない。

    国宝・重文区分のように、軸そのものが特定の種別に属することがある。
    """
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    _dataset(
        data_dir,
        "a",
        [record("101", "1", types="住宅"), record("101", "2", types="倉庫")],
        facets={"types": {"住宅": 1, "倉庫": 1}},
        name="登録有形文化財（建造物）",
    )
    _dataset(
        data_dir,
        "b",
        [record("101", "3", prefecture="東京都")],
        facets={"prefecture": {"東京都": 1}},
    )
    axes = {axis.key: axis for axis in _axes(data_dir)}
    assert axes["types"].groups == ()


def test_grouping_keeps_the_order_inside_each_scheme(tmp_path: Path) -> None:
    """まとめ直しても、体系の中の並び (件数順・年代順) は動かさない。

    体系の並びは「その体系の最初の値がどこにいたか」で決まる。件数の多い値を
    持つ体系ほど先に来て、体系の中は件数順のまま残る。
    """
    data_dir = tmp_path / "data-repos"
    data_dir.mkdir()
    _dataset(
        data_dir,
        "a",
        [record("401", f"a{n}", criteria="一．貝塚、集落跡") for n in range(3)]
        + [record("401", "a9", criteria="二．都城跡")],
        facets={"criteria": {"一．貝塚、集落跡": 3, "二．都城跡": 1}},
        name="史跡",
    )
    _dataset(
        data_dir,
        "b",
        [record("401", f"b{n}", criteria="（一）名木、巨樹") for n in range(2)],
        facets={"criteria": {"（一）名木、巨樹": 2}},
        name="天然記念物",
    )
    _dataset(
        data_dir,
        "c",
        [record("401", "c1", criteria="一．公園、庭園")],
        facets={"criteria": {"一．公園、庭園": 1}},
        name="名勝",
    )
    [axis] = _axes(data_dir)
    # 件数順だけなら 貝塚(3) → 名木(2) → 公園(1) → 都城(1)。体系でまとめ直しても
    # 史跡の 2 値は件数順のまま並び、体系の並びは先頭の値の順で決まる。
    assert axis.values == ("一．貝塚、集落跡", "二．都城跡", "（一）名木、巨樹", "一．公園、庭園")
    assert [(group.label, group.size) for group in axis.groups] == [
        ("史跡", 2),
        ("天然記念物", 1),
        ("名勝", 1),
    ]


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
