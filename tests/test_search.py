"""検索文字列の正規化。

**Python 側 (ビルド) と JS 側 (画面) が同じ結果を返すこと**をここで固定する。
索引を作るのと、打たれた語を均すのが別の言語なので、ずれても例外は出ない —
「打った語が当たらない」という形で静かに壊れる。事例表 (`normalization.json`) を
両方に食わせて突き合わせる。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from heritage_site.search import SEARCH_FIELDS, normalize, search_text

CASES_PATH = Path(__file__).with_name("normalization.json")
NORMALIZE_JS = Path(__file__).resolve().parents[1] / "site/normalize.js"

CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[case["why"] for case in CASES])
def test_the_python_normalizer_matches_the_table(case: dict[str, str]) -> None:
    assert normalize(case["input"]) == case["expected"]


def test_the_javascript_normalizer_matches_the_table(node: str) -> None:
    """画面側も同じ表を通す。"""
    script = f"""
    import {{ normalize }} from {json.dumps(NORMALIZE_JS.as_posix())};
    let input = "";
    process.stdin.setEncoding("utf8");
    for await (const chunk of process.stdin) input += chunk;
    const cases = JSON.parse(input);
    process.stdout.write(JSON.stringify(cases.map((c) => normalize(c.input))));
    """
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script],
        input=json.dumps(CASES),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == [case["expected"] for case in CASES]


def test_the_search_text_joins_only_the_fields_that_have_a_value() -> None:
    """**キーが無い = 値なし。**無い項目のぶんの区切りは残さない。"""
    record = {"name": "金堂", "address": "京都市", "quantity": "1棟"}
    assert search_text(record) == "金堂\n京都市"


def test_the_search_text_normalizes_every_field() -> None:
    record = {"name": "ＪＲ小樽駅", "name_kana": "ジェイアールオタルエキ"}
    assert search_text(record) == "jr小樽駅\nじぇいあーるおたるえき"


def test_a_query_cannot_match_across_two_fields() -> None:
    """項目の区切りは正規化が落とす文字なので、語がまたいで当たることはない。"""
    record = {"name": "金堂", "address": "京都市"}
    text = search_text(record)
    assert normalize("金堂京都市") not in text


def test_the_searched_fields_are_the_ones_the_issue_names() -> None:
    """解説文は入れない (部分一致の網にかかりすぎる)。"""
    assert SEARCH_FIELDS == ("name", "ridge_name", "name_kana", "ridge_name_kana", "address")
