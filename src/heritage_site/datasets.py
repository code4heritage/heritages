"""データリポジトリの発見と読み出し。

データセットは `meta.json` の有無で見つける (ADR 0014・0015)。リポジトリ名を
並べた表をサイト側に持たないので、**種別が増えても・減ってもこのコードは変わらない**。
データの無い器を削除しても (ADR 0013)、`meta.json` が無ければ黙って対象外になる。
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .search import search_text

META_FILENAME = "meta.json"
DATA_DIRNAME = "data"
DATA_SUFFIX = ".jsonl"

# サイトが読める `meta.json` / JSON Lines のスキーマ版。データ側が先に進んだら
# 黙って壊れるのではなく、ビルドを失敗させて気付く (Issue #32 の不変条件)。
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})


class DataError(Exception):
    """データの読み出しそのものが成立しないときに送出する。

    「値が想定と違う」は検査 (`checks.py`) の担当で、こちらは JSON として
    読めない・宣言されたファイルが無いといった、続行できない事態に限る。
    """


@dataclass(frozen=True)
class Dataset:
    """データリポジトリ 1 つ。"""

    repo: str
    root: Path
    meta: dict[str, Any]

    @property
    def name(self) -> str:
        dataset = self.meta.get("dataset", {})
        name = dataset.get("name")
        return name if isinstance(name, str) else self.repo

    @property
    def schema_version(self) -> Any:
        return self.meta.get("schema_version")

    @property
    def accessed_date(self) -> Any:
        return self.meta.get("source", {}).get("accessed_date")

    @property
    def counts(self) -> dict[str, Any]:
        counts = self.meta.get("counts", {})
        return counts if isinstance(counts, dict) else {}

    @property
    def declared_files(self) -> list[dict[str, Any]]:
        files = self.meta.get("files", [])
        return [entry for entry in files if isinstance(entry, dict)]


@dataclass(frozen=True)
class Row:
    """JSON Lines の 1 行のうち、索引と検査に要るぶんだけ。

    データそのものは変換せずに配るので (ADR 0015)、ここで全項目を持つ必要はない。
    解説文のような重い項目を持たないのは、2 万を超える行を一度に抱えるため。
    """

    dataset_index: int
    path: str
    line: int
    ledger_id: str
    managed_id: str
    name: str
    url: str
    latitude: float | None
    longitude: float | None
    ridge_name: str
    address: str
    designated_year: str
    western_year: str
    search: str
    # 軸ごとの値。**並びは `iter_rows` に渡した `facet_keys` と同じ** (軸の名前を
    # 行ごとに繰り返さないため)。値を持たない軸は空の組になる。
    facets: tuple[tuple[str, ...], ...] = ()

    @property
    def key(self) -> tuple[str, str]:
        """指定を一意に決める組。行数ではなくこれで数える (棟に展開される分類がある)。"""
        return (self.ledger_id, self.managed_id)

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None


def discover(data_dir: Path) -> list[Dataset]:
    """`data_dir` 直下から `meta.json` を持つディレクトリを集める。

    並びはリポジトリ名の昇順。索引の中身を実行のたびに揺らさないための固定で、
    生成物が決定的であることの一部でもある。
    """
    if not data_dir.is_dir():
        raise DataError(f"データの置き場が無い: {data_dir}")

    datasets: list[Dataset] = []
    for entry in sorted(data_dir.iterdir(), key=lambda path: path.name):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        meta_path = entry / META_FILENAME
        if not meta_path.is_file():
            continue
        datasets.append(Dataset(repo=entry.name, root=entry, meta=_read_meta(meta_path)))
    if not datasets:
        raise DataError(f"{META_FILENAME} を持つデータセットが 1 つも無い: {data_dir}")
    return datasets


def data_files(dataset: Dataset) -> list[Path]:
    """実際に置かれている JSON Lines。`meta.json` の宣言とは突き合わせて検査する。"""
    directory = dataset.root / DATA_DIRNAME
    if not directory.is_dir():
        return []
    return sorted(directory.glob(f"*{DATA_SUFFIX}"), key=lambda path: path.name)


def iter_rows(
    dataset: Dataset, dataset_index: int, *, facet_keys: Sequence[str] = ()
) -> Iterator[Row]:
    """データセットの全行を、ファイル名順・行順に読む。

    `facet_keys` に渡した軸の値だけを行から拾う。**どの軸があるかは
    `meta.json` が決める**ので (`facets.axis_keys`)、ここでは名前を知らない。
    """
    for path in data_files(dataset):
        relative = f"{DATA_DIRNAME}/{path.name}"
        with path.open(encoding="utf-8") as stream:
            for line_number, raw in enumerate(stream, start=1):
                if not raw.strip():
                    continue
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError as error:
                    raise DataError(
                        f"JSON として読めない: {dataset.repo}/{relative}:{line_number} ({error})"
                    ) from error
                yield _row(record, dataset_index, relative, line_number, facet_keys)


def location(datasets: list[Dataset], row: Row) -> str:
    """報告に出す位置。「どのリポジトリの何行目か」まで書く。"""
    return f"{datasets[row.dataset_index].repo}/{row.path}:{row.line}"


def _read_meta(path: Path) -> dict[str, Any]:
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise DataError(f"{path} を JSON として読めない: {error}") from error
    if not isinstance(meta, dict):
        raise DataError(f"{path} の中身がオブジェクトでない")
    return meta


def _row(
    record: Any,
    dataset_index: int,
    relative: str,
    line_number: int,
    facet_keys: Sequence[str],
) -> Row:
    if not isinstance(record, dict):
        raise DataError(f"行がオブジェクトでない: {relative}:{line_number}")
    latitude = _coordinate(record.get("latitude"))
    longitude = _coordinate(record.get("longitude"))
    # 片方だけの座標は地図に置けない。両方揃っていなければ「座標なし」として扱う。
    if latitude is None or longitude is None:
        latitude = longitude = None
    return Row(
        dataset_index=dataset_index,
        path=relative,
        line=line_number,
        ledger_id=_text(record.get("ledger_id")),
        managed_id=_text(record.get("managed_id")),
        name=_text(record.get("name")),
        url=_text(record.get("url")),
        latitude=latitude,
        longitude=longitude,
        ridge_name=_text(record.get("ridge_name")),
        address=_text(record.get("address")),
        # 日付は 4 / 7 / 10 文字の可変長 (原文にそこまでしか無いことがある)。
        # 先頭 4 文字がどの長さでも年になる。
        designated_year=_text(record.get("designated_date"))[:4],
        western_year=_text(record.get("western_year")),
        search=search_text(record),
        facets=tuple(values_of(record, key) for key in facet_keys),
    )


def values_of(record: Any, key: str) -> tuple[str, ...]:
    """絞り込みの軸 1 つぶんの値。**単一の値も配列も来る**。

    401 の種別は 2 つ持ちうる (特別名勝 + 特別史跡の複合指定)。空文字は値として
    数えない — 選べない項目が語彙に混じる。
    """
    value = record.get(key) if isinstance(record, dict) else None
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str) and item)
    return ()


def _text(value: Any) -> str:
    """キーが無い = 値なし (`null` は来ない)。無い項目は空文字で持つ。"""
    return value if isinstance(value, str) else ""


def _coordinate(value: Any) -> float | None:
    # bool は int の派生なので、数値として通さないよう先に弾く。
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)
