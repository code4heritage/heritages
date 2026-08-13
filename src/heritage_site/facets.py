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

# 所在都道府県だけは件数順にしない (Issue #7)。**都道府県の表は持たない** —
# コードはデータの側にあり、データリポジトリが `data/13_tokyo.jsonl` のように
# 地域ごとにファイルを分けている (`Row.path`)。ここが持つのは軸のキーだけで、
# 47 の呼び名も並びも行から決まる (ADR 0014 / ADR 0015)。
AREA_KEY = "prefecture"

# 並びの根拠。画面はこれを見て畳み方を決める (地域は途中で切らない)。
ORDER_COUNT = "count"
ORDER_PERIOD = "period"
ORDER_AREA = "area"

_LEADING_YEAR = re.compile(r"\d+")

# データリポジトリのファイル名の頭にある地域コード (`data/13_tokyo.jsonl`)。
_AREA_CODE = re.compile(r"(\d+)_")


@dataclass(frozen=True)
class Axis:
    """絞り込みの軸 1 つ。`values` の並びがそのまま画面の並びになる。"""

    key: str
    label: str
    values: tuple[str, ...]
    order: str = ORDER_COUNT


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
    codes = _area_codes(rows, keys)
    return [
        Axis(
            key=key,
            label=_label(datasets, key),
            values=_order(key, counts[position], medians, codes if key == AREA_KEY else {}),
            order=_order_kind(key, codes),
        )
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


def _order_kind(key: str, codes: dict[str, str]) -> str:
    if key == AREA_KEY and codes:
        return ORDER_AREA
    return ORDER_PERIOD if key == PERIOD_KEY else ORDER_COUNT


def _area_codes(rows: list[Row], keys: list[str]) -> dict[str, str]:
    """所在都道府県の値ごとの地域コード。ファイル名から読む。

    **1 つの値が 2 つのファイルに跨っていたら何も返さない。**この並びは
    「データリポジトリが地域ごとにファイルを分ける」という別の約束に乗っている
    ので、約束が変わったら黙ってコード順のつもりの壊れた並びを出すより、
    件数順へ戻す方がよい (Issue #7)。
    """
    if AREA_KEY not in keys:
        return {}
    position = keys.index(AREA_KEY)
    seen: defaultdict[str, set[str]] = defaultdict(set)
    for row in rows:
        found = _AREA_CODE.match(row.path.rsplit("/", maxsplit=1)[-1])
        for value in row.facets[position]:
            seen[value].add(found.group(1) if found else "")
    codes = {value: next(iter(found)) for value, found in seen.items() if len(found) == 1}
    if len(codes) != len(seen) or "" in codes.values():
        return {}
    # 1 つのファイルに 2 つの値が入っていれば、コードは値の並びを決められない。
    if len(set(codes.values())) != len(codes):
        return {}
    return codes


def _order(
    key: str, counts: Counter[str], medians: dict[str, float], codes: dict[str, str]
) -> tuple[str, ...]:
    """値の並び。既定は件数の多い順、地域はコード順、時代は西暦の中央値順。

    **地域を件数順に並べない** (Issue #7)。件数順だと探したい県の位置が予測できず、
    しかも件数は更新のたびに動くので、同じ県が先月と違う場所に来る。コードは
    総務省の都道府県コードで、データリポジトリのファイル名がそれを持っている。

    中央値が採れるのは西暦を持つ分類だけ (建造物系の 22 値)。史跡・記念物系の
    「中世」「古代」は西暦を持たないので、年代順の並びの**後ろ**へ件数順で回す。
    混ぜて並べる手はない — 年代の分からない値に位置を与えれば、それは推測になる。
    """
    if codes:
        # 桁数を先に見る。コードは 2 桁で揃っているが、揃わなくなっても
        # `10` が `2` の前に来る並びにはしない。
        return tuple(sorted(counts, key=lambda value: (len(codes[value]), codes[value])))
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
