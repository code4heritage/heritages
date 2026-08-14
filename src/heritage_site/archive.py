"""配布物 (ZIP) を固める。

データは種別ごとの 10 リポジトリに分かれているので、まとめて落とす手段が無く、
「いつ時点のデータか」を指して引用することもできない。ここで作る ZIP が
その両方を引き受ける。

**作るのは 11 個** — 種別横断の全部入りと、種別ごとの 10 個。前者は
`heritages` のリリースへ、後者は各データリポジトリのリリースへ置く。**同じ
コードから作る**ので、種別が増えても書き足すところは無い (ADR 0001 の「分けるのは
データであってコードではない」の延長)。**中身の構造は置き場に合わせる** — 全部入りは
`<リポジトリ名>/data/...` と並べ、種別ごとのぶんは展開するとそのデータリポジトリの
中身そのものになる。

**中身は変換しない。** JSON Lines も `meta.json` も、データリポジトリに置かれて
いるバイト列そのままを入れる — サイトが行に手を入れないのと同じ理由で
(ADR 0015)、配っているのが「あの行そのもの」だと言える状態を保つ。

**ZIP は決定的に作る。** 同じ入力なら同じバイト列になるよう、格納順とタイム
スタンプを固定する。データリポジトリの生成物が決定的であること (ADR 0014) を
配布物まで延ばしたもので、「データが変わっていないのに配布物だけ変わった」を
起こさないための性質。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .datasets import DATA_DIRNAME, META_FILENAME, DataError, Dataset, data_files, discover

# `MANIFEST.json` のスキーマ版。読み手 (配布物を機械で扱う人) が、知らない形で
# 黙って壊れずに済むようにする。
MANIFEST_SCHEMA_VERSION = 1

MANIFEST_FILENAME = "MANIFEST.json"

# 全部入りの名前。**月ごとに変えない** — `releases/latest/download/<名前>` を
# 固定 URL として使えるようにするため。版はタグが持つ。
ARCHIVE_NAME = "heritages-jsonl.zip"

# 取得元の commit を受け取るファイル (`<リポジトリ名> <commit>` を 1 行ずつ)。
# `scripts/fetch-datasets.sh` が書く。**`pack` から `git` を呼ばない** — data-dir を
# 読んで ZIP を書くだけの仕事に保つと、手元でもテストでも同じコードが動く。
SOURCES_FILENAME = "sources.txt"

# データのほかに ZIP へ入れるファイル。出典・利用条件が配布物だけで完結するよう、
# ライセンスと README を必ず連れて行く。無ければ黙って飛ばす。
EXTRA_FILENAMES = (META_FILENAME, "LICENSE", "README.md")

# ZIP に書き込む時刻。**実行時刻を入れない** — 入れると同じデータから作った
# 配布物が実行のたびに別のバイト列になる。ZIP が表せる最も古い時刻を使う。
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

# 通常ファイルの属性 (rw-r--r--)。展開したときの権限を環境に依存させない。
FILE_MODE = 0o644


@dataclass(frozen=True)
class ArchivedFile:
    """ZIP に入れた 1 ファイル。"""

    path: str
    """ZIP の中での位置 (`<リポジトリ名>/data/13_tokyo.jsonl`)。"""

    size: int
    sha256: str
    records: int | None = None
    """JSON Lines のときだけ、空でない行の数。"""


@dataclass(frozen=True)
class ArchivedDataset:
    """ZIP に入れたデータセット 1 つ。"""

    repo: str
    name: str
    schema_version: Any
    accessed_date: Any
    commit: str | None
    files: list[ArchivedFile]

    @property
    def records(self) -> int:
        return sum(entry.records or 0 for entry in self.files)


@dataclass(frozen=True)
class Archive:
    """書き出した ZIP 1 つ。"""

    path: Path
    repo: str | None
    """種別ごとのぶんならリポジトリ名。全部入りなら `None`。"""

    datasets: list[ArchivedDataset]
    size: int

    @property
    def records(self) -> int:
        return sum(dataset.records for dataset in self.datasets)

    @property
    def files(self) -> int:
        return sum(len(dataset.files) for dataset in self.datasets)


@dataclass(frozen=True)
class PackReport:
    """固めた結果。CLI とワークフローが件数と置き場を知るのに使う。"""

    everything: Archive
    per_dataset: list[Archive]

    @property
    def archives(self) -> list[Archive]:
        return [self.everything, *self.per_dataset]


def dataset_archive_name(repo: str) -> str:
    """種別ごとの配布物の名前。

    リポジトリ名を入れるのは、落としたあとのファイルだけを見て何のデータか
    分かるようにするため。**月ごとには変えない** (全部入りと同じ理由)。
    """
    return f"{repo}-jsonl.zip"


def pack(data_dir: Path, out_dir: Path) -> PackReport:
    """`data_dir` に並んだデータリポジトリを ZIP に固める。

    書くのは全部入り 1 つと種別ごとの 10 個。対象は `meta.json` を持つディレクトリ
    だけ (`discover`) なので、データの無い器を削除しても (ADR 0013)、種別が増えても、
    ここは変わらない。
    """
    datasets = discover(data_dir)
    commits = read_sources(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    everything = _write_archive(out_dir / ARCHIVE_NAME, datasets, commits, repo=None)
    per_dataset = [
        _write_archive(
            out_dir / dataset_archive_name(dataset.repo), [dataset], commits, repo=dataset.repo
        )
        for dataset in datasets
    ]
    return PackReport(everything=everything, per_dataset=per_dataset)


def _write_archive(
    path: Path, datasets: list[Dataset], commits: dict[str, str], *, repo: str | None
) -> Archive:
    """ZIP を 1 つ書く。

    `repo` が付いているぶんは**そのリポジトリの構造そのまま**で入れる (展開すれば
    データリポジトリの中身になる)。全部入りはリポジトリ名で仕切る。
    """
    archived: list[ArchivedDataset] = []
    # 中身を 2 度読まないよう、ZIP へ書きながら目録を組む。
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for dataset in datasets:
            archived.append(
                _add_dataset(archive, dataset, commits.get(dataset.repo), prefixed=repo is None)
            )
        # 目録は中身を読み終えるまで内容が決まらないので最後に書く。読み手には
        # 名前で見つけてもらう (ZIP の中の並びは読み出しに関係しない)。
        _write(archive, MANIFEST_FILENAME, _json_bytes(_manifest(archived)))
    return Archive(path=path, repo=repo, datasets=archived, size=path.stat().st_size)


def read_sources(data_dir: Path) -> dict[str, str]:
    """取得元の commit (`sources.txt`)。無ければ空で返す。

    手元で `data_dir` を直接指したときは commit を知りようがないので、**無いのは
    正常**。目録からその項目が落ちるだけで、配布物は同じように作れる。
    """
    path = data_dir / SOURCES_FILENAME
    if not path.is_file():
        return {}
    commits: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        repo, _, commit = raw.strip().partition(" ")
        if not repo:
            continue
        if not commit.strip():
            raise DataError(f"{path}:{line_number} が「<リポジトリ名> <commit>」の形でない")
        commits[repo] = commit.strip()
    return commits


def _add_dataset(
    archive: ZipFile, dataset: Dataset, commit: str | None, *, prefixed: bool
) -> ArchivedDataset:
    files: list[ArchivedFile] = []
    for path in data_files(dataset):
        files.append(_add_file(archive, dataset, path, count_records=True, prefixed=prefixed))
    for filename in EXTRA_FILENAMES:
        path = dataset.root / filename
        if path.is_file():
            files.append(_add_file(archive, dataset, path, count_records=False, prefixed=prefixed))
    return ArchivedDataset(
        repo=dataset.repo,
        name=dataset.name,
        schema_version=dataset.schema_version,
        accessed_date=dataset.accessed_date,
        commit=commit,
        files=files,
    )


def _add_file(
    archive: ZipFile, dataset: Dataset, path: Path, *, count_records: bool, prefixed: bool
) -> ArchivedFile:
    data = path.read_bytes()
    relative = f"{DATA_DIRNAME}/{path.name}" if count_records else path.name
    inside = f"{dataset.repo}/{relative}" if prefixed else relative
    _write(archive, inside, data)
    return ArchivedFile(
        path=inside,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        # 空行は行として数えない (読み出し側も飛ばす。`datasets._iter_lines`)。
        records=sum(1 for line in data.splitlines() if line.strip()) if count_records else None,
    )


def _write(archive: ZipFile, name: str, data: bytes) -> None:
    info = ZipInfo(filename=name, date_time=FIXED_TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    # 3 = Unix。権限を持たせるには作成系を明示する必要がある。
    info.create_system = 3
    info.external_attr = FILE_MODE << 16
    archive.writestr(info, data)


def _manifest(datasets: list[ArchivedDataset]) -> dict[str, Any]:
    """配布物の目録。

    **生成日時は入れない。** 入れると同じデータから作った ZIP が実行のたびに
    変わる。いつ固めたかはリリースのタグと公開日で足り、いつデータを取得したかは
    データセットごとの利用日 (`accessed_date`) が持っている (ADR 0014)。
    """
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "source": {
            "name": "国指定文化財等データベース",
            "publisher": "文化庁",
            "url": "https://kunishitei.bunka.go.jp/",
        },
        "totals": {
            "datasets": len(datasets),
            "records": sum(dataset.records for dataset in datasets),
            "files": sum(len(dataset.files) for dataset in datasets),
        },
        "datasets": [
            {
                "repo": dataset.repo,
                "name": dataset.name,
                "schema_version": dataset.schema_version,
                "accessed_date": dataset.accessed_date,
                **({"commit": dataset.commit} if dataset.commit else {}),
                "records": dataset.records,
                "files": [
                    {
                        "path": entry.path,
                        "size": entry.size,
                        "sha256": entry.sha256,
                        **({} if entry.records is None else {"records": entry.records}),
                    }
                    for entry in dataset.files
                ],
            }
            for dataset in datasets
        ],
    }


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
