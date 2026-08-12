"""コマンドライン。

`heritage-site build --data-dir <データリポジトリを並べた親> --out dist`

GitHub Actions からも手元からも同じコマンドを使う。手元では
データリポジトリ群を置いたディレクトリを指せば、そのままビルドを再現できる。
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .build import BuildReport, build
from .checks import DEFAULT_MAX_AGE_DAYS, DEFAULT_MAX_MISSING_COORDINATE_RATIO
from .datasets import DataError

_LEVEL_MARK = {"error": "NG", "warning": "警告", "info": "情報"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        report = build(
            args.data_dir,
            args.out,
            site_dir=args.site_dir,
            max_age_days=args.max_age_days,
            max_missing_coordinate_ratio=args.max_missing_coordinate_ratio,
            write=not args.check_only,
        )
    except DataError as error:
        print(f"NG: {error}", file=sys.stderr)
        return 2
    _report(report, out=args.out, wrote=not args.check_only and not report.failed)
    return 1 if report.failed else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="heritage-site", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    command = subparsers.add_parser("build", help="配信するディレクトリを組み立てる")
    command.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="データリポジトリを並べた親ディレクトリ (meta.json を持つものだけが対象)",
    )
    command.add_argument("--out", type=Path, default=Path("dist"), help="出力先 (既定: dist)")
    command.add_argument(
        "--site-dir", type=Path, default=Path("site"), help="静的ファイルの置き場 (既定: site)"
    )
    command.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        help=f"利用日の許容日数 (既定: {DEFAULT_MAX_AGE_DAYS})",
    )
    command.add_argument(
        "--max-missing-coordinate-ratio",
        type=float,
        default=DEFAULT_MAX_MISSING_COORDINATE_RATIO,
        help=f"座標が無い行の許容割合 (既定: {DEFAULT_MAX_MISSING_COORDINATE_RATIO})",
    )
    command.add_argument(
        "--check-only", action="store_true", help="検査だけ行い、何も書き出さない"
    )
    return parser


def _report(report: BuildReport, *, out: Path, wrote: bool) -> None:
    print(f"データセット {len(report.datasets)} 件")
    for dataset in report.datasets:
        records = dataset.counts.get("records")
        print(f"  {dataset.repo}: {dataset.name} / {records} 件 / 利用日 {dataset.accessed_date}")
    print(
        f"行 {report.rows} / 異なり {report.distinct}"
        f" / 複数データセットに現れる棟 {report.shared}"
        f" / 座標あり {report.with_coordinates} / 地図に出す {report.mapped}"
    )
    for finding in report.findings:
        stream = sys.stderr if finding.level == "error" else sys.stdout
        print(f"{_LEVEL_MARK[finding.level]}: [{finding.check}] {finding.message}", file=stream)
        for example in finding.examples:
            print(f"    - {example}", file=stream)
    if report.failed:
        print("NG: 不変条件が破れたので何も書き出していない", file=sys.stderr)
    elif wrote:
        print(f"OK: {out} を書き出した")
    else:
        print("OK: 検査のみ (何も書き出していない)")
