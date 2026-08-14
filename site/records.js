// 行の索引 (records.json) を読み、検索とファセットで絞り込む。
//
// 描画はここではしない (browse.js の担当)。**画面を持たないぶんだけ、
// 絞り込みの決まりごとがここに集まる**。
//
// - 検索は正規化した 1 本の文字列への部分一致 (normalize.js)
// - **軸の中は OR、軸をまたぐと AND**。「京都府 か 奈良県」で「国宝」のもの
// - 値ごとの件数は**その軸を除いた絞り込み**で数える。自分の軸まで含めて
//   数えると、1 つ選んだ瞬間に他の値が全部 0 件になって選び直せなくなる

import { createRecordSource, fieldsOf } from "./detail.js";
import { normalize } from "./normalize.js";

const RECORDS_URL = "./records.json";

// ビルドが書く索引のスキーマ版 (build.py の SITE_SCHEMA_VERSION)。
const SUPPORTED_SCHEMA_VERSION = 4;

// データセット (種別) は絞り込みの主軸だが、meta.json の facets には出てこない。
// 種別横断のサイトなので、ここだけは索引の datasets から軸を作る。
const DATASET_AXIS_KEY = "dataset";
const DATASET_AXIS_LABEL = "データセット";

export async function fetchRecords() {
  const response = await fetch(RECORDS_URL);
  if (!response.ok) {
    throw new Error(`行の索引を読めませんでした (HTTP ${response.status})`);
  }
  const payload = await response.json();
  if (payload.schema_version !== SUPPORTED_SCHEMA_VERSION) {
    throw new Error(
      `行の索引のスキーマ版 ${payload.schema_version} にこのページは対応していません` +
        ` (対応: ${SUPPORTED_SCHEMA_VERSION})`,
    );
  }
  return payload;
}

// 索引を絞り込める形にする。`datasets` は index.json のデータセット
// (`{ repo, path, meta }`) で、索引が持つのはリポジトリ名だけ — 呼び名も項目の
// 呼び名も置き場も、正本は meta.json の側にある (ADR 0014)。
export function createCatalog(payload, datasets = [], { source = createRecordSource() } = {}) {
  const column = Object.fromEntries(payload.fields.map((field, index) => [field, index]));
  const records = payload.records;
  const info = new Map(
    datasets.map(({ repo, path, meta }) => [
      repo,
      { name: meta?.dataset?.name ?? repo, path, labels: meta?.labels ?? {} },
    ]),
  );
  // 複合指定 (同じ棟が複数の種別に現れる) の相手。**要るまで作らない** —
  // 2 万行を数える手間を、詳細を 1 件も開かない読み手に払わせない。
  let shared = null;

  const axes = [
    {
      key: DATASET_AXIS_KEY,
      label: DATASET_AXIS_LABEL,
      // データセットそのものが体系なので、まとめる先はない (Issue #8)。
      groups: [],
      values: payload.datasets.map((repo) => info.get(repo)?.name ?? repo),
      // データセットは 1 行に 1 つ。列の値がそのまま語彙の番号になっている。
      valuesOf: (record) => [record[column.dataset]],
    },
    ...payload.axes.map((axis, position) => ({
      key: axis.key,
      label: axis.label,
      // 並びの根拠 (count / period / area)。畳み方の判断に画面が使う。
      order: axis.order,
      // 体系ごとのまとまり (Issue #8)。**横断の軸では空**。値の並びの先頭から
      // `size` ずつ区切る。
      groups: axis.groups ?? [],
      values: axis.values,
      // 軸によっては 1 行が複数の値を持つ (401 の複合指定など)。
      valuesOf: (record) => record[column.facets][position],
    })),
  ];

  // 同じ `(台帳ID, 管理対象ID)` を持つ行が、どのデータセットに現れるか。
  // 102 は 1 指定が複数の棟に展開されるので、同じ種別の中にも同じキーが並ぶ。
  function siblingsOf(record) {
    if (!shared) {
      shared = new Map();
      for (const other of records) {
        const key = `${other[column.ledger_id]}\n${other[column.managed_id]}`;
        const found = shared.get(key);
        if (found) found.add(other[column.dataset]);
        else shared.set(key, new Set([other[column.dataset]]));
      }
    }
    const key = `${record[column.ledger_id]}\n${record[column.managed_id]}`;
    return [...(shared.get(key) ?? [])]
      .filter((number) => number !== record[column.dataset])
      .map((number) => {
        const repo = payload.datasets[number];
        return info.get(repo)?.name ?? repo;
      });
  }

  // 元の行の置き場。索引が持つのは番号だけで、ファイル名は `files` が持つ。
  function sourceOf(record) {
    const repo = payload.datasets[record[column.dataset]];
    const path = info.get(repo)?.path;
    const file = payload.files?.[record[column.dataset]]?.[record[column.file]];
    if (!path || !file) return null;
    return { url: `./${path}/${file}`, line: record[column.line] };
  }

  return {
    axes,
    total: records.length,
    coordinates: coordinatesOf(records, column),
    record: (index) => describe(records[index], column, payload.datasets, info, siblingsOf),
    // 元の行を読んで、並べられる形の項目にして返す。**開かれたときだけ呼ぶ**。
    detail: async (index) => {
      const record = records[index];
      const place = sourceOf(record);
      if (!place) throw new Error("元のデータの置き場が索引に無い");
      const repo = payload.datasets[record[column.dataset]];
      return fieldsOf(await source.read(place), info.get(repo)?.labels ?? {});
    },
    filter: (query, selection) => filter(records, axes, column.search, query, selection),
  };
}

