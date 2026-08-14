"""前回の配布物と今回のデータを突き合わせて、何が変わったかを書く。

**比べるのはリリースどうし** — 前回の ZIP と今回のデータ。クローラーが持っている
月次の計画 (新規 / 台帳の値が変わった / 巡回) は使わない。あれは台帳ベースなので、
解説文・員数のような**詳細ページにしか無い項目の変更が現れない**。データリポジトリ
の git 履歴も使わない (ビルドは `--depth 1` で clone しており、前回の状態を
持っていない)。配布物どうしを比べれば、「配って以降に変わったもの」がそのまま出る。

書き出すのは 3 つ。

- `changes.json` … 差分の全量 (機械可読)
- `changes.md`   … 同じものを人が読む形で
- `notes.md`     … リリースノートの本文

**`notes.md` には全量を入れない。** リリースノートは 125,000 字が上限で、
スキーマを変えて全件を組み立て直した月には 2 万件が動きうる。本文は件数と
抜粋にとどめ、全量は `changes.md` に置く。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .archive import ARCHIVE_NAME
from .datasets import Dataset, discover, iter_records

CHANGES_SCHEMA_VERSION = 1

# 種別ごとのノートから案内する、種別横断の配布物の置き場。
CROSS_TYPE_RELEASES = "https://github.com/code4heritage/heritages/releases/latest"

CHANGES_JSON = "changes.json"
CHANGES_MARKDOWN = "changes.md"
NOTES_MARKDOWN = "notes.md"

# リリースノートの節ごとに並べる実例の数。これを超えたぶんは件数だけ書いて
# `changes.md` へ送る。
NOTE_EXAMPLES = 20

# 前後を並べても読めない長さの項目。差分には「変わった」ことと増減した字数だけを
# 書き、全文は `changes.json` に残す。
LONG_TEXT_KEYS = frozenset({"description", "detailed_description", "notes"})


@dataclass(frozen=True)
class Entry:
    """差分に出てくる 1 件。名指しできるだけの情報を持つ。"""

    dataset: str
    dataset_name: str
    ledger_id: str
    managed_id: str
    name: str
    address: str
    url: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.dataset, self.ledger_id, self.managed_id)


@dataclass(frozen=True)
class FieldChange:
    """1 項目の変更。"""

    key: str
    label: str
    before: Any
    after: Any

    @property
    def is_long_text(self) -> bool:
        return self.key in LONG_TEXT_KEYS

    @property
    def delta(self) -> int:
        """長文の増減した字数。"""
        return len(_text(self.after)) - len(_text(self.before))

    def summary(self) -> str:
        """人が読む 1 行。長文は前後を並べず、増減した字数で示す。"""
        if self.is_long_text:
            delta = self.delta
            if not delta:
                return f"{self.label}が変わった"
            return f"{self.label}が変わった ({'+' if delta > 0 else ''}{delta} 字)"
        if self.before is None:
            return f"{self.label}が入った ({_display(self.after)})"
        if self.after is None:
            return f"{self.label}が消えた ({_display(self.before)})"
        return f"{self.label}: {_display(self.before)} → {_display(self.after)}"


@dataclass(frozen=True)
class Change:
    """内容が変わった 1 件。"""

    entry: Entry
    fields: tuple[FieldChange, ...]


@dataclass(frozen=True)
class DatasetSummary:
    """今回の配布物に入っている種別 1 つ。"""

    repo: str
    name: str
    records: int
    accessed_date: Any


@dataclass
class Changes:
    """突き合わせの結果。"""

    baseline: bool
    """前回の配布物が無い (初回) か。"""

    datasets: list[DatasetSummary] = field(default_factory=list)
    added: list[Entry] = field(default_factory=list)
    removed: list[Entry] = field(default_factory=list)
    changed: list[Change] = field(default_factory=list)
    datasets_added: list[str] = field(default_factory=list)
    datasets_removed: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """リリースを立てる値打ちがあるか。

        **利用日は差分に出てこない。** `meta.json` の利用日は毎月動くが
        (ADR 0018)、ここで見ているのは行の中身だけなので、データが 1 行も
        変わらなかった月はここが偽になり、リリースが立たない。
        """
        if self.baseline:
            return True
        return bool(
            self.added
            or self.removed
            or self.changed
            or self.datasets_added
            or self.datasets_removed
        )

    @property
    def records(self) -> int:
        return sum(dataset.records for dataset in self.datasets)

    @property
    def accessed_date(self) -> str:
        """配布物としての利用日。種別ごとに違いうるので最も新しいものを採る。"""
        dates = [str(dataset.accessed_date) for dataset in self.datasets if dataset.accessed_date]
        return max(dates) if dates else ""

    def counts_by_dataset(self) -> dict[str, tuple[int, int, int]]:
        """種別ごとの (追加, 削除, 変更)。1 件も動いていない種別は出さない。"""
        counts: dict[str, list[int]] = {}
        for entry in self.added:
            counts.setdefault(entry.dataset_name, [0, 0, 0])[0] += 1
        for entry in self.removed:
            counts.setdefault(entry.dataset_name, [0, 0, 0])[1] += 1
        for change in self.changed:
            counts.setdefault(change.entry.dataset_name, [0, 0, 0])[2] += 1
        return {name: (values[0], values[1], values[2]) for name, values in counts.items()}


def compare(after_dir: Path, before_dir: Path | None) -> Changes:
    """今回のデータ (`after_dir`) を前回の配布物 (`before_dir`) と突き合わせる。

    `before_dir` が `None` のときは初回。**追加として 2 万件を並べたりはしない** —
    全件が「追加」なのは自明で、読む人の役に立たない。
    """
    after = discover(after_dir)
    summaries, records, labels = _read(after)
    changes = Changes(baseline=before_dir is None, datasets=summaries)
    if before_dir is None:
        return changes

    before = discover(before_dir)
    _, previous, _ = _read(before)

    now = {dataset.repo for dataset in after}
    was = {dataset.repo for dataset in before}
    changes.datasets_added = sorted(now - was)
    changes.datasets_removed = sorted(was - now)

    # 消えた種別の名前も要る (削除された行の呼び名になる)。
    names = {dataset.repo: dataset.name for dataset in before}
    names.update({dataset.repo: dataset.name for dataset in after})

    for key in sorted(records.keys() - previous.keys()):
        changes.added.append(_entry(key, records[key], names))
    for key in sorted(previous.keys() - records.keys()):
        changes.removed.append(_entry(key, previous[key], names))
    for key in sorted(records.keys() & previous.keys()):
        fields = _compare_values(previous[key], records[key], labels.get(key[0], {}))
        if fields:
            changes.changed.append(Change(entry=_entry(key, records[key], names), fields=fields))
    return changes


def for_dataset(changes: Changes, repo: str) -> Changes:
    """種別 1 つぶんに絞った差分。

    **差分の計算は全体で 1 回だけ**行い、種別ごとのリリースノートはここで切り出す。
    種別ごとに前回の配布物を取りに行くと、10 回同じ突き合わせをすることになる
    うえ、どれか 1 つが取れなかった月に基準がばらける。
    """
    return Changes(
        baseline=changes.baseline,
        datasets=[dataset for dataset in changes.datasets if dataset.repo == repo],
        added=[entry for entry in changes.added if entry.dataset == repo],
        removed=[entry for entry in changes.removed if entry.dataset == repo],
        changed=[change for change in changes.changed if change.entry.dataset == repo],
        datasets_added=[name for name in changes.datasets_added if name == repo],
        datasets_removed=[name for name in changes.datasets_removed if name == repo],
    )


def write(changes: Changes, out_dir: Path, *, archive: str = ARCHIVE_NAME) -> None:
    """種別横断の `changes.json` / `changes.md` / `notes.md` を書く。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / CHANGES_JSON).write_text(
        json.dumps(as_payload(changes), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / CHANGES_MARKDOWN).write_text(as_markdown(changes), encoding="utf-8")
    (out_dir / NOTES_MARKDOWN).write_text(
        as_notes(changes, archive=archive, cross_type=True), encoding="utf-8"
    )


def write_for_dataset(changes: Changes, out_dir: Path, *, repo: str, archive: str) -> Changes:
    """種別 1 つぶんの `changes.md` / `notes.md` を書き、切り出した差分を返す。

    `changes.md` も添えるのは、ノートが「全量は `changes.md`」と案内するため。
    案内先がそのリリースに無いと、読み手は全量に辿り着けない。
    """
    only = for_dataset(changes, repo)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / CHANGES_MARKDOWN).write_text(as_markdown(only), encoding="utf-8")
    (out_dir / NOTES_MARKDOWN).write_text(
        as_notes(only, archive=archive, cross_type=False), encoding="utf-8"
    )
    return only


