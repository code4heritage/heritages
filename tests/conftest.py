"""テスト用のデータリポジトリを組み立てる道具と、画面の表記を読む道具。

`meta.json` の件数は既定で行から数えて埋める。件数の不一致を試すテストは
`counts` を明示して壊す — 「正しい状態を作るのが面倒だから検査が緩い」を避ける。
"""

from __future__ import annotations

import json
import os
import shutil
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

DEFAULT_ACCESSED_DATE = "2026-08-12"

INDEX_HTML = Path(__file__).resolve().parents[1] / "site" / "index.html"


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


def notice_texts() -> dict[str, str]:
    """画面の表記を `data-notice` ごとに引けるようにする (空白は潰す)。

    表記が在るかどうかは `tests/test_notices.py`、中身は表記ごとの検査が見る。
    """
    parser = _NoticeExtractor()
    parser.feed(INDEX_HTML.read_text(encoding="utf-8"))
    return {key: " ".join(value.split()) for key, value in parser.notices.items()}


def record(
    ledger_id: str,
    managed_id: str,
    *,
    name: str = "名称",
    url: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """1 行ぶん。キーが無い = 値なしなので、指定しない項目はキーごと落とす。"""
    row: dict[str, Any] = {
        "ledger_id": ledger_id,
        "managed_id": managed_id,
        "name": name,
        "url": url or f"https://kunishitei.bunka.go.jp/heritage/detail/{ledger_id}/{managed_id}",
    }
    if latitude is not None:
        row["latitude"] = latitude
    if longitude is not None:
        row["longitude"] = longitude
    row.update(extra)
    return row


def make_dataset(
    data_dir: Path,
    repo: str,
    files: dict[str, list[dict[str, Any]]],
    *,
    name: str | None = None,
    schema_version: int = 1,
    accessed_date: str = DEFAULT_ACCESSED_DATE,
    counts: dict[str, Any] | None = None,
    declared_files: list[dict[str, Any]] | None = None,
    facets: dict[str, dict[str, int]] | None = None,
    labels: dict[str, str] | None = None,
    write_meta: bool = True,
) -> Path:
    root = data_dir / repo
    (root / "data").mkdir(parents=True, exist_ok=True)
    rows = [row for rows in files.values() for row in rows]
    for filename, contents in files.items():
        lines = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in contents)
        (root / "data" / filename).write_text(lines, encoding="utf-8")

    if not write_meta:
        return root

    meta = {
        "schema_version": schema_version,
        "dataset": {
            "repo": repo,
            "name": name or repo,
            "category": {"code": "999", "name": "分類"},
        },
        "source": {
            "name": "国指定文化財等データベース",
            "publisher": "文化庁",
            "accessed_date": accessed_date,
            "attribution": "出典：「国指定文化財等データベース」（文化庁）を加工して作成",
        },
        "counts": counts
        or {
            "records": len(rows),
            "files": len(files),
            "with_coordinates": sum(
                1 for row in rows if "latitude" in row and "longitude" in row
            ),
        },
        "labels": {"name": "名称", **(labels or {})},
        # 絞り込みの軸はここから作る (ADR 0014)。既定は空 — 軸を試すテストだけが渡す。
        "facets": facets or {},
        "files": declared_files
        if declared_files is not None
        else [
            {"path": f"data/{filename}", "records": len(contents)}
            for filename, contents in sorted(files.items())
        ],
    }
    (root / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return root


@pytest.fixture(scope="session")
def node() -> str:
    """画面側 (JS) を確かめるための node。

    **CI では飛ばさずに落とす。**黙って skip すると、「ビルドと画面で正規化が
    一致する」「絞り込みの規則がこうなっている」という保証が CI から消える。
    手元に node が無いぶんには先へ進めてよい。
    """
    found = shutil.which("node")
    if found:
        return found
    if os.environ.get("CI"):
        pytest.fail("node が見つからない (CI では JS 側の検証を飛ばさない)")
    pytest.skip("node が無いので JS 側を確かめられない")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """検査を素通りする 2 データセット。壊す試験はここから 1 箇所だけ変える。"""
    directory = tmp_path / "data-repos"
    directory.mkdir()
    make_dataset(
        directory,
        "national-treasures",
        {
            "13_tokyo.jsonl": [
                record("102", "00004367", name="旧東宮御所", latitude=35.68, longitude=139.72),
            ],
            "26_kyoto.jsonl": [
                record("102", "00001234", name="金堂", latitude=35.01, longitude=135.76),
                record("102", "00001235", name="塔"),
            ],
        },
        name="国宝（建造物）",
    )
    make_dataset(
        directory,
        "special-historic-sites",
        {
            "13_tokyo.jsonl": [
                # 複合指定: 下の名勝と同じ棟。原本 URL も同じでなければならない。
                record("401", "00009999", name="旧浜離宮庭園", latitude=35.65, longitude=139.76),
            ],
        },
        name="特別史跡",
    )
    make_dataset(
        directory,
        "special-places-of-scenic-beauty",
        {
            "13_tokyo.jsonl": [
                record("401", "00009999", name="旧浜離宮庭園", latitude=35.65, longitude=139.76),
            ],
        },
        name="特別名勝",
    )
    return directory
