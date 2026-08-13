"""画面側の絞り込み (site/records.js)。

描画は人が見るしかないが、**絞り込みの決まりごとは機械で確かめられる**。
軸の中は OR・軸をまたぐと AND・件数はその軸を除いて数える、の 3 つは
どれも間違えても画面は出るので、壊れても気付けない類の規則になる。

Python から node を呼んで確かめる (テストの正本を 1 か所に保つため。
JS 用のテスト基盤を別に持ち込むと、CI の依存が 2 系統になる)。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

RECORDS_JS = Path(__file__).resolve().parents[1] / "site/records.js"

# 3 データセット・2 軸の小さな索引。ビルドが書く形と同じ (build.py の
# `_records_payload`)。
PAYLOAD: dict[str, Any] = {
    "schema_version": 3,
    "datasets": ["national-treasures", "historic-sites", "places-of-scenic-beauty"],
    # データセットごとの JSON Lines。行は番号でここを指す (build.py の `files`)。
    "files": [["data/26_kyoto.jsonl"], ["data/13_tokyo.jsonl"], ["data/13_tokyo.jsonl"]],
    "search_fields": ["name", "ridge_name", "name_kana", "ridge_name_kana", "address"],
    "axes": [
        # 横断の軸は体系のまとまりを持たない (Issue #8)。
        {
            "key": "prefecture",
            "label": "所在都道府県",
            "values": ["京都府", "奈良県", "東京都"],
            "groups": [],
        },
        # 種別は体系ごとに語彙が張り付く。値の並びの先頭から `size` ずつ区切る。
        {
            "key": "types",
            "label": "種別",
            "values": ["寺院", "神社", "庭園"],
            "groups": [
                {"label": "国宝（建造物）", "size": 2},
                {"label": "史跡 / 名勝", "size": 1},
            ],
        },
    ],
    "fields": [
        "dataset",
        "file",
        "line",
        "ledger_id",
        "managed_id",
        "name",
        "ridge_name",
        "address",
        "designated_year",
        "url",
        "latitude",
        "longitude",
        "search",
        "facets",
    ],
    "records": [],
}


def _record(
    dataset: int,
    managed_id: str,
    name: str,
    kana: str,
    address: str,
    facets: list[list[int]],
    *,
    line: int = 1,
    coordinates: tuple[float, float] | None = (35.0, 135.7),
) -> list[Any]:
    latitude, longitude = coordinates if coordinates else (None, None)
    return [
        dataset,
        0,
        line,
        "102",
        managed_id,
        name,
        "",
        address,
        "1951",
        f"https://kunishitei.bunka.go.jp/heritage/detail/102/{managed_id}",
        latitude,
        longitude,
        f"{kana}\n{address}",
        facets,
    ]


PAYLOAD["records"] = [
    _record(0, "1", "金堂", "こんどう", "京都市", [[0], [0]]),
    # 座標を持たない行。地図には出せないが一覧には出す。
    _record(0, "2", "五重塔", "ごじゅうのとう", "奈良市", [[1], [0]], line=2, coordinates=None),
    _record(1, "3", "社殿", "しゃでん", "京都市", [[0], [1]]),
    # 1 行が 1 つの軸に 2 つの値を持つ (401 の複合指定)。
    _record(2, "4", "庭園", "ていえん", "東京都", [[2], [2, 0]]),
    # 同じ棟が別の種別にも現れる (複合指定。ADR 0012)。キーが同じで種別が違う。
    _record(1, "4", "庭園", "ていえん", "東京都", [[2], [2, 0]], line=2),
]

# index.json のデータセット。呼び名も項目の呼び名も置き場も meta.json が正本 (ADR 0014)。
DATASETS = [
    {
        "repo": "national-treasures",
        "path": "datasets/national-treasures",
        "meta": {"dataset": {"name": "国宝（建造物）"}, "labels": {"name": "名称"}},
    },
    {
        "repo": "historic-sites",
        "path": "datasets/historic-sites",
        "meta": {"dataset": {"name": "史跡"}, "labels": {"name": "名称"}},
    },
    {
        "repo": "places-of-scenic-beauty",
        "path": "datasets/places-of-scenic-beauty",
        "meta": {"dataset": {"name": "名勝"}, "labels": {"name": "名称"}},
    },
]

_HARNESS = """
import {{ createCatalog }} from {module};
let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;
const {{ payload, datasets, queries }} = JSON.parse(input);
const catalog = createCatalog(payload, datasets);
const answers = queries.map(({{ query, selection }}) => {{
  const chosen = Object.fromEntries(
    catalog.axes.map((axis) => [axis.key, new Set(selection?.[axis.key] ?? [])]),
  );
  const {{ matched, counts }} = catalog.filter(query ?? "", chosen);
  return {{
    names: matched.map((index) => catalog.record(index).name),
    datasets: matched.map((index) => catalog.record(index).dataset),
    mappable: matched.map((index) => catalog.record(index).mappable),
    siblings: matched.map((index) => catalog.record(index).siblings),
    counts: Object.fromEntries(catalog.axes.map((axis, position) => [axis.key, counts[position]])),
    axes: catalog.axes.map((axis) => ({{
      key: axis.key,
      label: axis.label,
      values: axis.values,
      groups: axis.groups,
    }})),
  }};
}});
process.stdout.write(JSON.stringify(answers));
"""


def _ask(node: str, queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    script = _HARNESS.format(module=json.dumps(RECORDS_JS.as_posix()))
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script],
        input=json.dumps({"payload": PAYLOAD, "datasets": DATASETS, "queries": queries}),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return list(json.loads(completed.stdout))


def test_the_dataset_becomes_the_first_axis(node: str) -> None:
    """種別横断のサイトなので、データセットが絞り込みの主軸になる。

    索引が持つのはリポジトリ名だけ。表示名は `meta.json` から渡す (ADR 0014)。
    """
    [answer] = _ask(node, [{}])
    assert [axis["key"] for axis in answer["axes"]] == ["dataset", "prefecture", "types"]
    assert answer["axes"][0]["values"] == ["国宝（建造物）", "史跡", "名勝"]


def test_an_empty_query_matches_everything(node: str) -> None:
    """複合指定は行として 2 つある。片方を隠すと、その種別で絞ったときに消える。"""
    [answer] = _ask(node, [{}])
    assert answer["names"] == ["金堂", "五重塔", "社殿", "庭園", "庭園"]


def test_the_query_matches_the_normalized_text(node: str) -> None:
    """打つのはカタカナでも全角でも当たる (正規化は両側で同じ — test_search.py)。"""
    [kana, place] = _ask(node, [{"query": "コンドウ"}, {"query": "京都市"}])
    assert kana["names"] == ["金堂"]
    assert place["names"] == ["金堂", "社殿"]


def test_values_inside_one_axis_are_or_ed(node: str) -> None:
    [answer] = _ask(node, [{"selection": {"prefecture": [0, 1]}}])
    assert answer["names"] == ["金堂", "五重塔", "社殿"]


def test_axes_are_and_ed(node: str) -> None:
    [answer] = _ask(node, [{"selection": {"prefecture": [0], "types": [1]}}])
    assert answer["names"] == ["社殿"]


def test_a_row_with_two_values_on_one_axis_matches_either(node: str) -> None:
    """401 の複合指定 (ADR 0012)。庭園でも寺院でも当たる。"""
    [garden, temple] = _ask(node, [{"selection": {"types": [2]}}, {"selection": {"types": [0]}}])
    assert garden["names"] == ["庭園", "庭園"]
    assert temple["names"] == ["金堂", "五重塔", "庭園", "庭園"]


def test_the_query_and_the_facets_apply_together(node: str) -> None:
    [answer] = _ask(node, [{"query": "京都市", "selection": {"types": [0]}}])
    assert answer["names"] == ["金堂"]


def test_counts_ignore_the_selection_on_their_own_axis(node: str) -> None:
    """自分の軸まで数に入れると、1 つ選んだ瞬間に他の値が 0 件になって選び直せない。"""
    [answer] = _ask(node, [{"selection": {"prefecture": [0]}}])
    assert answer["counts"]["prefecture"] == [2, 1, 2]  # 選んでいない値も選べる
    assert answer["counts"]["types"] == [1, 1, 0]  # 他の軸は京都府に絞った件数


def test_counts_follow_the_query_too(node: str) -> None:
    [answer] = _ask(node, [{"query": "奈良市"}])
    assert answer["counts"]["prefecture"] == [0, 1, 0]
    assert answer["counts"]["dataset"] == [1, 0, 0]


def test_a_row_without_coordinates_is_still_listed(node: str) -> None:
    """**座標が無い行を黙って落とさない。**地図に出せないことは一覧で示す。"""
    [answer] = _ask(node, [{"query": "ごじゅうのとう"}])
    assert answer["names"] == ["五重塔"]
    assert answer["mappable"] == [False]


def test_a_shared_building_names_the_other_datasets(node: str) -> None:
    """複合指定 (ADR 0012)。**種別ごとのサイトでは表せなかったもの**なので、
    詳細では同じ棟がどこにも入っているかを併記する。"""
    [gardens, hall] = _ask(node, [{"query": "ていえん"}, {"query": "こんどう"}])
    assert gardens["datasets"] == ["名勝", "史跡"]
    assert gardens["siblings"] == [["史跡"], ["名勝"]]
    # 1 つの種別にしかない行に、相手はいない。
    assert hall["siblings"] == [[]]


_DETAIL_HARNESS = """
import {{ createCatalog }} from {module};
let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;
const {{ payload, datasets, indexes }} = JSON.parse(input);
const places = [];
const catalog = createCatalog(payload, datasets, {{
  source: {{
    read: async (place) => {{
      places.push(place);
      return {{ name: "元の行", unknown: "索引には無い項目" }};
    }},
  }},
}});
const fields = [];
for (const index of indexes) fields.push(await catalog.detail(index));
process.stdout.write(JSON.stringify({{ places, fields }}));
"""


def _detail(node: str, indexes: list[int]) -> dict[str, Any]:
    script = _DETAIL_HARNESS.format(module=json.dumps(RECORDS_JS.as_posix()))
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script],
        input=json.dumps({"payload": PAYLOAD, "datasets": DATASETS, "indexes": indexes}),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return dict(json.loads(completed.stdout))


def test_the_detail_reads_the_row_the_index_points_at(node: str) -> None:
    """索引は行の出どころだけを持ち、項目は元の JSON Lines から読む (Issue #32 §4)。

    置き場は `meta.json` の側 (index.json の `path`) と索引の `files` から組み立てる。
    """
    answer = _detail(node, [4])
    assert answer["places"] == [
        {"url": "./datasets/historic-sites/data/13_tokyo.jsonl", "line": 2}
    ]
    assert [(field["label"], field["value"]) for field in answer["fields"][0]] == [
        ("名称", "元の行"),
        # `labels` に無いキーも落とさない (上流に項目が増えても黙って消えない)。
        ("unknown", "索引には無い項目"),
    ]


_LIMIT_HARNESS = """
import {{ visibleLimit }} from {module};
let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;
process.stdout.write(
  JSON.stringify(
    JSON.parse(input).map(({{ axis, expanded }}) => visibleLimit(axis, expanded)),
  ),
);
"""


def _limits(node: str, cases: list[dict[str, Any]]) -> list[Any]:
    script = _LIMIT_HARNESS.format(
        module=json.dumps((RECORDS_JS.parent / "browse.js").as_posix())
    )
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    # JSON に Infinity は無いので null で返る。
    return list(json.loads(completed.stdout))


def test_the_area_axis_shows_every_value(node: str) -> None:
    """所在都道府県は途中で切らない (Issue #7)。

    コード順に並べると最初に見えるのは「北海道〜栃木県」で、上位 10 値が覆うのは
    全体の 41% にすぎない。切ると探したい県にたどり着けない。
    """
    [limit] = _limits(node, [{"axis": {"key": "prefecture", "order": "area"}, "expanded": False}])
    assert limit is None  # Infinity


def test_the_other_axes_are_still_cut_at_ten(node: str) -> None:
    """時代は 211 値ある。全部並べると一覧より絞り込みの方が長くなる。"""
    limits = _limits(
        node,
        [
            {"axis": {"key": "period", "order": "period"}, "expanded": False},
            {"axis": {"key": "criteria", "order": "count"}, "expanded": False},
        ],
    )
    assert limits == [10, 10]


def test_expanding_an_axis_still_shows_everything(node: str) -> None:
    """「ほか N 件を表示」を押したあとの振る舞いは変えない。"""
    [limit] = _limits(node, [{"axis": {"key": "period", "order": "period"}, "expanded": True}])
    assert limit is None


def test_the_schemes_reach_the_screen(node: str) -> None:
    """体系のまとまりは索引が持つ (ビルドが行から測る)。画面はそれを見て畳む。"""
    [answer] = _ask(node, [{}])
    axes = {axis["key"]: axis for axis in answer["axes"]}
    assert axes["types"]["groups"] == [
        {"label": "国宝（建造物）", "size": 2},
        {"label": "史跡 / 名勝", "size": 1},
    ]
    assert axes["prefecture"]["groups"] == []
    # データセットそのものが体系なので、まとめる先はない。
    assert axes["dataset"]["groups"] == []


_GROUPS_HARNESS = """
import {{ showsGroups }} from {module};
let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;
process.stdout.write(JSON.stringify(JSON.parse(input).map(showsGroups)));
"""


def _grouped(node: str, axes: list[dict[str, Any]]) -> list[bool]:
    script = _GROUPS_HARNESS.format(
        module=json.dumps((RECORDS_JS.parent / "browse.js").as_posix())
    )
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script],
        input=json.dumps(axes),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return list(json.loads(completed.stdout))


def _axis(groups: int, values: int) -> dict[str, Any]:
    return {
        "groups": [{"label": f"体系{number}", "size": 1} for number in range(groups)],
        "values": [f"値{number}" for number in range(values)],
    }


def test_an_axis_with_many_values_from_several_schemes_is_grouped(node: str) -> None:
    """指定基準は 63 値が 12 の体系に混ざっている。まとめないと最初の画面が読めない。"""
    assert _grouped(node, [_axis(groups=12, values=63)]) == [True]


def test_a_cross_cutting_axis_is_not_grouped(node: str) -> None:
    """所在都道府県は 47 値あるが横断なので、索引にまとまりが入っていない。"""
    assert _grouped(node, [_axis(groups=0, values=47)]) == [False]


def test_a_short_axis_is_left_alone(node: str) -> None:
    """3 値の「指定 / 登録 / 選定」は体系に張り付いているが、はじめから全部見える。

    見出しを 3 つ足しても読む量が増えるだけなので、畳まずまとめず素通しする。
    """
    assert _grouped(node, [_axis(groups=3, values=3)]) == [False]
