"""報告先の機械検査 (Issue #6)。

誤りに気付いた人の伝え先は、画面のフッタと Issue テンプレートの 2 か所にある。
どちらも無くても画面は動くので、消えても気付けない。アドレスを 2 か所に書いて
いるぶん、片方だけ変わる形の壊れ方もする。

表記が在ることと畳まれていないことは `tests/test_notices.py` (`REQUIRED_NOTICES`)。
ここで見るのは中身。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from conftest import notice_texts

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "site" / "index.html"
TEMPLATE_DIR = ROOT / ".github" / "ISSUE_TEMPLATE"

# アカウントを持たない人のための窓口。難読化しない — 届かなければ窓口の意味が無い。
SUPPORT_EMAIL = "c4h-support@googlegroups.com"
ISSUE_FORM_URL = "https://github.com/code4heritage/heritages/issues/new/choose"

EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")


def _feedback() -> str:
    return notice_texts()["feedback"]


def _index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def test_the_footer_points_at_the_issue_tracker() -> None:
    """テンプレートの選択画面へ送る。種類を選ばせたいので新規作成の直リンクにしない。"""
    assert ISSUE_FORM_URL in _index()


def test_the_footer_offers_a_way_in_without_a_github_account() -> None:
    text = _feedback()
    assert SUPPORT_EMAIL in text
    assert f"mailto:{SUPPORT_EMAIL}" in _index()


def test_the_footer_asks_for_the_url_of_the_original_page() -> None:
    """どの指定の話かは原本ページの URL でしか確かめられない (同名の指定がある)。"""
    text = _feedback()
    assert "原本" in text
    assert "URL" in text


def test_the_footer_separates_what_the_site_can_fix() -> None:
    """直せるもの (このサイトの表示) と上流に由来するものを書き分ける。

    サイトは出典元の文字情報をそのまま出していて、内容を直す立場にない。
    区別を書かないと、直せない報告に「直します」と答えることになる。
    """
    text = _feedback()
    assert "不具合" in text
    assert "国指定文化財等データベース" in text


@pytest.mark.parametrize("template", ("data-error.md", "site-bug.md"))
def test_the_issue_template_exists(template: str) -> None:
    """データの誤りとサイトの不具合は、書いてほしいことが違うので分けて置く。"""
    assert (TEMPLATE_DIR / template).is_file()


def test_the_data_error_template_asks_for_the_original_page() -> None:
    text = (TEMPLATE_DIR / "data-error.md").read_text(encoding="utf-8")
    assert "原本ページの URL" in text


def test_the_template_chooser_offers_the_email() -> None:
    """アカウントの無い人は Issue を立てられない。選択画面から窓口へ出す。"""
    text = (TEMPLATE_DIR / "config.yml").read_text(encoding="utf-8")
    assert "contact_links" in text
    assert f"mailto:{SUPPORT_EMAIL}" in text


def test_the_address_does_not_drift_between_the_two_places() -> None:
    """片方だけ書き換わると、届かない窓口が画面に残る。"""
    found = {
        address
        for path in (INDEX_HTML, TEMPLATE_DIR / "config.yml")
        for address in EMAIL.findall(path.read_text(encoding="utf-8"))
    }
    assert found == {SUPPORT_EMAIL}
