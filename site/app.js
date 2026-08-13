// 索引を読んで画面を組み立てる。
//
// バンドラは使わない (ADR 0015 で決めた「生成物をコミットしない」に、素の ESM が
// そのまま乗る)。データの取得はすべて相対パスにして、Pages のベースパスに
// 依存させない。
//
// 読むものは 2 つ。データセットの索引 (index.json・16 KB) と行の索引
// (records.json・約 1.3 MB)。**別々に読んで、先に届いた方から描く** — 件数と
// 利用日の表は軽いので、一覧の読み込みを待たせない。

import { createBrowser } from "./browse.js";
import { createCatalog, fetchRecords } from "./records.js";

const INDEX_URL = "./index.json";

// ビルドが書く索引のスキーマ版 (build.py の SITE_SCHEMA_VERSION)。
// 食い違ったまま描くと画面のどこかが黙って空になるので、先に止める。
const SUPPORTED_SCHEMA_VERSION = 1;

const NUMBER_FORMAT = new Intl.NumberFormat("ja-JP");

main();

async function main() {
  let index;
  try {
    index = await fetchIndex();
    render(index);
  } catch (error) {
    showError("error", error);
    return;
  }
  try {
    const payload = await fetchRecords();
    await startBrowsing(payload, datasetLabels(index));
  } catch (error) {
    showError("browse-error", error);
  }
}

async function fetchIndex() {
  const response = await fetch(INDEX_URL);
  if (!response.ok) {
    throw new Error(`索引を読めませんでした (HTTP ${response.status})`);
  }
  const index = await response.json();
  if (index.schema_version !== SUPPORTED_SCHEMA_VERSION) {
    throw new Error(
      `索引のスキーマ版 ${index.schema_version} にこのページは対応していません` +
        ` (対応: ${SUPPORTED_SCHEMA_VERSION})`,
    );
  }
  return index;
}

function render(index) {
  renderSummary(index);
  renderDatasets(index.datasets);
  renderAttribution(index.datasets);
}

// 種別の呼び名の正本は meta.json (ADR 0014)。行の索引はリポジトリ名しか
// 持たないので、表示名はこちらから渡す。
function datasetLabels(index) {
  return Object.fromEntries(
    index.datasets.map(({ repo, meta }) => [repo, meta.dataset?.name ?? repo]),
  );
}

async function startBrowsing(payload, labels) {
  const catalog = createCatalog(payload, labels);
  document.getElementById("browse-loading").hidden = true;
  // 地図は自分の大きさを容れ物から測るので、先に見える状態にしておく。
  document.getElementById("browse").hidden = false;
  const map = await startMap(catalog);
  createBrowser(
    catalog,
    {
      search: document.getElementById("search"),
      reset: document.getElementById("reset"),
      facets: document.getElementById("facets"),
      count: document.getElementById("result-count"),
      list: document.getElementById("results"),
      more: document.getElementById("more"),
      empty: document.getElementById("no-results"),
    },
    // 絞り込むたびに地図へ渡す。地図が組み立てられなかったときは渡す先が無い。
    { onResults: (matched) => map?.show(matched) },
  );
}

// 地図だけ**動的に読む**。同梱した地図ライブラリ (ADR 0016) は 400 KB を超え、
// 読めなかったときに一覧まで道連れにしたくない — 地図に位置を持たない行への
// 配慮も、キーボードだけで使える経路も、一覧が生きていることが前提になる。
async function startMap(catalog) {
  try {
    const { createMapView } = await import("./map.js");
    return createMapView(catalog, {
      map: document.getElementById("map"),
      tiles: document.getElementById("map-tiles"),
      summary: document.getElementById("map-summary"),
    });
  } catch (error) {
    const failed = document.getElementById("map-error");
    failed.textContent = `地図を表示できませんでした: ${error.message} (一覧はそのまま使えます)`;
    failed.hidden = false;
    // 地図が出ないなら、地図の出典と種類の選択も出す意味が無い。
    document.getElementById("map-frame").hidden = true;
    document.getElementById("map-tiles-field").hidden = true;
    return null;
  }
}

function renderSummary({ totals, accessed_dates: accessed, datasets }) {
  const parts = [
    `${datasets.length} 種別 / ${NUMBER_FORMAT.format(totals.records)} 行`,
    `異なり ${NUMBER_FORMAT.format(totals.distinct)} 件`,
  ];
  if (totals.shared > 0) {
    // 同じ棟が複数の種別に現れる複合指定。種別ごとのサイトでは表せなかったもの (ADR 0015)。
    parts.push(`うち ${NUMBER_FORMAT.format(totals.shared)} 件は複数の種別に現れます`);
  }
  parts.push(`利用日 ${formatAccessed(accessed)}`);
  document.getElementById("summary").textContent = parts.join(" / ");
}

function renderDatasets(datasets) {
  const body = document.getElementById("datasets-body");
  body.replaceChildren(
    ...datasets.map(({ meta }) =>
      row([
        cell(meta.dataset?.name ?? "", { scope: "row" }),
        cell(meta.dataset?.category?.name ?? ""),
        cell(NUMBER_FORMAT.format(meta.counts?.records ?? 0), { numeric: true }),
        cell(NUMBER_FORMAT.format(meta.counts?.with_coordinates ?? 0), { numeric: true }),
        cell(meta.source?.accessed_date ?? ""),
      ]),
    ),
  );
}

// 出典表記は meta.json が持つ文言をそのまま出す。サイト側で書き起こすと、
// 利用日が変わっても文言だけ古いままになる (ADR 0014)。
function renderAttribution(datasets) {
  const texts = [...new Set(datasets.map(({ meta }) => meta.source?.attribution).filter(Boolean))];
  const container = document.getElementById("attribution");
  container.replaceChildren(
    ...texts.map((text) => {
      const paragraph = document.createElement("p");
      paragraph.className = "attribution";
      paragraph.textContent = text;
      return paragraph;
    }),
  );
}

function formatAccessed({ oldest, newest } = {}) {
  if (!oldest) return "不明";
  return oldest === newest ? oldest : `${oldest}〜${newest}`;
}

function row(cells) {
  const element = document.createElement("tr");
  element.replaceChildren(...cells);
  return element;
}

function cell(text, { scope, numeric } = {}) {
  const element = document.createElement(scope ? "th" : "td");
  if (scope) element.scope = scope;
  if (numeric) element.className = "numeric";
  element.textContent = text;
  return element;
}

function showError(id, error) {
  const element = document.getElementById(id);
  element.textContent = `データを表示できませんでした: ${error.message}`;
  element.hidden = false;
  if (id === "error") document.getElementById("summary").textContent = "";
  if (id === "browse-error") document.getElementById("browse-loading").hidden = true;
}
