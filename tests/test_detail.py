"""詳細ビューが並べる項目 (site/detail.js)。

描画は人が見るしかないが、**どの項目をどの順で・どんな形で出すかは機械で
確かめられる**。項目の表をサイトに持たず `meta.json` の `labels` に従うのが要で、
ここが崩れると「持っているのに出ない項目」が黙って生まれる。

Python から node を呼ぶ (test_browse.py と同じ理由 — テストの基盤を 2 系統に
しない)。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

DETAIL_JS = Path(__file__).resolve().parents[1] / "site/detail.js"

# 国宝 (建造物) の `labels` を縮めたもの。並びは meta.json が持つ順そのまま
# (クローラーの出力スキーマ順)。
LABELS = {
    "ledger_id": "台帳ID",
    "managed_id": "管理対象ID",
    "url": "詳細ページ",
    "name": "名称",
    "quantity": "員数",
    "types": "種別",
    "structure": "構造及び形式等",
    "latitude": "緯度",
    "description": "解説文",
    "annexes": "附指定",
    "annexes.name": "附名称",
    "annexes.quantity": "附員数",
    "has_photo": "写真の有無",
}

_HARNESS = """
import {{ fieldsOf }} from {module};
let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;
const {{ labels, records }} = JSON.parse(input);
process.stdout.write(JSON.stringify(records.map((record) => fieldsOf(record, labels))));
"""


def _fields(node: str, records: list[dict[str, Any]], labels: Any = None) -> list[list[Any]]:
    script = _HARNESS.format(module=json.dumps(DETAIL_JS.as_posix()))
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script],
        input=json.dumps({"labels": LABELS if labels is None else labels, "records": records}),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return list(json.loads(completed.stdout))


def test_the_order_and_the_names_come_from_the_labels(node: str) -> None:
    """項目の表をサイトに持たない (ADR 0014)。種別ごとに項目が違っても手を入れない。"""
    [fields] = _fields(node, [{"name": "東大寺南大門", "quantity": "1棟", "ledger_id": "102"}])
    assert [field["label"] for field in fields] == ["台帳ID", "名称", "員数"]


def test_a_key_the_labels_do_not_know_is_still_shown(node: str) -> None:
    """**知らない項目でも落とさない。**上流に項目が増えたとき、黙って消えるより
    名前のまま出る方がよい (気付ける)。"""
    [fields] = _fields(node, [{"name": "名称", "future_key": "これから増える値"}])
    assert [(field["label"], field["value"]) for field in fields] == [
        ("名称", "名称"),
        ("future_key", "これから増える値"),
    ]


def test_missing_values_do_not_become_empty_rows(node: str) -> None:
    """キーが無い = 値なし (`null` は来ない)。空文字と空の配列も出さない。"""
    [fields] = _fields(node, [{"name": "名称", "structure": "", "types": []}])
    assert [field["key"] for field in fields] == ["name"]


def test_an_array_of_strings_becomes_a_list(node: str) -> None:
    """種別・指定基準は 1 行が複数の値を持つ (401 の複合指定など)。"""
    [fields] = _fields(node, [{"types": ["特別名勝", "特別史跡"]}])
    assert fields[0]["kind"] == "list"
    assert fields[0]["values"] == ["特別名勝", "特別史跡"]


def test_an_array_of_objects_becomes_a_table(node: str) -> None:
    """附指定 (附名称 / 附員数) の組。列の呼び名も `labels` が持つ。"""
    annexes = [{"name": "木札", "quantity": "１枚"}, {"name": "味噌蔵", "quantity": "１棟"}]
    [fields] = _fields(node, [{"annexes": annexes}])
    assert fields[0]["kind"] == "table"
    assert [column["label"] for column in fields[0]["columns"]] == ["附名称", "附員数"]
    assert fields[0]["rows"] == [["木札", "１枚"], ["味噌蔵", "１棟"]]


def test_a_table_keeps_columns_that_only_some_rows_have(node: str) -> None:
    """行によって持つ項目が違っても落とさない (異動種別を持たない措置がある)。"""
    [fields] = _fields(
        node,
        [{"measures": [{"date": "1967-12-11"}, {"date": "1991-05-28", "types": ["名称変更"]}]}],
        labels={"measures": "指定等後に行った措置", "measures.date": "異動年月日"},
    )
    assert [column["label"] for column in fields[0]["columns"]] == ["異動年月日", "types"]
    assert fields[0]["rows"] == [["1967-12-11", ""], ["1991-05-28", "名称変更"]]


def test_flags_read_as_words(node: str) -> None:
    """真偽値をそのまま出さない。「あり」「なし」で読めるようにする。"""
    [fields] = _fields(node, [{"has_photo": True, "has_measures": False}])
    assert [(field["kind"], field["value"]) for field in fields] == [
        ("flag", True),
        ("flag", False),
    ]


def test_the_photo_flag_points_at_the_original_page(node: str) -> None:
    """写真の実体は持てない (ADR 0007)。あると言うだけで終わらせない。"""
    [photo, measures] = _fields(node, [{"has_photo": True}, {"has_measures": True}])
    assert photo[0]["original"] is True
    # 措置の有無は原本へ案内する類の項目ではない (中身はこの行が持っている)。
    assert measures[0]["original"] is False


def test_the_original_page_becomes_a_link(node: str) -> None:
    [fields] = _fields(
        node, [{"url": "https://kunishitei.bunka.go.jp/heritage/detail/102/2435"}]
    )
    assert fields[0]["kind"] == "link"


def test_coordinates_stay_readable_as_numbers(node: str) -> None:
    """緯度経度は数値で来る。文字列に混ぜて落とさない。"""
    [fields] = _fields(node, [{"latitude": 34.68579351}])
    assert (fields[0]["kind"], fields[0]["value"]) == ("number", "34.68579351")


# 元の行の読み出し。読みに行く回数そのものが約束なので、取りに行く関数を差し替えて
# 回数を数える。
_SOURCE_HARNESS = """
import {{ createRecordSource }} from {module};
let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;
const {{ files, reads }} = JSON.parse(input);
const calls = [];
const source = createRecordSource({{
  load: async (url) => {{
    calls.push(url);
    if (!(url in files)) throw new Error(`HTTP 404 (${{url}})`);
    return files[url].split("\\n");
  }},
}});
const rows = [];
for (const place of reads) {{
  try {{
    rows.push(await source.read(place));
  }} catch (error) {{
    rows.push({{ error: error.message }});
  }}
}}
process.stdout.write(JSON.stringify({{ rows, calls }}));
"""


def _read(node: str, files: dict[str, str], reads: list[dict[str, Any]]) -> dict[str, Any]:
    script = _SOURCE_HARNESS.format(module=json.dumps(DETAIL_JS.as_posix()))
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script],
        input=json.dumps({"files": files, "reads": reads}),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return dict(json.loads(completed.stdout))


TOKYO = './data/13_tokyo.jsonl'
FILES = {
    TOKYO: '{"name": "1 行目"}\n{"name": "2 行目"}\n',
    "./data/26_kyoto.jsonl": '{"name": "京都の 1 行目"}\n',
}


def test_a_row_is_read_by_its_line_number(node: str) -> None:
    """`(台帳ID, 管理対象ID)` は一意ではない (102 は 1 指定が複数の棟に展開される)。
    行番号でなければ隣の棟を出しかねない。"""
    answer = _read(node, FILES, [{"url": TOKYO, "line": 2}])
    assert answer["rows"] == [{"name": "2 行目"}]


def test_the_same_file_is_fetched_once(node: str) -> None:
    """同じ県の 2 件目を開いても取りに行かない (1 ファイル最大 1.1 MB)。"""
    answer = _read(
        node,
        FILES,
        [
            {"url": TOKYO, "line": 1},
            {"url": TOKYO, "line": 2},
            {"url": "./data/26_kyoto.jsonl", "line": 1},
        ],
    )
    assert answer["calls"] == [TOKYO, "./data/26_kyoto.jsonl"]


def test_a_failed_read_can_be_tried_again(node: str) -> None:
    """失敗を覚えると、開き直しても二度と出なくなる。"""
    answer = _read(node, {}, [{"url": TOKYO, "line": 1}, {"url": TOKYO, "line": 1}])
    assert [row["error"] for row in answer["rows"]] == [f"HTTP 404 ({TOKYO})"] * 2
    assert answer["calls"] == [TOKYO, TOKYO]


def test_a_line_that_is_not_there_says_so(node: str) -> None:
    """索引とデータがずれたときに、空の詳細を黙って出さない。"""
    answer = _read(node, FILES, [{"url": TOKYO, "line": 9}])
    assert "元の行が見つかりませんでした" in answer["rows"][0]["error"]
