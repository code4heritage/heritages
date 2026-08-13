// 検索・ファセット・一覧の画面 (Issue #32 §2)。
//
// 素の input / checkbox / button だけで組み立てる。**キーボードだけで
// 使えること**は地図に依存しない経路の保証でもあり、地図に位置を持たない
// 373 行への配慮でもある。
//
// 仮想スクロールは入れない。一覧は先頭 200 件を描き、「さらに 200 件」で伸ばす。

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
  const groups = catalog.axes.map((axis, position) => {
    const group = document.createElement("details");
    group.className = "facet";
    // 最初の軸 (データセット) だけ開いておく。9 軸すべてを開くと、一覧に
    // たどり着く前に画面が facet で埋まる。
    group.open = position === 0;

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
      list.append(item);
      return { item, input, count };
    });

    group.append(summary, list, more);
    container.append(group);
    return { axis, group, chosen, items, more };
  });

  return {
    update(counts, selection, expanded) {
      groups.forEach(({ axis, group, chosen, items, more }, position) => {
        const limit = visibleLimit(axis, expanded.has(axis.key));
        let visible = 0;
        let hidden = 0;
        items.forEach(({ item, input, count }, number) => {
          const found = counts[position][number];
          input.checked = selection[axis.key].has(number);
          count.textContent = NUMBER_FORMAT.format(found);
          // 0 件の値は隠す。選んでいるものは、外せるように残す。
          const usable = found > 0 || input.checked;
          const room = visible < limit;
          item.hidden = !usable || !room;
          if (usable && room) visible += 1;
          else if (usable) hidden += 1;
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

function renderList(list, catalog, indexes) {
  list.replaceChildren(...indexes.map((index) => item(catalog.record(index))));
}

function item(record) {
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
  return element;
}
