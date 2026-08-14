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
ORDER_NUMBER = "number"

_LEADING_YEAR = re.compile(r"\d+")

# データリポジトリのファイル名の頭にある地域コード (`data/13_tokyo.jsonl`)。
_AREA_CODE = re.compile(r"(\d+)_")

# 値の頭に振られた番号 (`一．貝塚、集落跡…` / `（一）名木、巨樹…`)。**括弧は
# 開きだけ半角のことがある** (`(三）歴史的価値の高いもの`。102 の重文指定基準)。
# 区切りの記号まで含めて読むのは、`三重県庁舎` のような値を番号と見ないため。
_LEADING_NUMBER = re.compile(r"^[（(]?([一二三四五六七八九十]+)[）)．.]")

_KANJI_DIGITS = {character: number for number, character in enumerate("一二三四五六七八九", 1)}


@dataclass(frozen=True)
class Group:
    """軸の中の体系 1 つ (Issue #8)。`values` の先頭から数えた連続する区間を指す。

    値そのものを持たないのは、同じ文字列を索引に二度書かないため。並びは
    `Axis.values` が正本で、こちらは切れ目だけを持つ。
    """

    label: str
    size: int


@dataclass(frozen=True)
class Axis:
    """絞り込みの軸 1 つ。`values` の並びがそのまま画面の並びになる。"""

    key: str
    label: str
    values: tuple[str, ...]
    order: str = ORDER_COUNT
    # 体系ごとのまとまり (Issue #8)。**横断の軸では空**。値が体系ごとに
    # 張り付いている軸だけがこれを持ち、画面は見出しと畳み方をここから決める。
    groups: tuple[Group, ...] = ()


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
    composite = _composite_keys(rows)
    axes = []
    for position, key in enumerate(keys):
        if not counts[position]:
            continue
        area = codes if key == AREA_KEY else {}
        # 地域と時代は先に並びが決まっている。番号は残りの軸だけで探す。
        numbers = {} if area or key == PERIOD_KEY else _numbers(counts[position])
        values = _order(key, counts[position], medians, area, numbers)
        schemes = _schemes(datasets, rows, position, values, composite)
        axes.append(
            Axis(
                key=key,
                label=_label(datasets, key),
                values=tuple(value for _, members in schemes for value in members) or values,
                order=_order_kind(key, area, numbers),
                groups=tuple(Group(label, len(members)) for label, members in schemes),
            )
        )
    return axes


def _composite_keys(rows: list[Row]) -> set[tuple[str, str]]:
    """複数のデータセットに現れる指定 (401 の複合指定。ADR 0012)。

    体系を数えるときにこの行を外す。**同じ行が両方のリポジトリに書かれる**ので、
    数に入れると名勝の指定基準が史跡にも出ていることになり、どの値も体系を
    またいで見える (Issue #8 のコメントの実測)。
    """
    owners: defaultdict[tuple[str, str], set[int]] = defaultdict(set)
    for row in rows:
        owners[row.key].add(row.dataset_index)
    return {key for key, found in owners.items() if len(found) > 1}


