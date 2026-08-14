"""ビルド時の不変条件 (Issue #32)。

サイトはデータリポジトリを読むだけで、直せる立場にない。だから検査の役目は
**壊れた状態で黙って配信されるのを止めること**に絞る。破れたら配信を止めるべき
ものを `error`、データ元の誤りとして報せるだけのものを `warning` に置く。

`error` でビルドを止めても既に配信済みのサイトは残る (Pages は最後の成功した
デプロイを配り続ける)。「古いまま」は「壊れたまま」より安全なので、構造の壊れは
止める側に倒す。逆に**データ元の誤りでサイトの更新を止めない** — 上流の誤字 1 件で
毎月の反映が止まるのは割に合わない。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Literal

from .datasets import SUPPORTED_SCHEMA_VERSIONS, Dataset, Row, data_files, location

Level = Literal["error", "warning", "info"]

# 日本の外周。ここから外れた座標は元データの誤りなので地図に置かない。
MIN_LATITUDE = 20.0
MAX_LATITUDE = 46.0
MIN_LONGITUDE = 122.0
MAX_LONGITUDE = 154.0

# 利用日がこれより古ければ月次更新が止まっている。ソース側に更新日が無いので、
# 「止まったことに気付く」仕掛けはこれしかない (ADR 0018)。月に 1 度の更新に
# 対して 1 回分の空振りぶんの余裕を見る。
DEFAULT_MAX_AGE_DAYS = 45

# 座標の欠けは元データの都合で常に一定数ある (実測 373 / 23,856 = 1.6%)。
# 急に増えたときだけ台帳の取得漏れを疑いたいので、比率で見る。
DEFAULT_MAX_MISSING_COORDINATE_RATIO = 0.05

# ただし比率だけでは件数の少ないデータセットで暴れる (36 件の特別名勝なら 2 件
# 欠けただけで 5% を超える)。取得漏れを疑うに足る件数に達するまでは報せるだけ。
DEFAULT_MIN_MISSING_COORDINATES = 50

_MAX_EXAMPLES = 5


@dataclass(frozen=True)
class Finding:
    check: str
    level: Level
    message: str
    examples: tuple[str, ...] = ()


def in_japan(latitude: float, longitude: float) -> bool:
    return (
        MIN_LATITUDE <= latitude <= MAX_LATITUDE and MIN_LONGITUDE <= longitude <= MAX_LONGITUDE
    )


def run(
    datasets: list[Dataset],
    rows: list[Row],
    *,
    today: date,
    checked_date: str = "",
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    max_missing_coordinate_ratio: float = DEFAULT_MAX_MISSING_COORDINATE_RATIO,
    min_missing_coordinates: int = DEFAULT_MIN_MISSING_COORDINATES,
) -> list[Finding]:
    findings: list[Finding] = []
    findings += _check_schema_version(datasets)
    findings += _check_accessed_date(
        datasets, today=today, max_age_days=max_age_days, checked_date=checked_date
    )
    findings += _check_files(datasets)
    findings += _check_counts(datasets, rows)
    findings += _check_required_fields(datasets, rows)
    findings += _check_shared_keys(datasets, rows)
    findings += _check_coordinates(
        datasets,
        rows,
        max_ratio=max_missing_coordinate_ratio,
        minimum=min_missing_coordinates,
    )
    return findings


def has_errors(findings: list[Finding]) -> bool:
    return any(finding.level == "error" for finding in findings)


def _check_schema_version(datasets: list[Dataset]) -> list[Finding]:
    unsupported = [
        f"{dataset.repo}: schema_version={dataset.schema_version!r}"
        for dataset in datasets
        if dataset.schema_version not in SUPPORTED_SCHEMA_VERSIONS
    ]
    if not unsupported:
        return []
    supported = ", ".join(str(version) for version in sorted(SUPPORTED_SCHEMA_VERSIONS))
    return [
        Finding(
            "schema_version",
            "error",
            f"サイトが対応していないスキーマ版のデータセットが {len(unsupported)} 件"
            f" (対応: {supported})",
            tuple(unsupported[:_MAX_EXAMPLES]),
        )
    ]


def _check_accessed_date(
    datasets: list[Dataset], *, today: date, max_age_days: int, checked_date: str
) -> list[Finding]:
    """更新の仕組みが止まっていないかを見る。

    **見る日付は 2 つあり、意味が違う。**

    - 利用日 (`accessed_date`) … そのデータを取り出した日。上流が長く変わらなければ
      古いままになるが、それは正常
    - 確認日 (`checked_date`) … データベースを見にいった最後の日。クローラーが
      渡してくる

    だから**確認日が分かるときは、そちらで判定する**。確認日が渡されないとき
    (手元での組み立てなど) だけ、利用日の古さを安全網として使う — どちらも見ないと、
    仕組みが止まったことに誰も気付けない。
    """
    findings: list[Finding] = []
    unreadable: list[str] = []
    stale: list[str] = []
    for dataset in datasets:
        value = dataset.accessed_date
        try:
            accessed = date.fromisoformat(value)
        except (TypeError, ValueError):
            unreadable.append(f"{dataset.repo}: accessed_date={value!r}")
            continue
        # 確認日が分かるなら、利用日の古さは判定に使わない (古いのが正常なため)。
        if checked_date:
            continue
        age = (today - accessed).days
        if age > max_age_days:
            stale.append(f"{dataset.repo}: {accessed.isoformat()} ({age} 日前)")
    if unreadable:
        findings.append(
            Finding(
                "accessed_date",
                "error",
                f"利用日を日付として読めないデータセットが {len(unreadable)} 件",
                tuple(unreadable[:_MAX_EXAMPLES]),
            )
        )
    if stale:
        findings.append(
            Finding(
                "accessed_date",
                "error",
                f"利用日が {max_age_days} 日より古いデータセットが {len(stale)} 件"
                " — 差分更新が止まっている疑い",
                tuple(stale[:_MAX_EXAMPLES]),
            )
        )
    findings += _check_checked_date(today=today, max_age_days=max_age_days, value=checked_date)
    return findings


def _check_checked_date(*, today: date, max_age_days: int, value: str) -> list[Finding]:
    """確認日そのものが古くないか。

    ここが古いのは**データが変わっていない**のではなく、**確かめに行けていない**
    という意味なので、配信を止める。
    """
    if not value:
        return []
    try:
        checked = date.fromisoformat(value)
    except (TypeError, ValueError):
        return [Finding("checked_date", "error", f"確認日を日付として読めない: {value!r}")]
    age = (today - checked).days
    if age <= max_age_days:
        return []
    return [
        Finding(
            "checked_date",
            "error",
            f"確認日が {max_age_days} 日より古い ({checked.isoformat()}・{age} 日前)"
            " — 週次の更新が止まっている疑い",
        )
    ]


def _check_files(datasets: list[Dataset]) -> list[Finding]:
    """`meta.json` が並べたファイルと実在するファイルの突き合わせ。

    宣言に無いファイルを配ると `meta.json` の件数と中身がずれ、宣言だけあって
    実在しないファイルはサイトから 404 になる。どちらも配信前に止める。
    """
    missing: list[str] = []
    undeclared: list[str] = []
    for dataset in datasets:
        declared = {str(entry.get("path", "")) for entry in dataset.declared_files}
        present = {f"data/{path.name}" for path in data_files(dataset)}
        missing += [f"{dataset.repo}/{path}" for path in sorted(declared - present)]
        undeclared += [f"{dataset.repo}/{path}" for path in sorted(present - declared)]
    findings: list[Finding] = []
    if missing:
        findings.append(
            Finding(
                "files",
                "error",
                f"meta.json が並べているのに実在しないファイルが {len(missing)} 件",
                tuple(missing[:_MAX_EXAMPLES]),
            )
        )
    if undeclared:
        findings.append(
            Finding(
                "files",
                "error",
                f"meta.json に無いのに置かれているファイルが {len(undeclared)} 件",
                tuple(undeclared[:_MAX_EXAMPLES]),
            )
        )
    return findings


def _check_counts(datasets: list[Dataset], rows: list[Row]) -> list[Finding]:
    """`meta.json` の件数と実際の行数の突き合わせ。

    どちらもデータリポジトリ側の生成物なので普通は一致する。ずれていれば
    「メタだけ更新された」「途中で落ちた」といった生成の失敗を意味する。
    """
    actual_records: dict[int, int] = defaultdict(int)
    actual_coordinates: dict[int, int] = defaultdict(int)
    actual_per_file: dict[tuple[int, str], int] = defaultdict(int)
    for row in rows:
        actual_records[row.dataset_index] += 1
        actual_per_file[(row.dataset_index, row.path)] += 1
        if row.has_coordinates:
            actual_coordinates[row.dataset_index] += 1

    mismatched: list[str] = []
    for index, dataset in enumerate(datasets):
        counts = dataset.counts
        for label, declared, actual in (
            ("records", counts.get("records"), actual_records[index]),
            ("with_coordinates", counts.get("with_coordinates"), actual_coordinates[index]),
        ):
            if declared != actual:
                mismatched.append(f"{dataset.repo}: counts.{label} {declared!r} ≠ 実際 {actual}")
        for entry in dataset.declared_files:
            path = str(entry.get("path", ""))
            declared_records = entry.get("records")
            actual_file = actual_per_file[(index, path)]
            if declared_records != actual_file:
                mismatched.append(
                    f"{dataset.repo}/{path}: records {declared_records!r} ≠ 実際 {actual_file}"
                )
    if not mismatched:
        return []
    return [
        Finding(
            "counts",
            "error",
            f"meta.json の件数と実際の行数が合わない箇所が {len(mismatched)} 件",
            tuple(mismatched[:_MAX_EXAMPLES]),
        )
    ]


def _check_required_fields(datasets: list[Dataset], rows: list[Row]) -> list[Finding]:
    """索引が成り立つ最低限。これが欠けると行を指す手段が無くなる。"""
    broken = [
        f"{location(datasets, row)}: {', '.join(missing)} が空"
        for row in rows
        if (
            missing := [
                label
                for label, value in (
                    ("ledger_id", row.ledger_id),
                    ("managed_id", row.managed_id),
                    ("name", row.name),
                    ("url", row.url),
                )
                if not value
            ]
        )
    ]
    if not broken:
        return []
    return [
        Finding(
            "required_fields",
            "error",
            f"索引に要る項目が空の行が {len(broken)} 件",
            tuple(broken[:_MAX_EXAMPLES]),
        )
    ]


def _check_shared_keys(datasets: list[Dataset], rows: list[Row]) -> list[Finding]:
    """複数のデータセットに現れる棟は、同じ原本を指しているはず。

    401 の複合指定は同じ行を 2 つのリポジトリへ書く (ADR 0012)。**同じ棟なのに
    違う原本 URL を指していたら、複合指定ではなく別物を同じキーで数えている**。
    サイトはこのキーで相互リンクを引くので、ここが崩れると誤った併記になる。
    """
    urls: dict[tuple[str, str], set[str]] = defaultdict(set)
    repos: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        urls[row.key].add(row.url)
        repos[row.key].add(datasets[row.dataset_index].repo)

    conflicting = [
        f"{key[0]}/{key[1]}: {', '.join(sorted(urls[key]))}"
        for key in sorted(urls)
        if len(repos[key]) > 1 and len(urls[key]) > 1
    ]
    if not conflicting:
        return []
    return [
        Finding(
            "shared_keys",
            "error",
            f"複数のデータセットに現れる棟のうち、原本 URL が食い違うものが {len(conflicting)} 件",
            tuple(conflicting[:_MAX_EXAMPLES]),
        )
    ]


def _check_coordinates(
    datasets: list[Dataset], rows: list[Row], *, max_ratio: float, minimum: int
) -> list[Finding]:
    """座標の欠けと、日本の外周から外れた座標。

    **座標が無い行を黙って落とさない** (Issue #32)。地図に出せないだけで、一覧には
    出す。ここで数えるのは「元データがどれだけ地図に出せないか」を毎回見える形に
    残すため。
    """
    missing = [row for row in rows if not row.has_coordinates]
    outside = [
        row
        for row in rows
        if row.latitude is not None
        and row.longitude is not None
        and not in_japan(row.latitude, row.longitude)
    ]

    findings: list[Finding] = []
    ratio = len(missing) / len(rows) if rows else 0.0
    if ratio > max_ratio and len(missing) >= minimum:
        findings.append(
            Finding(
                "coordinates",
                "error",
                f"座標の無い行が {len(missing)} 件 ({ratio:.1%}) で上限 {max_ratio:.1%} を超えた"
                " — 台帳の取得漏れを疑う",
                tuple(_describe(datasets, row) for row in missing[:_MAX_EXAMPLES]),
            )
        )
    else:
        findings.append(
            Finding(
                "coordinates",
                "info",
                f"座標の無い行が {len(missing)} 件 ({ratio:.1%})。一覧には出し、地図には出さない",
            )
        )
    if outside:
        findings.append(
            Finding(
                "bbox",
                "warning",
                f"日本の外周 (緯度 {MIN_LATITUDE:.0f}〜{MAX_LATITUDE:.0f} /"
                f" 経度 {MIN_LONGITUDE:.0f}〜{MAX_LONGITUDE:.0f}) の外にある座標が"
                f" {len(outside)} 件。元データの誤りとして地図から除く",
                tuple(
                    f"{_describe(datasets, row)} ({row.latitude}, {row.longitude})"
                    for row in outside[:_MAX_EXAMPLES]
                ),
            )
        )
    return findings


def _describe(datasets: list[Dataset], row: Row) -> str:
    """報告に出す 1 行。**キーまで書く** — 位置だけでは原本を引けない。"""
    return f"{location(datasets, row)}: {row.ledger_id}/{row.managed_id} {row.name}"
