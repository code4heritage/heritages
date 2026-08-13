// 検索・ファセット・一覧の画面 (Issue #32 §2)。
//
// 素の input / checkbox / button だけで組み立てる。**キーボードだけで
// 使えること**は地図に依存しない経路の保証でもあり、地図に位置を持たない
// 373 行への配慮でもある。
//
// 仮想スクロールは入れない。一覧は先頭 200 件を描き、「さらに 200 件」で伸ばす。

import { createDetailBlock } from "./detail.js";

const PAGE_SIZE = 200;

// 軸ごとに最初から見せる値の数。時代は 211 値あるので、全部並べると
// 一覧より facet の方が長くなる。
const VISIBLE_VALUES = 10;

// **地域の軸だけは切らない** (Issue #7)。並びが総務省の都道府県コード順なので、
// 上位 10 値で切ると見えるのは「北海道〜栃木県」だけになり、探したい県に
// たどり着けない (上位 10 値が覆うのは全体の 41%)。47 値なら全部並べても
// 一覧を押しのけない。
const UNTRUNCATED_ORDER = "area";

// 軸ごとに、最初から見せる値の数。**描画は DOM が要るが、この規則は要らない**ので
// 切り出しておく (tests/test_browse.py が node から確かめる)。
export function visibleLimit(axis, expanded) {
  return expanded || axis.order === UNTRUNCATED_ORDER ? Infinity : VISIBLE_VALUES;
}

// 体系ごとの見出しでまとめる軸か (Issue #8)。
//
// 指定基準も種別も、**体系ごとに別の語彙が 1 本の軸に混ざっている** — 登録有形の
// 登録基準と天然記念物の指定基準が、番号の振り方すら違うまま 63 値並ぶ。どの値が
// どの体系かは索引の `groups` が持っていて (ビルドが行から測る)、**横断の軸では空**。
//
// ただし**最初から全部見える軸はそのまま**にする。3 値の「指定 / 登録 / 選定」も
// 体系に張り付いてはいるが、見出しを 3 つ足しても読む量が増えるだけで、値は
// はじめから全部見えている。
export function showsGroups(axis) {
  return (axis.groups?.length ?? 0) > 1 && axis.values.length > VISIBLE_VALUES;
}

const NUMBER_FORMAT = new Intl.NumberFormat("ja-JP");

// `onResults` は絞り込みの結果 (行番号の配列) を受け取る。地図はこれを見て
// 描き直す — **地図に別の絞り込みを持たせない**ので、一覧と地図に出るものが
// 食い違わない (Issue #32 §3)。
export function createBrowser(catalog, elements, { onResults } = {}) {
  const selection = Object.fromEntries(catalog.axes.map((axis) => [axis.key, new Set()]));
  const expanded = new Set();
  let query = "";
  let shown = PAGE_SIZE;

  const facets = renderFacets(catalog, elements.facets, {
    onToggle(axisKey, value, checked) {
      const chosen = selection[axisKey];
      if (checked) chosen.add(value);
      else chosen.delete(value);
      shown = PAGE_SIZE;
      update();
    },
    onExpand(axisKey) {
      expanded.add(axisKey);
      update();
    },
  });

  elements.search.addEventListener("input", () => {
    query = elements.search.value;
    shown = PAGE_SIZE;
    update();
  });

  elements.reset.addEventListener("click", () => {
    for (const chosen of Object.values(selection)) chosen.clear();
    elements.search.value = "";
    query = "";
    shown = PAGE_SIZE;
    update();
  });

  elements.more.addEventListener("click", () => {
    shown += PAGE_SIZE;
    update({ focusMore: true });
  });

  function update({ focusMore = false } = {}) {
    const { matched, counts } = catalog.filter(query, selection);
    facets.update(counts, selection, expanded);
    onResults?.(matched);
    renderSummary(elements.count, matched.length, Math.min(shown, matched.length), catalog.total);
    renderList(elements.list, catalog, matched.slice(0, shown));
    elements.more.hidden = matched.length <= shown;
    elements.more.textContent = `さらに ${NUMBER_FORMAT.format(
      Math.min(PAGE_SIZE, matched.length - shown),
    )} 件`;
    elements.empty.hidden = matched.length > 0;
    // 「さらに」を押し切ってボタンが消えると、キーボードの位置が行き場を失う。
    // 件数の見出しへ移す (aria-live で読み上げる先でもある)。
    if (focusMore && elements.more.hidden) elements.count.focus();
  }

  update();
  return { update };
}

function renderSummary(element, matched, shown, total) {
  const parts = [`${NUMBER_FORMAT.format(matched)} 件`];
  if (matched !== total) parts.push(`(全 ${NUMBER_FORMAT.format(total)} 件から)`);
  if (shown < matched) parts.push(`— 先頭 ${NUMBER_FORMAT.format(shown)} 件を表示`);
  element.textContent = parts.join(" ");
}

