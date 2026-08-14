"""コマンドライン。

```
heritage-site build --data-dir <データリポジトリを並べた親> --out dist
heritage-site pack  --data-dir <同上> --out-dir dist
heritage-site diff  --data-dir <同上> --out dist [--before <前回の ZIP>]
```

GitHub Actions からも手元からも同じコマンドを使う。手元では
データリポジトリ群を置いたディレクトリを指せば、そのまま再現できる。
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

from .archive import Archive, PackReport, dataset_archive_name, pack
from .build import BuildReport, build
from .changes import CHANGES_JSON, NOTES_MARKDOWN, Changes, compare, write_for_dataset
from .changes import write as write_changes
from .checks import DEFAULT_MAX_AGE_DAYS, DEFAULT_MAX_MISSING_COORDINATE_RATIO
from .datasets import DataError

_LEVEL_MARK = {"error": "NG", "warning": "警告", "info": "情報"}

# 種別ごとの書き出し先。**リポジトリ名で仕切る** — ワークフローが
# `<out>/datasets/<リポジトリ名>/notes.md` を素直に指せるようにする。
DATASETS_DIRNAME = "datasets"


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "pack":
            return _pack(args)
        if args.command == "diff":
            return _diff(args)
        return _build(args)
    except DataError as error:
        print(f"NG: {error}", file=sys.stderr)
        return 2


def _build(args: argparse.Namespace) -> int:
    report = build(
        args.data_dir,
        args.out,
        site_dir=args.site_dir,
        checked_date=args.checked_date,
        max_age_days=args.max_age_days,
        max_missing_coordinate_ratio=args.max_missing_coordinate_ratio,
        write=not args.check_only,
    )
    _report(report, out=args.out, wrote=not args.check_only and not report.failed)
    return 1 if report.failed else 0


def _pack(args: argparse.Namespace) -> int:
    _report_pack(pack(args.data_dir, args.out_dir))
    return 0


def _diff(args: argparse.Namespace) -> int:
    """前回の配布物と突き合わせて、差分と各リリースのノートを書き出す。

    **差分が無くても失敗にしない。** 「変わらなかった」は正常な結果で、リリースを
    立てるかどうかは `changes.json` の `has_changes` を見て呼び出し側が決める
    (`.github/workflows/deliver.yml`)。
    """
    if args.before is None:
        return _write_diff(compare(args.data_dir, None), args.out)
    # 前回の ZIP を展開して、**今回と同じコードで読む**。配布物の構造は
    # データリポジトリを並べた形そのままなので、`discover` がそのまま効く。
    with tempfile.TemporaryDirectory() as workspace:
        before = Path(workspace) / "before"
        with zipfile.ZipFile(args.before) as archive:
            archive.extractall(before)
        return _write_diff(compare(args.data_dir, before), args.out)


def _write_diff(changes: Changes, out: Path) -> int:
    write_changes(changes, out)
    print(f"利用日 {changes.accessed_date} / 全 {changes.records:,} 行")
    if changes.baseline:
        print("初回 (前回の配布物が無いので、全件を基準にする)")
    else:
        print(
            f"追加 {len(changes.added):,} / 削除 {len(changes.removed):,}"
            f" / 変更 {len(changes.changed):,}"
        )
    for dataset in changes.datasets:
        only = write_for_dataset(
            changes,
            out / DATASETS_DIRNAME / dataset.repo,
            repo=dataset.repo,
            archive=dataset_archive_name(dataset.repo),
        )
        mark = "変更あり" if only.has_changes else "変更なし"
        print(
            f"  {dataset.repo}: {mark}"
            f" (追加 {len(only.added):,} / 削除 {len(only.removed):,}"
            f" / 変更 {len(only.changed):,})"
        )
    print(f"OK: {out} に {CHANGES_JSON} と {NOTES_MARKDOWN} を書き出した")
    return 0


_DATA_DIR_HELP = "データリポジトリを並べた親ディレクトリ (meta.json を持つものだけが対象)"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="heritage-site", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    pack_command = subparsers.add_parser("pack", help="配布物 (ZIP) を固める")
    pack_command.add_argument("--data-dir", type=Path, required=True, help=_DATA_DIR_HELP)
    pack_command.add_argument(
        "--out-dir", type=Path, default=Path("dist"), help="出力先 (既定: dist)"
    )

    diff_command = subparsers.add_parser("diff", help="前回の配布物と突き合わせる")
    diff_command.add_argument("--data-dir", type=Path, required=True, help=_DATA_DIR_HELP)
    diff_command.add_argument(
        "--before",
        type=Path,
        default=None,
        help="前回の全部入り ZIP (省略すると初回として扱う)",
    )
    diff_command.add_argument("--out", type=Path, default=Path("dist"), help="出力先 (既定: dist)")

    command = subparsers.add_parser("build", help="配信するディレクトリを組み立てる")
    command.add_argument("--data-dir", type=Path, required=True, help=_DATA_DIR_HELP)
    command.add_argument("--out", type=Path, default=Path("dist"), help="出力先 (既定: dist)")
    command.add_argument(
        "--checked-date",
        default="",
        help="データベースを確認した日 (YYYY-MM-DD)。クローラーが渡す。省略すると出さない",
    )
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


def _report_pack(report: PackReport) -> None:
    _report_archive(report.everything, name="全部入り")
    for archive in report.per_dataset:
        _report_archive(archive, name=archive.repo or "")
    print(f"OK: 配布物 {len(report.archives)} 個を書き出した")


def _report_archive(archive: Archive, *, name: str) -> None:
    print(
        f"  {name}: {archive.path.name}"
        f" / {archive.records:,} 件 / {archive.files:,} ファイル"
        f" / {archive.size / 1024 / 1024:.1f} MB"
    )


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
