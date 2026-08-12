// 行の索引 (records.json) を読み、検索とファセットで絞り込む。
//
// 描画はここではしない (browse.js の担当)。**画面を持たないぶんだけ、
// 絞り込みの決まりごとがここに集まる**。
//
// - 検索は正規化した 1 本の文字列への部分一致 (normalize.js)
// - **軸の中は OR、軸をまたぐと AND**。「京都府 か 奈良県」で「国宝」のもの
// - 値ごとの件数は**その軸を除いた絞り込み**で数える。自分の軸まで含めて
//   数えると、1 つ選んだ瞬間に他の値が全部 0 件になって選び直せなくなる

import { normalize } from "./normalize.js";

const RECORDS_URL = "./records.json";

// ビルドが書く索引のスキーマ版 (build.py の SITE_SCHEMA_VERSION)。
const SUPPORTED_SCHEMA_VERSION = 1;

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

// 索引を絞り込める形にする。`datasetLabels` は index.json 由来の表示名で、
// 索引が持つのはリポジトリ名だけ (呼び名の正本は meta.json)。
export function createCatalog(payload, datasetLabels = {}) {
  const column = Object.fromEntries(payload.fields.map((field, index) => [field, index]));
  const records = payload.records;

  const axes = [
    {
      key: DATASET_AXIS_KEY,
      label: DATASET_AXIS_LABEL,
      values: payload.datasets.map((repo) => datasetLabels[repo] ?? repo),
      // データセットは 1 行に 1 つ。列の値がそのまま語彙の番号になっている。
      valuesOf: (record) => [record[column.dataset]],
    },
    ...payload.axes.map((axis, position) => ({
      key: axis.key,
      label: axis.label,
      values: axis.values,
      // 軸によっては 1 行が複数の値を持つ (401 の複合指定など)。
      valuesOf: (record) => record[column.facets][position],
    })),
  ];

  return {
    axes,
    total: records.length,
    record: (index) => describe(records[index], column, payload.datasets, datasetLabels),
    filter: (query, selection) => filter(records, axes, column.search, query, selection),
  };
}

function describe(record, column, repos, datasetLabels) {
  const repo = repos[record[column.dataset]];
  return {
    dataset: datasetLabels[repo] ?? repo,
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
