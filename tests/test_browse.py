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
    "schema_version": 1,
    "datasets": ["national-treasures", "historic-sites", "places-of-scenic-beauty"],
    "search_fields": ["name", "ridge_name", "name_kana", "ridge_name_kana", "address"],
    "axes": [
        {"key": "prefecture", "label": "所在都道府県", "values": ["京都府", "奈良県", "東京都"]},
        {"key": "types", "label": "種別", "values": ["寺院", "神社", "庭園"]},
    ],
    "fields": [
        "dataset",
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
    coordinates: tuple[float, float] | None = (35.0, 135.7),
) -> list[Any]:
    latitude, longitude = coordinates if coordinates else (None, None)
    return [
        dataset,
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
    _record(0, "2", "五重塔", "ごじゅうのとう", "奈良市", [[1], [0]], coordinates=None),
    _record(1, "3", "社殿", "しゃでん", "京都市", [[0], [1]]),
    # 1 行が 1 つの軸に 2 つの値を持つ (401 の複合指定)。
    _record(2, "4", "庭園", "ていえん", "東京都", [[2], [2, 0]]),
]

LABELS = {
    "national-treasures": "国宝（建造物）",
    "historic-sites": "史跡",
    "places-of-scenic-beauty": "名勝",
}

_HARNESS = """
import {{ createCatalog }} from {module};
let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;
const {{ payload, labels, queries }} = JSON.parse(input);
const catalog = createCatalog(payload, labels);
const answers = queries.map(({{ query, selection }}) => {{
  const chosen = Object.fromEntries(
    catalog.axes.map((axis) => [axis.key, new Set(selection?.[axis.key] ?? [])]),
  );
  const {{ matched, counts }} = catalog.filter(query ?? "", chosen);
  return {{
    names: matched.map((index) => catalog.record(index).name),
    datasets: matched.map((index) => catalog.record(index).dataset),
    mappable: matched.map((index) => catalog.record(index).mappable),
    counts: Object.fromEntries(catalog.axes.map((axis, position) => [axis.key, counts[position]])),
    axes: catalog.axes.map((axis) => ({{ key: axis.key, label: axis.label, values: axis.values }})),
  }};
}});
process.stdout.write(JSON.stringify(answers));
"""


def _ask(node: str, queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    script = _HARNESS.format(module=json.dumps(RECORDS_JS.as_posix()))
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script],
        input=json.dumps({"payload": PAYLOAD, "labels": LABELS, "queries": queries}),
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
    [answer] = _ask(node, [{}])
    assert answer["names"] == ["金堂", "五重塔", "社殿", "庭園"]


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
    assert garden["names"] == ["庭園"]
    assert temple["names"] == ["金堂", "五重塔", "庭園"]


def test_the_query_and_the_facets_apply_together(node: str) -> None:
    [answer] = _ask(node, [{"query": "京都市", "selection": {"types": [0]}}])
    assert answer["names"] == ["金堂"]


def test_counts_ignore_the_selection_on_their_own_axis(node: str) -> None:
    """自分の軸まで数に入れると、1 つ選んだ瞬間に他の値が 0 件になって選び直せない。"""
    [answer] = _ask(node, [{"selection": {"prefecture": [0]}}])
    assert answer["counts"]["prefecture"] == [2, 1, 1]  # 選んでいない値も選べる
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
