"""検索文字列の正規化 (Issue #32 §2)。

検索は**ビルド時に正規化した 1 本の文字列への部分一致**で行う。索引を作るのが
ここ (Python) で、入力された語を同じ手順で正規化するのが画面側 (`site/normalize.js`)。
**両者がずれると、打った語が当たらない**という形で静かに壊れるので、同じ事例表で
突き合わせて固定する (`tests/test_search.py` / `tests/normalization.json`)。

手順は 4 つ。

1. NFKC — 全角の英数字・半角カナを畳む (`ＪＲ小樽駅` → `JR小樽駅`)
2. 小文字化 — 名称にラテン文字が 64 件ある (`MAEHARA 20th`)。`jr` で引けるように
3. カタカナ → ひらがな — ふりがなは片方の表記しか持たない
4. 空白と `・` を落とす — 原文の区切りは表記の揺れでしかない

**空白を落とす手順の中に改行も入る。**索引は項目ごとに正規化してから改行で
繋ぐので、正規化を通った語には改行が残らない。**項目をまたいだ誤った一致が
起きない**のはこのため。
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Any

# 検索の対象にする項目 (Issue #32 §2)。解説文は入れない — 部分一致の網に
# かかりすぎて、名前で引きたい人の邪魔になる。
SEARCH_FIELDS = ("name", "ridge_name", "name_kana", "ridge_name_kana", "address")

# 項目の区切り。正規化が落とす文字なので、**語がここをまたいで当たることはない**。
FIELD_SEPARATOR = "\n"

# ひらがなと 1:1 に対応するカタカナの範囲 (ァ〜ヶ)。ヷ〜ヺ に対応する
# ひらがなは無いので、この範囲から外す。
_KATAKANA_FIRST = 0x30A1
_KATAKANA_LAST = 0x30F6
_HIRAGANA_OFFSET = 0x60

# 落とす文字。**空白は集合で書き下す** — Python の `str.isspace` と JS の `\s` は
# 対象がわずかに違い、どちらかに寄せると両側の正規化がずれる。
_DROPPED = frozenset(" \t\n\r\v\f\u00a0\u3000・")


def normalize(text: str) -> str:
    """検索に使う形に均す。`site/normalize.js` の `normalize` と同じ結果になること。"""
    folded = unicodedata.normalize("NFKC", text).lower()
    characters: list[str] = []
    for character in folded:
        code = ord(character)
        if _KATAKANA_FIRST <= code <= _KATAKANA_LAST:
            characters.append(chr(code - _HIRAGANA_OFFSET))
        elif character not in _DROPPED:
            characters.append(character)
    return "".join(characters)


def search_text(record: Mapping[str, Any]) -> str:
    """1 行ぶんの検索文字列。

    **キーが無い = 値なし** (`null` は来ない) なので、無い項目は繋がない。
    正規化して空になった項目も落とす — 区切りだけが残っても当たらない。
    """
    parts = [
        normalized
        for key in SEARCH_FIELDS
        if isinstance(value := record.get(key), str) and (normalized := normalize(value))
    ]
    return FIELD_SEPARATOR.join(parts)
