"""配信するディレクトリを組み立てる。

やることは 3 つだけ。

1. データリポジトリの `meta.json` を束ねた `index.json` を書く
2. 一覧・検索・地図が読む行の索引 `records.json` を書く
3. JSON Lines を**変換せずそのまま**並べ、静的ファイルを重ねる

**JSON Lines に手を入れないのが要** (ADR 0015)。サイトが見せているのは
データリポジトリのあの行そのもの、と言える状態を保つ。生成するのは索引だけ。

行の索引は **1 本にする**。地図だけが読む索引 (`points.json`) を別に持つと、
名称とキーを二重に運ぶことになる (実測 gzip 0.99 + 0.50 MB 対 まとめて 1.23 MB)。
一覧は座標の有無を「地図に位置がない」の判定に使い、地図は同じ列を座標として
読む — 同じ事実を 2 つのファイルに書き分ける理由が無い。
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .checks import (
    DEFAULT_MAX_AGE_DAYS,
    DEFAULT_MAX_MISSING_COORDINATE_RATIO,
    Finding,
    has_errors,
    in_japan,
)
from .checks import run as run_checks
from .datasets import (
    DATA_DIRNAME,
    DataError,
    Dataset,
    Row,
    data_files,
    discover,
    iter_rows,
)
from .facets import Axis, axis_keys, build_axes, positions
from .search import SEARCH_FIELDS

# 生成物のスキーマ版。フロントがこの版を見て、読めない索引で黙って壊れるのを防ぐ。
# 2 で行の出どころ (`files` / `file` / `line`) が入った — 詳細ビューが JSON Lines を
# その場で読むための道しるべ (Issue #32 §4)。
SITE_SCHEMA_VERSION = 2

DATASETS_DIRNAME = "datasets"
INDEX_FILENAME = "index.json"
RECORDS_FILENAME = "records.json"

# 出力先を消してよいかの目印。`--out` の打ち間違いで別のディレクトリを消さない。
MARKER_FILENAME = ".heritage-site-build"

# 日本標準時。利用日はデータリポジトリ側も日本時間で切っている (ADR 0014)。
JST = timezone(timedelta(hours=9))


@dataclass
class BuildReport:
    datasets: list[Dataset]
    rows: int
    distinct: int
    shared: int
    with_coordinates: int
    mapped: int
    findings: list[Finding]

    @property
    def failed(self) -> bool:
        return has_errors(self.findings)


def today_in_japan() -> date:
    return datetime.now(JST).date()


def build(
    data_dir: Path,
    out_dir: Path,
    *,
    site_dir: Path,
    today: date | None = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    max_missing_coordinate_ratio: float = DEFAULT_MAX_MISSING_COORDINATE_RATIO,
    write: bool = True,
) -> BuildReport:
    """`data_dir` に並んだデータリポジトリから `out_dir` を作る。

    検査に `error` があれば何も書かずに戻る。壊れた索引で上書きするより、
    既に配信されているものを残す方が安全 (`checks` の方針)。
    """
    datasets = discover(data_dir)
    # どの軸で絞り込めるかは `meta.json` が決める (ADR 0014)。行を読む前に
    # 決まっていなければ、行から軸の値を拾えない。
    keys = axis_keys(datasets)
    rows = [
        row
        for index, dataset in enumerate(datasets)
        for row in iter_rows(dataset, index, facet_keys=keys)
    ]

    findings = run_checks(
        datasets,
        rows,
        today=today or today_in_japan(),
        max_age_days=max_age_days,
        max_missing_coordinate_ratio=max_missing_coordinate_ratio,
    )
    report = _summarize(datasets, rows, findings)
    if report.failed or not write:
        return report

    axes = build_axes(datasets, rows, keys)
    _prepare(out_dir)
    _write_json(out_dir / INDEX_FILENAME, _index_payload(datasets, report), indent=2)
    _write_json(
        out_dir / RECORDS_FILENAME, _records_payload(datasets, rows, keys, axes), indent=None
    )
    _copy_site(site_dir, out_dir)
    _copy_data(datasets, out_dir)
    return report


def _summarize(datasets: list[Dataset], rows: list[Row], findings: list[Finding]) -> BuildReport:
    keys: dict[tuple[str, str], set[int]] = {}
    for row in rows:
        keys.setdefault(row.key, set()).add(row.dataset_index)
    return BuildReport(
        datasets=datasets,
        rows=len(rows),
        distinct=len(keys),
        shared=sum(1 for indexes in keys.values() if len(indexes) > 1),
        with_coordinates=sum(1 for row in rows if row.has_coordinates),
        mapped=sum(1 for row in rows if _mappable(row)),
        findings=findings,
    )


def _mappable(row: Row) -> bool:
    return (
        row.latitude is not None
        and row.longitude is not None
        and in_japan(row.latitude, row.longitude)
    )


def _index_payload(datasets: list[Dataset], report: BuildReport) -> dict[str, Any]:
    """`meta.json` を**そのまま**束ねる。

    サイト側で読み替えないので、データリポジトリが持つ語彙・ラベル・件数が
    そのまま画面に出る。種別が増えてもここは変わらない (ADR 0015)。
    """
    accessed = sorted(
        str(dataset.accessed_date) for dataset in datasets if dataset.accessed_date
    )
    return {
        "schema_version": SITE_SCHEMA_VERSION,
        "totals": {
            "records": report.rows,
            "distinct": report.distinct,
            "shared": report.shared,
            "with_coordinates": report.with_coordinates,
            "mapped": report.mapped,
        },
        "accessed_dates": {
            "oldest": accessed[0] if accessed else None,
            "newest": accessed[-1] if accessed else None,
        },
        "datasets": [
            {
                "repo": dataset.repo,
                "path": f"{DATASETS_DIRNAME}/{dataset.repo}",
                "meta": dataset.meta,
            }
            for dataset in datasets
        ],
    }


def _records_payload(
    datasets: list[Dataset], rows: list[Row], keys: list[str], axes: list[Axis]
) -> dict[str, Any]:
    """一覧・検索・地図が読む行の索引。

    2 万を超える行を配るので、行はオブジェクトではなく配列にする (キー名の
    繰り返しがそのまま転送量になる)。並びは `fields` が持ち、ファセットの値は
    語彙の番号で書く。

    **座標は地図に置けるものだけ入れる。**欠けている行と日本の外周から外れた行は
    `null` にして、一覧が「地図に位置がない」と示せるようにする — 誤った座標を
    渡して地図に置かせるより、位置が無いと言う方が正しい (`checks` が件数と実例を
    報告に出す)。

    **行の全項目は索引に入れず、出どころ (`file` / `line`) だけ持つ** (Issue #32 §4)。
    解説文まで抱えると索引が桁違いに重くなるうえ、配っている JSON Lines と同じ値を
    2 か所に持つことになる。詳細ビューはこの道しるべで元の行を読みに行く。
    **行番号が要るのは `(台帳ID, 管理対象ID)` が一意でないため** — 102 は 1 指定が
    複数の棟に展開され、同じキーの行が同じファイルに並ぶ。
    """
    numbers = positions(axes)
    axis_positions = [(axis, keys.index(axis.key)) for axis in axes]
    files = [
        [f"{DATA_DIRNAME}/{path.name}" for path in data_files(dataset)] for dataset in datasets
    ]
    file_numbers = {
        (dataset_index, path): number
        for dataset_index, paths in enumerate(files)
        for number, path in enumerate(paths)
    }
    return {
        "schema_version": SITE_SCHEMA_VERSION,
        "datasets": [dataset.repo for dataset in datasets],
        # データセットごとの JSON Lines。行はここへの番号で出どころを指す
        # (ファイル名を 2 万行ぶん繰り返さない)。
        "files": files,
        "search_fields": list(SEARCH_FIELDS),
        "axes": [
            # `order` は並びの根拠。画面はこれを見て畳み方を決める (Issue #7)。
            {
                "key": axis.key,
                "label": axis.label,
                "order": axis.order,
                "values": list(axis.values),
            }
            for axis in axes
        ],
        "fields": [
            "dataset",
            "file",
            "line",
            "ledger_id",
            "managed_id",
            "name",
            "ridge_name",
            "address",
            "designated_year",
            "url",
            "latitude",
            "longitude",
            "search",
            "facets",
        ],
        "records": [
            [
                row.dataset_index,
                file_numbers[(row.dataset_index, row.path)],
                row.line,
                row.ledger_id,
                row.managed_id,
                row.name,
                row.ridge_name,
                row.address,
                row.designated_year,
                row.url,
                row.latitude if _mappable(row) else None,
                row.longitude if _mappable(row) else None,
                row.search,
                [
                    [numbers[axis.key][value] for value in row.facets[position]]
                    for axis, position in axis_positions
                ],
            ]
            for row in rows
        ],
    }


def _prepare(out_dir: Path) -> None:
    if out_dir.exists():
        if any(out_dir.iterdir()) and not (out_dir / MARKER_FILENAME).exists():
            raise DataError(
                f"出力先が空でなく、このビルドの生成物でもない: {out_dir}"
                f" (消してよければ {MARKER_FILENAME} を置くか、別の出力先を指定する)"
            )
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    (out_dir / MARKER_FILENAME).write_text(
        "heritage-site が作る。中身は毎回作り直される。\n", encoding="utf-8"
    )


def _copy_site(site_dir: Path, out_dir: Path) -> None:
    if not site_dir.is_dir():
        raise DataError(f"静的ファイルの置き場が無い: {site_dir}")
    shutil.copytree(site_dir, out_dir, dirs_exist_ok=True)


def _copy_data(datasets: list[Dataset], out_dir: Path) -> None:
    for dataset in datasets:
        destination = out_dir / DATASETS_DIRNAME / dataset.repo / DATA_DIRNAME
        destination.mkdir(parents=True, exist_ok=True)
        for path in data_files(dataset):
            shutil.copyfile(path, destination / path.name)


def _write_json(path: Path, payload: dict[str, Any], *, indent: int | None) -> None:
    separators = None if indent else (",", ":")
    text = json.dumps(payload, ensure_ascii=False, indent=indent, separators=separators)
    path.write_text(text + "\n", encoding="utf-8")
