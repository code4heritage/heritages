"""地図の要約文 (site/summary.js)。

地図そのものは人が見るしかないが、**何を言うかは機械で確かめられる**。
地図に出せる行が 0 件のときに何と言うかは、場所に結び付かない種別が加わって
初めて要るようになった判断なので (Issue #23)、文言ごと固定する。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

SUMMARY_JS = Path(__file__).resolve().parents[1] / "site/summary.js"

_HARNESS = """
import {{ summaryText }} from {module};
let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;
const asked = JSON.parse(input);
process.stdout.write(
  JSON.stringify(asked.map(({{ mappable, matched, options }}) =>
    summaryText(mappable, matched, options ?? {{}})))
);
"""


def _ask(node: str, cases: list[dict[str, Any]]) -> list[str]:
    script = _HARNESS.format(module=json.dumps(SUMMARY_JS.as_posix()))
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script],
        input=json.dumps(cases),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return list(json.loads(completed.stdout))


def test_it_counts_what_reached_the_map(node: str) -> None:
    """**位置を持たない行を黙って落とさない** (Issue #32 §3)。数で一覧へ繋ぐ。"""
    [both, all_mapped] = _ask(
        node,
        [{"mappable": 3, "matched": 5}, {"mappable": 5, "matched": 5}],
    )
    assert both == "3 件を地図に表示 / 2 件は位置がないので一覧のみ"
    assert all_mapped == "5 件を地図に表示"


def test_an_empty_map_says_why(node: str) -> None:
    """地図を畳んだ回に、読み手が次にどこを見ればよいか分かるようにする。

    **理由は 2 つあり、意味が違う。**種別そのものが場所に結び付かない (無形文化財・
    選定保存技術) のと、所在地が公開されていない (美術工芸品) のは別のことなので、
    「位置がない」で一括りにしない。
    """
    [placeless, undisclosed] = _ask(
        node,
        [
            {"mappable": 0, "matched": 100, "options": {"placeless": True}},
            {"mappable": 0, "matched": 100},
        ],
    )
    assert placeless == "100 件はいずれも場所に結び付かない種別です。一覧で見られます"
    assert undisclosed == "100 件はいずれも所在地が公開されていません。一覧で見られます"


def test_nothing_matched_says_nothing(node: str) -> None:
    """1 件も当たらなかった回は一覧の側が「ありません」と言う。

    どちらも `aria-live` なので、両方が数を読み上げると同じことを 2 度聞かされる。
    """
    assert _ask(node, [{"mappable": 0, "matched": 0}]) == [""]