def as_payload(changes: Changes) -> dict[str, Any]:
    """機械可読の全量。**長文も前後を落とさずに入れる。**"""
    return {
        "schema_version": CHANGES_SCHEMA_VERSION,
        "baseline": changes.baseline,
        "has_changes": changes.has_changes,
        "accessed_date": changes.accessed_date,
        "totals": {
            "records": changes.records,
            "added": len(changes.added),
            "removed": len(changes.removed),
            "changed": len(changes.changed),
        },
        # **種別ごとの件数もここに入れる。** 各データリポジトリへリリースを作るかを
        # ワークフローがこれ 1 つで決められるようにする (10 個のノートを読み直さない)。
        "datasets": [
            _dataset_payload(changes, dataset) for dataset in changes.datasets
        ],
        "datasets_added": changes.datasets_added,
        "datasets_removed": changes.datasets_removed,
        "added": [_entry_payload(entry) for entry in changes.added],
        "removed": [_entry_payload(entry) for entry in changes.removed],
        "changed": [
            {
                **_entry_payload(change.entry),
                "fields": [
                    {
                        "key": item.key,
                        "label": item.label,
                        "before": item.before,
                        "after": item.after,
                    }
                    for item in change.fields
                ],
            }
            for change in changes.changed
        ],
    }


