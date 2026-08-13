// 1 行が持っている項目を**すべて**見せる (Issue #32 §4)。
//
// 索引 (records.json) に入っているのは一覧と地図に要る項目だけで、解説文も員数も
// 構造及び形式等も入っていない。**残りは JSON Lines をその場で読む** — サイトが
// 配っているのはデータリポジトリのあの行そのものなので (ADR 0015)、索引に写しを
// 増やすと同じ事実を 2 か所に持つことになる。
//
// 読みに行くのは開かれたときだけ、単位は県ごとのファイル 1 つ。同じファイルの別の
// 行を開いても 2 度は取りに行かない (最大 1.1 MB のファイルがある)。
//
// **項目の並びと呼び名は `meta.json` の `labels`** (ADR 0014)。サイトに項目の表を
// 持たないので、種別ごとに項目が違っても・上流に項目が増えても手を入れずに済む。

// 「あり」とだけ言われても行き先が分からない項目。実体は持てないので (ADR 0007)、
// 原本のページへ繋ぐ。
const ORIGINAL_ONLY_FLAGS = new Set(["has_photo", "has_attachment"]);

// 配列の中の値を 1 つの升目に収めるときの区切り (異動種別など)。原文の区切りが
// 読点なので、混ざらない記号にする。
const CELL_SEPARATOR = " / ";

// 元の行を読む。`url` ごとに読み込みを覚えるので、同じファイルの行を続けて開いても
// 取りに行くのは 1 度きり。
export function createRecordSource({ load = fetchLines } = {}) {
  const files = new Map();
  return {
    async read({ url, line }) {
      let lines = files.get(url);
      if (!lines) {
        lines = load(url);
        // 失敗した読み込みは覚えない (開き直せば取りに行ける)。
        lines.catch(() => files.delete(url));
        files.set(url, lines);
      }
      const raw = (await lines)[line - 1];
      if (raw === undefined || !raw.trim()) {
        throw new Error(`元の行が見つかりませんでした (${url}:${line})`);
      }
      return JSON.parse(raw);
    },
  };
}

async function fetchLines(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`元のデータを読めませんでした (HTTP ${response.status})`);
  }
  // 行番号はビルド側が数えた「ファイルの N 行目」。空行も 1 行として数えるので、
  // ここでも詰めずに分ける。
  return (await response.text()).split("\n");
}

// 行を「並べられる項目」に開く。**画面を持たないので node から確かめられる**
// (tests/test_detail.py)。
//
// 並びは `labels` の順、そこに無いキーは後ろへ回す — **知らない項目でも落とさない**。
// 上流に項目が増えたときに、黙って消えるより名前のまま出る方がよい。
export function fieldsOf(record, labels = {}) {
  if (!record || typeof record !== "object") return [];
  const known = Object.keys(labels).filter((key) => !key.includes("."));
  const rest = Object.keys(record).filter((key) => !(key in labels));
  return [...known, ...rest]
    .filter((key) => present(record[key]))
    .map((key) => field(key, record[key], labels));
}

// キーが無い = 値なし (`null` は来ない)。空文字と空の配列も「値なし」として扱う。
function present(value) {
  if (value === undefined || value === null || value === "") return false;
  return !(Array.isArray(value) && value.length === 0);
}