function renderFacets(catalog, container, handlers) {
  const groups = catalog.axes.map((axis) => {
    const group = document.createElement("details");
    group.className = "facet";
    // **体系ごとにまとめる軸は畳んでおく** (Issue #8)。指定基準の 63 値は
    // 体系が混ざったままでは読み解けないので、開いていても選べない。逆に
    // 横断の軸は開いておく — 所在都道府県はどの種別を見ていても同じ意味で効く。
    group.open = !showsGroups(axis);

    const summary = document.createElement("summary");
    const label = document.createElement("span");
    label.textContent = axis.label;
    const chosen = document.createElement("span");
    chosen.className = "facet-chosen";
    summary.append(label, chosen);

    const list = document.createElement("div");
    list.className = "facet-values";

    const more = document.createElement("button");
    more.type = "button";
    more.className = "facet-more";
    more.addEventListener("click", () => handlers.onExpand(axis.key));

    const sections = renderGroups(axis, list);
    // 値の番号から体系の番号を引く。まとめない軸では空のまま (値は list へ直接)。
    const sectionOf = sections.flatMap(({ size }, number) => Array(size).fill(number));

    const items = axis.values.map((value, number) => {
      const item = document.createElement("label");
      item.className = "facet-value";
      const input = document.createElement("input");
      input.type = "checkbox";
      input.addEventListener("change", () =>
        handlers.onToggle(axis.key, number, input.checked),
      );
      const text = document.createElement("span");
      text.className = "facet-label";
      text.textContent = value;
      const count = document.createElement("span");
      count.className = "facet-count";
      item.append(input, text, count);
      (sections[sectionOf[number]]?.element ?? list).append(item);
      return { item, input, count, section: sectionOf[number] ?? -1 };
    });

    group.append(summary, list, more);
    container.append(group);
    return { axis, group, chosen, items, sections, more };
  });

  return {
    update(counts, selection, expanded) {
      groups.forEach(({ axis, group, chosen, items, sections, more }, position) => {
        const limit = visibleLimit(axis, expanded.has(axis.key));
        const shown = sections.map(() => 0);
        let visible = 0;
        let hidden = 0;
        items.forEach(({ item, input, count, section }, number) => {
          const found = counts[position][number];
          input.checked = selection[axis.key].has(number);
          count.textContent = NUMBER_FORMAT.format(found);
          // 0 件の値は隠す。選んでいるものは、外せるように残す。
          const usable = found > 0 || input.checked;
          const room = visible < limit;
          item.hidden = !usable || !room;
          if (usable && room) {
            visible += 1;
            if (section >= 0) shown[section] += 1;
          } else if (usable) hidden += 1;
        });
        // **見えている体系が 1 つになったら見出しを出さない。**データセットを
        // 選べば 0 件の値が消えて体系は自然に 1 つになり、そこで残る見出しは
        // 選んだ種別の名前をなぞるだけになる。
        const alone = shown.filter((found) => found > 0).length < 2;
        sections.forEach(({ element, heading }, number) => {
          element.hidden = shown[number] === 0;
          heading.hidden = alone;
        });
        const picked = selection[axis.key].size;
        chosen.textContent = picked > 0 ? `${picked} 件選択中` : "";
        group.hidden = visible === 0 && hidden === 0 && picked === 0;
        more.hidden = hidden === 0;
        more.textContent = `ほか ${NUMBER_FORMAT.format(hidden)} 件を表示`;
      });
    },
  };
}

// 体系ごとの区画。**見出しは索引が持っている値** (ビルドが行から測る) で、
// 体系の表を画面に持たない (ADR 0014 / ADR 0015)。
function renderGroups(axis, list) {
  if (!showsGroups(axis)) return [];
  return axis.groups.map((scheme, number) => {
    const element = document.createElement("div");
    element.className = "facet-group";
    // 見出しと値の結び付きを、見た目だけでなく読み上げにも残す。
    element.setAttribute("role", "group");
    const heading = document.createElement("p");
    heading.className = "facet-group-label";
    heading.id = `facet-${axis.key}-group-${number}`;
    heading.textContent = scheme.label;
    element.setAttribute("aria-labelledby", heading.id);
    element.append(heading);
    list.append(element);
    return { element, heading, size: scheme.size };
  });
}

function renderList(list, catalog, indexes) {
  list.replaceChildren(
    ...indexes.map((index) => item(catalog.record(index), () => catalog.detail(index))),
  );
}

function item(record, load) {
  const element = document.createElement("li");
  element.className = "record";

  const heading = document.createElement("p");
  heading.className = "record-name";
  const link = document.createElement("a");
  // 原本のページ。サイトが持っているのは抜き出した文字情報だけで、
  // 写真や図面はここにしかない (ADR 0007)。
  link.href = record.url;
  link.rel = "noopener noreferrer";
  link.target = "_blank";
  link.textContent = record.name;
  heading.append(link);
  if (record.ridgeName) {
    const ridge = document.createElement("span");
    ridge.className = "record-ridge";
    ridge.textContent = record.ridgeName;
    heading.append(" ", ridge);
  }

  const meta = document.createElement("p");
  meta.className = "record-meta";
  const parts = [record.dataset, record.address, record.designatedYear].filter(Boolean);
  meta.textContent = parts.join(" / ");

  element.append(heading, meta);
  if (!record.mappable) {
    const note = document.createElement("p");
    note.className = "record-note";
    note.textContent = "地図に位置がない";
    element.append(note);
  }
  // 持っている項目はすべて読めるようにする (Issue #32 §4)。原本へのリンクは
  // 残す — 写真や図面はあちらにしかない (ADR 0007)。
  element.append(createDetailBlock(record, load));
  return element;
}