def _dataset_payload(changes: Changes, dataset: DatasetSummary) -> dict[str, Any]:
    only = for_dataset(changes, dataset.repo)
    return {
        "repo": dataset.repo,
        "name": dataset.name,
        "records": dataset.records,
        "accessed_date": dataset.accessed_date,
        "has_changes": only.has_changes,
        "added": len(only.added),
        "removed": len(only.removed),
        "changed": len(only.changed),
    }


def as_markdown(changes: Changes) -> str:
    """人が読む全量。**件数で切らない** — 切ったぶんの行き先がここなので。"""
    lines = ["# 変更の全量", ""]
    lines += _summary_lines(changes)
    if not changes.baseline:
        lines += _sections(changes, limit=None)
    return "\n".join(lines) + "\n"


def as_notes(changes: Changes, *, archive: str = ARCHIVE_NAME, cross_type: bool = True) -> str:
    """リリースノートの本文。**件数で切り、全量は `changes.md` へ送る。**"""
    lines = _summary_lines(changes)
    if not changes.baseline:
        lines += _sections(changes, limit=NOTE_EXAMPLES)
    lines += ["## 中身", ""]
    if cross_type:
        lines += [
            f"`{archive}` に種別ごとの JSON Lines と `meta.json`、"
            "目録の `MANIFEST.json` が入っています。",
            "1 行の形は各データリポジトリの README にあります。",
        ]
    else:
        lines += [
            f"`{archive}` を展開すると、このリポジトリの中身 (`data/` の JSON Lines と"
            " `meta.json`) がそのまま出ます。目録は `MANIFEST.json`、1 行の形は"
            " README にあります。",
            "",
            f"種別をまたいで扱うなら、全部入りが[こちら]({CROSS_TYPE_RELEASES})にあります。",
        ]
    lines += [
        "",
        "```",
        "出典：「国指定文化財等データベース」（文化庁）",
        f"（https://kunishitei.bunka.go.jp/）（{_japanese_date(changes.accessed_date)}に利用）",
        "上記を加工して作成",
        "```",
        "",
        "データは文化庁「国指定文化財等データベース」の利用規約に従います。"
        "**画像は含みません。**",
    ]
    return "\n".join(lines) + "\n"


def _sections(changes: Changes, *, limit: int | None) -> list[str]:
    return [
        *_section("追加された指定", [_entry_line(entry) for entry in changes.added], limit=limit),
        *_section(
            "指定から外れたもの", [_entry_line(entry) for entry in changes.removed], limit=limit
        ),
        *_section(
            "内容が変わったもの", [_change_line(change) for change in changes.changed], limit=limit
        ),
    ]


def _read(
    datasets: list[Dataset],
) -> tuple[list[DatasetSummary], dict[tuple[str, str, str], dict[str, Any]], dict[str, Any]]:
    """データセット群を読み、要約・キーで引ける行・項目のラベルにほどく。"""
    summaries: list[DatasetSummary] = []
    records: dict[tuple[str, str, str], dict[str, Any]] = {}
    labels: dict[str, Any] = {}
    for dataset in datasets:
        count = 0
        for record in iter_records(dataset):
            records[record.key] = record.values
            count += 1
        summaries.append(
            DatasetSummary(
                repo=dataset.repo,
                name=dataset.name,
                records=count,
                accessed_date=dataset.accessed_date,
            )
        )
        meta_labels = dataset.meta.get("labels")
        labels[dataset.repo] = meta_labels if isinstance(meta_labels, dict) else {}
    return summaries, records, labels