// 地図が読む座標。行ごとにオブジェクトを引かずに済むよう、列ごとの数値の並びで
// 渡す (2 万行を毎回なぞるため)。
//
// **地図に置けない行は `NaN`。**索引では `null` で来るが、そのまま数値の並びに
// 入れると 0 になり、アフリカ沖 (緯度 0・経度 0) に点が立つ。
function coordinatesOf(records, column) {
  return {
    latitudes: Float64Array.from(records, (record) => record[column.latitude] ?? NaN),
    longitudes: Float64Array.from(records, (record) => record[column.longitude] ?? NaN),
  };
}

function describe(record, column, repos, info, siblingsOf) {
  const repo = repos[record[column.dataset]];
  return {
    dataset: info.get(repo)?.name ?? repo,
    // 同じ棟が現れる他の種別 (ADR 0012)。種別ごとのサイトでは表せなかったもの。
    // **読まれたときに数える** — 一覧に 200 件並べるたびに 2 万行を数えない。
    get siblings() {
      return siblingsOf(record);
    },
    ledgerId: record[column.ledger_id],
    managedId: record[column.managed_id],
    name: record[column.name],
    ridgeName: record[column.ridge_name],
    address: record[column.address],
    designatedYear: record[column.designated_year],
    url: record[column.url],
    latitude: record[column.latitude],
    longitude: record[column.longitude],
    // 座標は「地図に置けるもの」だけが入っている。無い行は一覧にだけ出す
    // (黙って落とさない — Issue #32 §3)。
    mappable: record[column.latitude] !== null && record[column.longitude] !== null,
  };
}

function filter(records, axes, searchColumn, query, selection) {
  const needle = normalize(query ?? "");
  const matched = [];
  const counts = axes.map((axis) => new Array(axis.values.length).fill(0));
  const everyAxis = axes.map((_, position) => position);

  for (let index = 0; index < records.length; index += 1) {
    const record = records[index];
    if (needle && !record[searchColumn].includes(needle)) continue;

    // どの軸で落ちたかを覚えておく。落ちた軸が 1 つだけなら、その軸の件数には
    // 数える — 選び直せる状態を保つため。
    let failed = 0;
    let failedAxis = -1;
    for (let position = 0; position < axes.length; position += 1) {
      const chosen = selection[axes[position].key];
      if (!chosen || chosen.size === 0) continue;
      if (!axes[position].valuesOf(record).some((value) => chosen.has(value))) {
        failed += 1;
        failedAxis = position;
        if (failed > 1) break;
      }
    }
    // 2 つ以上の軸で落ちた行は、どの軸から見ても選べない。件数にも数えない。
    if (failed > 1) continue;
    if (failed === 0) matched.push(index);
    const counted = failed === 1 ? [failedAxis] : everyAxis;
    for (const position of counted) {
      for (const value of axes[position].valuesOf(record)) counts[position][value] += 1;
    }
  }
  return { matched, counts };
}
