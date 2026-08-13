"""地図に置く点のまとめ方 (site/cluster.js)。

丸の位置と件数は人が見て確かめられるが、**間違えても地図は出る**類の規則が
いくつもある — 座標を持たない行を落とすこと、画面の外を数えないこと、縮尺で
まとまり直すこと。どれも壊れたまま気付けないので機械で固定する。

Python から node を呼ぶ (テストの正本を 1 か所に保つため。test_browse.py と同じ)。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

CLUSTER_JS = Path(__file__).resolve().parents[1] / "site/cluster.js"

# site/cluster.js の CELL_SIZE。値そのものは JS 側から取るので、ここは
# 「どのくらい離せば別の升目か」を読むための写し。
CELL_SIZE = 56

_HARNESS = """
import {{ CELL_SIZE, cluster, countMappable }} from {module};
let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;
const {{ points, cases }} = JSON.parse(input);
// JSON は NaN を運べない。索引の `null` を NaN にするのは records.js と同じ扱い。
const positions = {{
  x: points.map((point) => point[0] ?? NaN),
  y: points.map((point) => point[1] ?? NaN),
}};
const answers = cases.map(({{ matched, view }}) => ({{
  cellSize: CELL_SIZE,
  mappable: countMappable(positions, matched),
  clusters: cluster(positions, matched, view),
}}));
process.stdout.write(JSON.stringify(answers));
"""

VIEW: dict[str, Any] = {
    "originX": 0,
    "originY": 0,
    "width": 200,
    "height": 200,
    "scale": 1,
    "cellSize": CELL_SIZE,
    "margin": 0,
}


def _ask(
    node: str,
    points: list[tuple[float, float] | tuple[None, None]],
    cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    script = _HARNESS.format(module=json.dumps(CLUSTER_JS.as_posix()))
    prepared = [
        {"matched": case.get("matched", list(range(len(points)))), "view": {**VIEW, **case}}
        for case in cases
    ]
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script],
        input=json.dumps({"points": points, "cases": prepared}),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return list(json.loads(completed.stdout))


def test_the_cell_size_matches_the_one_read_here(node: str) -> None:
    """升目の大きさが変わったら、このファイルの前提も読み直す。"""
    [answer] = _ask(node, [(10.0, 10.0)], [{}])
    assert answer["cellSize"] == CELL_SIZE


def test_points_in_the_same_cell_become_one_circle(node: str) -> None:
    [answer] = _ask(node, [(10.0, 10.0), (20.0, 20.0)], [{}])
    [circle] = answer["clusters"]
    assert circle["count"] == 2
    # 丸は升目の中心ではなく、まとめた点の平均に置く。中心に置くと、実際には
    # 何も無いところに丸が出る。
    assert (circle["x"], circle["y"]) == (15, 15)


def test_points_in_different_cells_stay_apart(node: str) -> None:
    [answer] = _ask(node, [(10.0, 10.0), (10.0 + CELL_SIZE, 10.0)], [{}])
    assert [circle["count"] for circle in answer["clusters"]] == [1, 1]


def test_only_a_single_point_names_its_row(node: str) -> None:
    """2 件以上をまとめた丸に、どれか 1 行を代表させない。"""
    [alone, together] = _ask(
        node,
        [(10.0, 10.0), (20.0, 20.0)],
        [{"matched": [1]}, {"matched": [0, 1]}],
    )
    assert [circle["index"] for circle in alone["clusters"]] == [1]
    assert [circle["index"] for circle in together["clusters"]] == [None]


def test_a_row_without_coordinates_is_dropped(node: str) -> None:
    """**NaN は比較がすべて偽になる。**範囲の判定に任せると画面に紛れ込む。"""
    [answer] = _ask(node, [(None, None), (10.0, 10.0)], [{}])
    assert [circle["count"] for circle in answer["clusters"]] == [1]
    assert answer["mappable"] == 1


def test_points_outside_the_screen_are_dropped(node: str) -> None:
    [answer] = _ask(node, [(10.0, 10.0), (400.0, 10.0), (10.0, 400.0)], [{}])
    assert [circle["count"] for circle in answer["clusters"]] == [1]


def test_the_margin_keeps_points_just_outside(node: str) -> None:
    """掴んで動かしている間に縁が空かないよう、画面の外側にも描いておく。"""
    [without, with_margin] = _ask(
        node, [(240.0, 10.0)], [{}, {"margin": 60, "width": 200, "height": 200}]
    )
    assert without["clusters"] == []
    assert [circle["count"] for circle in with_margin["clusters"]] == [1]


def test_the_scale_decides_what_merges(node: str) -> None:
    """縮尺を変えれば同じ密度でまとまり直す (まとめる単位は距離ではなく画素)。"""
    points = [(100.0, 100.0), (1000.0, 100.0)]
    [near, far] = _ask(
        node, points, [{"scale": 1, "width": 1200, "height": 400}, {"scale": 0.05}]
    )
    assert [circle["count"] for circle in near["clusters"]] == [1, 1]
    assert [circle["count"] for circle in far["clusters"]] == [2]


def test_the_origin_moves_the_view(node: str) -> None:
    """地図を動かすと、同じ点が画面の別の場所に来る。"""
    [answer] = _ask(node, [(300.0, 300.0)], [{"originX": 250, "originY": 250}])
    [circle] = answer["clusters"]
    assert (circle["x"], circle["y"]) == (50, 50)


def test_the_bounds_cover_what_was_merged(node: str) -> None:
    """まとめた丸を押したときに寄る先。広がりが無ければ倍率で寄る (map.js)。"""
    [answer] = _ask(node, [(10.0, 20.0), (30.0, 40.0)], [{}])
    [circle] = answer["clusters"]
    assert circle["bounds"] == {"minX": 10, "minY": 20, "maxX": 30, "maxY": 40}


def test_only_the_matched_rows_are_drawn(node: str) -> None:
    """地図は「さがす」の結果をそのまま映す (地図側に別の絞り込みを持たせない)。"""
    [answer] = _ask(node, [(10.0, 10.0), (150.0, 150.0)], [{"matched": [1]}])
    [circle] = answer["clusters"]
    assert (circle["x"], circle["y"]) == (150, 150)


def test_rows_without_coordinates_are_counted_not_hidden(node: str) -> None:
    """地図に出せない行の数は示す。黙って落とさない (Issue #32 §3)。"""
    [answer] = _ask(node, [(None, None), (None, None), (10.0, 10.0)], [{}])
    assert answer["mappable"] == 1
