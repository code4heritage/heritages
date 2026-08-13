"""入口の説明の機械検査 (Issue #5)。

見に来るのはデータを見たい人で、取得の仕組みを知りたい人ではない。画面に置くのは
「定期的に確認してまとめている」ことと、「利用日」が何の日付かまで。頻度の数字と
取得の方法は書かない — 正本はクローラー側にあり、写せば片方だけ古くなる。

どちらも本文の一文なので、無関係な書き換えで静かに消えても、運用の内部が紛れ込んでも
人手のレビューでは気付けない。
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parents[1] / "site"
INDEX_HTML = SITE_DIR / "index.html"

# 画面に出さない運用の内部 (Issue #5)。頻度と取得の方法にあたる語。
OPERATIONAL_WORDS = ("毎月", "月次", "クロール", "レート", "req/s", "差分更新")


class _TextExtractor(HTMLParser):
    """読み手に見えるテキストを取り出す。

    HTML コメントは `handle_comment` に回るのでここには入らない。理由をコメントで
    書き残すことは妨げず、**画面に出ること**だけを検査する。
    """

    SKIP = frozenset({"script", "style", "title"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.by_id: dict[str, str] = {}
        self.visible = ""
        self._ids: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skipping += 1
            return
        element_id = dict(attrs).get("id")
        if element_id:
            self._ids.append(element_id)
            self.by_id.setdefault(element_id, "")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skipping:
            self._skipping -= 1

    def handle_data(self, data: str) -> None:
        if self._skipping:
            return
        self.visible += data
        for element_id in self._ids:
            self.by_id[element_id] += data


def _document() -> _TextExtractor:
    parser = _TextExtractor()
    parser.feed(INDEX_HTML.read_text(encoding="utf-8"))
    return parser


def _text(element_id: str) -> str:
    return " ".join(_document().by_id.get(element_id, "").split())


def test_the_intro_says_the_data_is_checked_regularly() -> None:
    """更新していること自体は伝える。伝わらないと、止まったデータと区別が付かない。"""
    text = _text("intro")
    assert "国指定文化財等データベース" in text
    assert "定期的に" in text


def test_the_accessed_date_is_explained() -> None:
    """「利用日」は消せない表示 (ADR 0014 / ADR 0007)。出す以上は読めるようにする。"""
    text = _text("accessed-note")
    assert "利用日" in text
    assert "取り出した日" in text


def test_the_screen_does_not_spell_out_how_the_data_is_fetched() -> None:
    """頻度と取得の方法は画面に出さない。正本はクローラー側 (Issue #5)。"""
    visible = _document().visible
    assert [word for word in OPERATIONAL_WORDS if word in visible] == []