def _schemes(
    datasets: list[Dataset],
    rows: list[Row],
    position: int,
    values: tuple[str, ...],
    composite: set[tuple[str, str]],
) -> list[tuple[str, tuple[str, ...]]]:
    """軸の値を体系ごとにまとめる。**横断の軸では何も返さない** (Issue #8)。

    指定基準も種別も、体系ごとに別の語彙が 1 本の軸に混ざっている — 登録有形の
    登録基準と天然記念物の指定基準が、番号の振り方すら違うまま並ぶ。**どの値が
    どの体系かは行から導ける**ので、体系の表をサイトに持たずに済む
    (ADR 0014 / ADR 0015)。種別が増えても判定は追随する。

    横断かどうかも行から測る。**値がその軸を持つデータセットの過半に現れるなら
    横断**で、まとめる意味がない — 所在都道府県は 47 値すべてが 8 データセットに
    出るので、体系の見出しを付けても「ほぼ全部」としか書けない。逆に指定基準は
    値あたり 2 データセットで、体系がそのまま境目になる。

    体系の名前は**その値がいちばん多く現れたデータセット**にする。出どころの
    データセットを並べた名前にはしない — 特別史跡にも出る史跡の基準と史跡に
    しか出ない基準が別の見出しに割れ、「史跡」を選んだ読み手に「史跡 / 特別史跡」と
    「史跡 / 名勝 / 特別史跡」が並ぶ。読み手が要るのは**どの体系の基準か**であって、
    その基準が他にどこで使われているかではない。
    """
    origins: dict[str, Counter[int]] = {}
    fallback: dict[str, Counter[int]] = {}
    for row in rows:
        for value in row.facets[position]:
            fallback.setdefault(value, Counter())[row.dataset_index] += 1
            if row.key not in composite:
                origins.setdefault(value, Counter())[row.dataset_index] += 1
    # 複合指定にしか出ない値は、汚れていてもそれしか手掛かりが無い。
    found = {
        value: origins.get(value) or fallback.get(value) or Counter[int]() for value in values
    }
    present = set().union(*(set(tally) for tally in found.values())) if found else set()
    if not present:
        return []
    sizes = sorted(len(tally) for tally in found.values())
    if statistics.median(sizes) * 2 >= len(present):
        return []

    # 体系が 1 つしか無い軸はここへ来ない — 全値が同じデータセットに出るなら、
    # それは過半どころか全部で、上の横断の判定が先に落としている。
    grouped: dict[int, list[str]] = {}
    for value in values:
        tally = found[value]
        # 同数ならデータセットの並び順で決める (生成物を実行ごとに揺らさない)。
        origin = min(tally, key=lambda index: (-tally[index], index))
        grouped.setdefault(origin, []).append(value)
    return [
        (datasets[origin].name, tuple(found_values)) for origin, found_values in grouped.items()
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


def _order_kind(key: str, codes: dict[str, str], numbers: dict[str, int]) -> str:
    if key == AREA_KEY and codes:
        return ORDER_AREA
    if key == PERIOD_KEY:
        return ORDER_PERIOD
    return ORDER_NUMBER if numbers else ORDER_COUNT


def _numbers(counts: Counter[str]) -> dict[str, int]:
    """値の頭に振られた番号。**過半が番号を持つ軸だけ**が並びに使う。

    指定基準は原文が番号で並んでいる (`一．貝塚、集落跡…` `二．都城跡…`)。
    件数順にすると `八．` が `七．` の前に来るような並びになり、原文のどこを
    見ているのか読み手が追えない。**番号は値そのものが持っている**ので、
    基準の表をサイトに持たずに原文の並びへ戻せる (ADR 0014 / ADR 0015)。

    番号を持たない値が少しは混ざる — 登録有形の登録基準は 3 つとも番号を
    持たず、天然記念物にも `保護すべき天然記念物に富んだ代表的一定の区域` が
    ある。**過半で決める**のは、そういう軸を番号順にしつつ、番号らしき値が
    たまたま 1 つ 2 つ現れた軸を巻き込まないため。
    """
    found = {
        value: number for value in counts if (number := _leading_number(value)) is not None
    }
    return found if len(found) * 2 > len(counts) else {}


def _leading_number(value: str) -> int | None:
    found = _LEADING_NUMBER.match(value)
    return _kanji(found.group(1)) if found else None


def _kanji(text: str) -> int | None:
    """漢数字を数にする。**十二までの表を持たない** — 位取りで読む。

    指定基準の番号は十二までだが、原文が増えたときに表を書き足す作りにはしない。
    """
    tens, mark, ones = text.partition("十")
    if not mark:
        return _KANJI_DIGITS.get(text)
    upper = 1 if not tens else _KANJI_DIGITS.get(tens)
    lower = 0 if not ones else _KANJI_DIGITS.get(ones)
    if upper is None or lower is None:
        return None
    return upper * 10 + lower


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
    key: str,
    counts: Counter[str],
    medians: dict[str, float],
    codes: dict[str, str],
    numbers: dict[str, int],
) -> tuple[str, ...]:
    """値の並び。既定は件数の多い順、地域はコード順、時代は西暦の中央値順、
    番号を持つ値はその番号順。

    **地域を件数順に並べない** (Issue #7)。件数順だと探したい県の位置が予測できず、
    しかも件数は更新のたびに動くので、同じ県が先月と違う場所に来る。コードは
    総務省の都道府県コードで、データリポジトリのファイル名がそれを持っている。

    中央値が採れるのは西暦を持つ分類だけ (建造物系の 22 値)。史跡・記念物系の
    「中世」「古代」は西暦を持たないので、年代順の並びの**後ろ**へ件数順で回す。
    混ぜて並べる手はない — 年代の分からない値に位置を与えれば、それは推測になる。

    番号を持たない値も同じく**後ろ**へ件数順で回す。番号が同じ値どうし
    (天然記念物の `（一）` は動物・植物・地質鉱物の 3 体系に 1 つずつある) は、
    既定どおり件数の多い順。
    """
    if codes:
        # 桁数を先に見る。コードは 2 桁で揃っているが、揃わなくなっても
        # `10` が `2` の前に来る並びにはしない。
        return tuple(sorted(counts, key=lambda value: (len(codes[value]), codes[value])))
    if numbers:
        return tuple(
            sorted(
                counts,
                key=lambda value: (
                    (0, numbers[value], -counts[value], value)
                    if value in numbers
                    else (1, 0, -counts[value], value)
                ),
            )
        )
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