function field(key, value, labels) {
  const label = labels[key] ?? key;
  if (typeof value === "boolean") {
    return { key, label, kind: "flag", value, original: ORIGINAL_ONLY_FLAGS.has(key) && value };
  }
  if (typeof value === "number") {
    return { key, label, kind: "number", value: String(value) };
  }
  if (Array.isArray(value)) {
    return value.some((item) => item && typeof item === "object")
      ? table(key, value, labels)
      : { key, label, kind: "list", values: value.map(text) };
  }
  const string = text(value);
  if (/^https?:\/\//.test(string)) return { key, label, kind: "link", value: string };
  return { key, label, kind: "text", value: string };
}

// 附指定 (`附名称` / `附員数`) や指定等後の措置 (`異動年月日` / `異動種別`) のような、
// 組の並び。列は現れた順に増やす — 行によって持つ項目が違っても落とさない。
function table(key, items, labels) {
  const columns = [];
  const rows = items.map((item) => {
    const entry = item && typeof item === "object" ? item : { "": item };
    for (const column of Object.keys(entry)) {
      if (!columns.includes(column)) columns.push(column);
    }
    return entry;
  });
  return {
    key,
    label: labels[key] ?? key,
    kind: "table",
    // 組の中の呼び名は `labels` が `<キー>.<項目>` で持つ (ADR 0014)。
    columns: columns.map((column) => ({
      key: column,
      label: labels[`${key}.${column}`] ?? column,
    })),
    rows: rows.map((entry) => columns.map((column) => text(entry[column]))),
  };
}

function text(value) {
  if (value === undefined || value === null) return "";
  if (Array.isArray(value)) return value.map(text).join(CELL_SEPARATOR);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

// 一覧と地図の吹き出しに置く折りたたみ。**開かれるまで読みに行かない**ので、
// 200 件を描くだけで 200 ファイルを取りに行くことはない。
//
// `load` は元の行の項目を約束する関数 (records.js の `catalog.detail`)。
// `onChange` は中身の大きさが変わったときに呼ぶ — 自分の大きさを測って場所を
// 決める容れ物 (地図の吹き出し) に、測り直す機会を渡すため。
export function createDetailBlock(record, load, { onChange } = {}) {
  const block = document.createElement("details");
  block.className = "record-detail";

  const summary = document.createElement("summary");
  summary.textContent = "すべての項目を見る";

  const body = document.createElement("div");
  body.className = "detail-body";

  block.append(summary, body);

  let loaded = false;
  block.addEventListener("toggle", () => {
    onChange?.();
    if (!block.open || loaded) return;
    loaded = true;
    body.textContent = "読み込んでいます…";
    load()
      .then((fields) => body.replaceChildren(...describe(record, fields)))
      .catch((error) => {
        // 覚えないので、閉じて開き直せばもう一度取りに行く。
        loaded = false;
        body.replaceChildren(message(`項目を読めませんでした: ${error.message}`, "error"));
      })
      .finally(() => onChange?.());
  });
  return block;
}

function describe(record, fields) {
  const parts = [];
  // 同じ棟が複数の種別に現れる複合指定 (ADR 0012)。種別ごとのサイトでは表せず、
  // 1 つのサイトに束ねた理由そのものなので、詳細では必ず併記する。
  if (record.siblings?.length) {
    parts.push(message(`この棟は「${record.siblings.join("」「")}」にも入っています`, "siblings"));
  }
  parts.push(fieldList(fields));
  return parts;
}

function fieldList(fields) {
  const list = document.createElement("dl");
  list.className = "detail-fields";
  for (const entry of fields) {
    const term = document.createElement("dt");
    term.textContent = entry.label;
    const definition = document.createElement("dd");
    definition.append(valueOf(entry));
    list.append(term, definition);
  }
  return list;
}

function valueOf(field) {
  if (field.kind === "list") return bullets(field.values);
  if (field.kind === "table") return grid(field);
  if (field.kind === "link") return link(field.value);
  if (field.kind === "flag") return flag(field);
  return document.createTextNode(field.value);
}

function bullets(values) {
  const list = document.createElement("ul");
  list.className = "detail-list";
  list.append(
    ...values.map((value) => {
      const item = document.createElement("li");
      item.textContent = value;
      return item;
    }),
  );
  return list;
}

function grid({ columns, rows }) {
  const table = document.createElement("table");
  table.className = "detail-table";
  const head = document.createElement("tr");
  head.append(
    ...columns.map((column) => {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = column.label;
      return cell;
    }),
  );
  const body = document.createElement("tbody");
  body.append(
    ...rows.map((values) => {
      const row = document.createElement("tr");
      row.append(
        ...values.map((value) => {
          const cell = document.createElement("td");
          cell.textContent = value;
          return cell;
        }),
      );
      return row;
    }),
  );
  const header = document.createElement("thead");
  header.append(head);
  table.append(header, body);
  return table;
}

function link(url) {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.rel = "noopener noreferrer";
  anchor.target = "_blank";
  anchor.textContent = url;
  return anchor;
}

function flag(field) {
  const fragment = document.createDocumentFragment();
  fragment.append(field.value ? "あり" : "なし");
  // 写真も添付ファイルも実体は持てない (ADR 0007)。あると言うだけで終わらせず、
  // 見られる場所へ繋ぐ。
  if (field.original) {
    const note = document.createElement("span");
    note.className = "detail-note";
    note.textContent = "（詳細ページで見られます）";
    fragment.append(" ", note);
  }
  return fragment;
}

function message(content, className) {
  const paragraph = document.createElement("p");
  paragraph.className = `detail-${className}`;
  paragraph.textContent = content;
  return paragraph;
}
