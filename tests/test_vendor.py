"""同梱した地図ライブラリ (site/vendor/) の検査。

ADR 0016 で決めたのは 2 つ。**CDN から読まない**ことと、**同梱するものは版で
固定される**こと。どちらも破れても画面は出るので、機械で押さえる。

- 同梱物に手を入れると上流の版と照合できなくなり、「何を配っているのか」が
  言えなくなる → 取得元と sha256 を README に書き、実ファイルと突き合わせる
- 外部オリジンから読み込む行が 1 つ紛れれば、閲覧者の接続先が増える →
  自分たちが書いた側 (vendor の外) に外部の読み込みが無いことを見る
"""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

SITE_DIR = Path(__file__).resolve().parents[1] / "site"
VENDOR_DIR = SITE_DIR / "vendor"
LEAFLET_DIR = VENDOR_DIR / "leaflet"
LEAFLET_README = LEAFLET_DIR / "README.md"

# | `ファイル名` | 取得元 | `sha256` |
_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(\S+)\s*\|\s*`([0-9a-f]{64})`\s*\|$", re.MULTILINE)

# JS と CSS から外部を読む書き方。タイルの URL は JS の中のただの文字列なので
# 当たらない (取得しているのは実行時の地図で、読み込みの宣言ではない)。
_EXTERNAL_LOAD = re.compile(r"""(?:from|import)\s*\(?\s*["']https?://|url\(\s*["']?https?://""")

# HTML で外から取ってくる要素。`<a href>` は行き先であって読み込みではないので
# 含めない (地図の出典が求めるリンクがここに当たってしまう)。
_LOADING_TAGS = {
    "link": "href",
    "script": "src",
    "img": "src",
    "iframe": "src",
    "source": "src",
    "embed": "src",
    "object": "data",
}


class _LoadCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.loaded: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attribute = _LOADING_TAGS.get(tag)
        if attribute is None:
            return
        value = dict(attrs).get(attribute)
        if value:
            self.loaded.append(value)


def _loads_from_outside(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        collector = _LoadCollector()
        collector.feed(text)
        return any(url.startswith(("http://", "https://", "//")) for url in collector.loaded)
    return _EXTERNAL_LOAD.search(text) is not None


def _declared() -> list[tuple[str, str, str]]:
    return _ROW.findall(LEAFLET_README.read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_readme_declares_every_vendored_file() -> None:
    """表に無いものを黙って足さない (足したものは検査を通らない)。"""
    declared = {name for name, _, _ in _declared()}
    present = {path.name for path in LEAFLET_DIR.iterdir() if path.name != "README.md"}
    assert declared == present


@pytest.mark.parametrize("row", _declared(), ids=lambda row: row[0])
def test_the_vendored_file_is_unmodified(row: tuple[str, str, str]) -> None:
    """1 バイトでも変えたら落ちる。差し替えるならファイルごと入れ替えて表を直す。"""
    name, source, digest = row
    assert source.startswith("https://"), "取得元は控えておく (再取得して照合できるように)"
    assert _digest(LEAFLET_DIR / name) == digest


def test_the_license_travels_with_the_code() -> None:
    text = (LEAFLET_DIR / "LICENSE").read_text(encoding="utf-8")
    assert "BSD 2-Clause" in text


def test_the_vendored_version_matches_the_readme() -> None:
    """README の見出しの版と、同梱した中身が名乗る版を突き合わせる。"""
    heading = LEAFLET_README.read_text(encoding="utf-8").splitlines()[0]
    [version] = re.findall(r"\d+\.\d+\.\d+", heading)
    source = (LEAFLET_DIR / "leaflet-src.esm.js").read_text(encoding="utf-8")
    assert f'var version = "{version}"' in source


def test_nothing_is_loaded_from_another_origin() -> None:
    """閲覧者のブラウザが外へ出るのはタイルの取得だけ (ADR 0016)。"""
    offenders = [
        path.relative_to(SITE_DIR).as_posix()
        for path in sorted(SITE_DIR.rglob("*"))
        if path.suffix in {".html", ".js", ".css"}
        if VENDOR_DIR not in path.parents
        if _loads_from_outside(path)
    ]
    assert not offenders