def _compare_values(
    before: dict[str, Any], after: dict[str, Any], labels: dict[str, Any]
) -> tuple[FieldChange, ...]:
    """行 1 つぶんの項目を比べる。

    並びは `meta.json` の `labels` の順にする。あれはスキーマの正本
    (クローラーの `record.py` の `FIELD_KEYS`) の並びで書かれているので、報告も
    原文の項目の並びで読める。ラベルに無いキーは後ろへ回す。
    """
    order = {key: index for index, key in enumerate(labels)}
    keys = sorted(set(before) | set(after), key=lambda key: (order.get(key, len(order)), key))
    return tuple(
        FieldChange(
            key=key,
            label=str(labels.get(key, key)),
            before=before.get(key),
            after=after.get(key),
        )
        for key in keys
        if before.get(key) != after.get(key)
    )


def _entry(key: tuple[str, str, str], values: dict[str, Any], names: dict[str, str]) -> Entry:
    repo = key[0]
    return Entry(
        dataset=repo,
        dataset_name=names.get(repo, repo),
        ledger_id=key[1],
        managed_id=key[2],
        name=_text(values.get("name")) or "(名称なし)",
        address=_text(values.get("address")),
        url=_text(values.get("url")),
    )


def _entry_payload(entry: Entry) -> dict[str, Any]:
    return {
        "dataset": entry.dataset,
        "dataset_name": entry.dataset_name,
        "ledger_id": entry.ledger_id,
        "managed_id": entry.managed_id,
        "name": entry.name,
        "address": entry.address,
        "url": entry.url,
    }


def _summary_lines(changes: Changes) -> list[str]:
    if changes.baseline:
        lines = [
            f"初回のリリースです。**{changes.records:,} 行** / {len(changes.datasets)} 種別。",
            "",
            "| 種別 | 件数 |",
            "|---|---:|",
        ]
        lines += [
            f"| {dataset.name} | {dataset.records:,} |"
            for dataset in sorted(changes.datasets, key=lambda item: -item.records)
        ]
        lines += [f"| **合計** | **{changes.records:,}** |", ""]
        return lines

    lines = [
        f"前回の配布物から、**追加 {len(changes.added):,} 件 / "
        f"削除 {len(changes.removed):,} 件 / 変更 {len(changes.changed):,} 件**の"
        f"差分があります (全 {changes.records:,} 行)。",
        "",
    ]
    counts = changes.counts_by_dataset()
    if counts:
        lines += ["| 種別 | 追加 | 削除 | 変更 |", "|---|---:|---:|---:|"]
        lines += [
            f"| {name} | {added:,} | {removed:,} | {changed:,} |"
            for name, (added, removed, changed) in sorted(counts.items())
        ]
        lines += [
            f"| **合計** | **{len(changes.added):,}** | **{len(changes.removed):,}** | "
            f"**{len(changes.changed):,}** |",
            "",
        ]
    if changes.datasets_added:
        lines += [f"種別が増えました: {'・'.join(changes.datasets_added)}", ""]
    if changes.datasets_removed:
        lines += [f"種別が無くなりました: {'・'.join(changes.datasets_removed)}", ""]
    return lines


def _section(title: str, lines: list[str], *, limit: int | None) -> list[str]:
    if not lines:
        return []
    shown = lines if limit is None else lines[:limit]
    out = [f"## {title} ({len(lines):,} 件)", "", *shown]
    if limit is not None and len(lines) > limit:
        out.append(f"- ほか {len(lines) - limit:,} 件 (全量は `{CHANGES_MARKDOWN}`)")
    out.append("")
    return out


def _entry_line(entry: Entry) -> str:
    where = f" — {entry.address}" if entry.address else ""
    link = f" ([原本]({entry.url}))" if entry.url else ""
    return f"- **{entry.name}** ({entry.dataset_name}){where}{link}"


def _change_line(change: Change) -> str:
    summary = "、".join(item.summary() for item in change.fields)
    return f"{_entry_line(change.entry)}\n  - {summary}"


def _display(value: Any) -> str:
    """値を 1 行に収める。配列は原文の並びのまま繋ぐ。"""
    if isinstance(value, list):
        return "・".join(_text(item) for item in value)
    text = _text(value)
    return text if text else "(なし)"


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


def _japanese_date(value: str) -> str:
    """`2026-08-12` を `2026年8月12日` に。出典表記の体裁に合わせる。"""
    parts = value.split("-")
    if len(parts) != 3:
        return value
    year, month, day = parts
    return f"{int(year)}年{int(month)}月{int(day)}日"
