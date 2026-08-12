"""ファセットの軸 (Issue #32 §2)。

**軸の表をサイトに持たない。**どの軸があるかは `meta.json` の `facets` が
持っているので、そこから作る (ADR 0014 / ADR 0015)。種別が増えて新しい軸が
現れても、減って軸が消えても、ここは変わらない。

語彙と並びは**行から**決める。`meta.json` の `facets` にも値と件数はあるが、
そちらは分類ごとに分かれていて、種別横断の 1 本の軸にするには結局まとめ直す
ことになる。行から作れば、索引が指す値が語彙に無いという食い違いも起きない。
"""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from .datasets import Dataset, Row

# 時代の並びだけは件数順にしない。**年代表をハードコードせず**に年代順へ
# 並べるため、値ごとの西暦の中央値を使う (Issue #32 §2)。
PERIOD_KEY = "period"

_LEADING_YEAR = re.compile(r"\d+")


@dataclass(frozen=True)
class Axis:
    """絞り込みの軸 1 つ。`values` の並びがそのまま画面の並びになる。"""

    key: str
    label: str
    values: tuple[str, ...]


def axis_keys(datasets: list[Dataset]) -> list[str]:
    """どの軸を出すか。行を読む前に決まる (索引の並びがこれに揃うため)。

    **語彙が空の軸は出さない** — 重要伝統的建造物群保存地区は `period` が
    全行空で、`meta.json` にもその軸ごと現れない。空の軸を出すと、選べない
    見出しだけが画面に残る。

    並びは「宣言しているデータセットの数」の多い順。種別をまたいで効く軸ほど
    先に来る。同数なら件数の多い順、それも同じならキー順で固定する。
    """
    datasets_declaring: Counter[str] = Counter()
    declared_records: Counter[str] = Counter()
    for dataset in datasets:
        facets = dataset.meta.get("facets", {})
        if not isinstance(facets, dict):
            continue
        for key, vocabulary in facets.items():
            if not isinstance(vocabulary, dict) or not vocabulary:
                continue
            datasets_declaring[key] += 1
            declared_records[key] += sum(
                count for count in vocabulary.values() if isinstance(count, int)
            )
    return sorted(
        datasets_declaring,
        key=lambda key: (-datasets_declaring[key], -declared_records[key], key),
    )


def build_axes(datasets: list[Dataset], rows: list[Row], keys: list[str]) -> list[Axis]:
    """軸ごとの語彙と並びを行から作る。`keys` は `axis_keys` の戻り値と同じ順。"""
    counts: list[Counter[str]] = [Counter() for _ in keys]
    for row in rows:
        for position, values in enumerate(row.facets):
            counts[position].update(values)
    medians = _period_medians(rows, keys)
    return [
        Axis(key=key, label=_label(datasets, key), values=_order(key, counts[position], medians))
        for position, key in enumerate(keys)
        if counts[position]
    ]


def _label(datasets: list[Dataset], key: str) -> str:
    """軸の見出し。**分類ごとに呼び名が違う** (指定基準 / 重文指定基準)。

    宣言しているデータセットが多い方を採る。同数ならラベル順で固定する
    (生成物を実行ごとに揺らさない)。どのデータセットもラベルを持たなければ
    キーをそのまま出す — 呼び名を推測で書き起こすより、原文が無いと分かる方がよい。
    """
    labels: Counter[str] = Counter()
    for dataset in datasets:
        meta_labels = dataset.meta.get("labels", {})
        if isinstance(meta_labels, dict) and isinstance(label := meta_labels.get(key), str):
            labels[label] += 1
    if not labels:
        return key
    return min(labels, key=lambda label: (-labels[label], label))


def _order(key: str, counts: Counter[str], medians: dict[str, float]) -> tuple[str, ...]:
    """値の並び。既定は件数の多い順、時代だけ西暦の中央値順。

    中央値が採れるのは西暦を持つ分類だけ (建造物系の 22 値)。史跡・記念物系の
    「中世」「古代」は西暦を持たないので、年代順の並びの**後ろ**へ件数順で回す。
    混ぜて並べる手はない — 年代の分からない値に位置を与えれば、それは推測になる。
    """
    if key != PERIOD_KEY:
        return tuple(sorted(counts, key=lambda value: (-counts[value], value)))
    return tuple(
        sorted(
            counts,
            key=lambda value: (
                (0, medians[value], value) if value in medians else (1, -counts[value], value)
            ),
        )
    )


def _period_medians(rows: list[Row], keys: list[str]) -> dict[str, float]:
    """時代の値ごとの西暦の中央値。西暦を持つ行が 1 つも無い値は入らない。"""
    if PERIOD_KEY not in keys:
        return {}
    position = keys.index(PERIOD_KEY)
    years: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        if (year := _year(row.western_year)) is None:
            continue
        for value in row.facets[position]:
            years[value].append(year)
    return {value: statistics.median(found) for value, found in years.items()}


def _year(text: str) -> int | None:
    """原文の西暦から並べ替えに使う年を取る。

    **原文の 3 割は 1 つの数ではない** — `1868-1911` `1830～1868` `1905頃`
    `1926／1955改修` のように幅や但し書きを持つ。**先頭の数を採る**と、
    どの書式でもその値が指す最も古い年になり、並べ替えの材料として揃う。
    """
    found = _LEADING_YEAR.search(text)
    return int(found.group()) if found else None


def positions(axes: Iterable[Axis]) -> dict[str, dict[str, int]]:
    """語彙を索引の番号に置き換えるための表。値の名前を行ごとに繰り返さない。"""
    return {axis.key: {value: number for number, value in enumerate(axis.values)} for axis in axes}
