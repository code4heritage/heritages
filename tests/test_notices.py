"""出典・地図・非公式・ライセンスの表記が消えていないことの機械検査。

4 つは目的の違う表示で、混ぜると役目を果たさない (ADR 0007 / ADR 0016)。
人手のレビューでは、無関係なリファクタで静かに消えたときに気付けない。
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest

SITE_DIR = Path(__file__).resolve().parents[1] / "site"
INDEX_HTML = SITE_DIR / "index.html"

REQUIRED_NOTICES = ("source", "map", "unofficial", "license")

# 地理院タイルの利用は、出典の明示と一覧ページへのリンクが条件 (ADR 0016)。
GSI_TILE_LIST_URL = "https://maps.gsi.go.jp/development/ichiran.html"


class _NoticeExtractor(HTMLParser):
    """`data-notice` を持つ要素の中身を取り出す。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.notices: dict[str, str] = {}
        self._current: str | None = None
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        notice = dict(attrs).get("data-notice")
        if self._current is None and notice:
            self._current = notice
            self._depth = 0
            self.notices.setdefault(notice, "")
        elif self._current is not None:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return
        if self._depth == 0:
            self._current = None
        else:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self.notices[self._current] += data


class _AncestorTracker(HTMLParser):
    """`data-notice` を持つ要素が、どの要素の中にあるかを覚える。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ancestors: dict[str, tuple[str, ...]] = {}
        self._stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        notice = dict(attrs).get("data-notice")
        if notice:
            self.ancestors[notice] = tuple(self._stack)
        self._stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """`<meta />` のように閉じる要素は入れ子を作らない。"""

    def handle_endtag(self, tag: str) -> None:
        if tag in self._stack:
            del self._stack[self._stack.index(tag) :]


def _ancestors() -> dict[str, tuple[str, ...]]:
    parser = _AncestorTracker()
    parser.feed(INDEX_HTML.read_text(encoding="utf-8"))
    return parser.ancestors


def _notices() -> dict[str, str]:
    parser = _NoticeExtractor()
    parser.feed(INDEX_HTML.read_text(encoding="utf-8"))
    return {key: " ".join(value.split()) for key, value in parser.notices.items()}


def _site_sources() -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8")
        for path in sorted(SITE_DIR.rglob("*"))
        if path.suffix in {".html", ".js", ".css"}
    }


@pytest.mark.parametrize("notice", REQUIRED_NOTICES)
def test_the_notice_is_present(notice: str) -> None:
    assert notice in _notices()


def test_the_map_notice_credits_the_tiles() -> None:
    """地理院タイルは、出典の明示と一覧ページへのリンクが利用の条件 (ADR 0016)。"""
    text = _notices()["map"]
    assert "地理院タイル" in text
    assert "国土地理院" in text
    assert GSI_TILE_LIST_URL in INDEX_HTML.read_text(encoding="utf-8")


@pytest.mark.parametrize("notice", REQUIRED_NOTICES)
def test_the_notice_is_not_folded_away(notice: str) -> None:
    """折りたたみの内側に入れない。

    地図の出典は「測量成果が画面に表示されている間は常に見える」ことを求められる
    (ADR 0016)。他の 3 つも、畳めば無いのと変わらない。
    """
    assert "details" not in _ancestors()[notice]


def test_the_map_credit_does_not_depend_on_the_library() -> None:
    """出典を地図ライブラリが作る表示に預けない。

    預けると、同梱の版を上げたときや初期化に失敗したときに静かに消える。
    ここの検査 (HTML を読むだけ) からも見えなくなる。
    """
    script = (SITE_DIR / "map.js").read_text(encoding="utf-8")
    assert "attributionControl: false" in script


def test_the_unofficial_notice_denies_being_official() -> None:
    """「国が作成したかのような態様」の回避 (ADR 0007)。"""
    text = _notices()["unofficial"]
    assert "非公式" in text
    assert "文化庁" in text


def test_the_license_notice_separates_code_from_data() -> None:
    text = _notices()["license"]
    assert "MIT" in text
    assert "利用規約" in text


def test_the_site_never_claims_a_creative_commons_license() -> None:
    """データは文化庁の利用規約に従う。CC BY だとは言わない (ADR 0007)。"""
    offenders = [
        path.name
        for path, text in _site_sources().items()
        if "CC BY" in text or "クリエイティブ・コモンズ" in text
    ]
    assert not offenders


def test_the_attribution_text_is_not_hardcoded() -> None:
    """出典表記は meta.json が持つ文言をそのまま出す。

    写し取ると、利用日が変わっても文言だけ古いまま残る (ADR 0014)。
    """
    offenders = [
        path.name
        for path, text in _site_sources().items()
        if "出典：「国指定文化財等データベース」" in text
    ]
    assert not offenders


def test_the_attribution_is_rendered_from_the_metadata() -> None:
    script = (SITE_DIR / "app.js").read_text(encoding="utf-8")
    assert "attribution" in script
    assert 'getElementById("attribution")' in script
