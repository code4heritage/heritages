// 索引を読んでデータセットの一覧を描く。
//
// バンドラは使わない (ADR 0015 で決めた「生成物をコミットしない」に、素の ESM が
// そのまま乗る)。データの取得はすべて相対パスにして、Pages のベースパスに
// 依存させない。

const INDEX_URL = "./index.json";

// ビルドが書く索引のスキーマ版 (build.py の SITE_SCHEMA_VERSION)。
// 食い違ったまま描くと画面のどこかが黙って空になるので、先に止める。
const SUPPORTED_SCHEMA_VERSION = 1;

const NUMBER_FORMAT = new Intl.NumberFormat("ja-JP");

main();

async function main() {
  try {
    const index = await fetchIndex();
    render(index);
  } catch (error) {
    showError(error);
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

function showError(error) {
  document.getElementById("summary").textContent = "";
  const element = document.getElementById("error");
  element.textContent = `データを表示できませんでした: ${error.message}`;
  element.hidden = false;
}
