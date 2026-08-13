// 地図の画面 (Issue #3 / Issue #32 §3)。
//
// タイルは**地理院タイル**、ライブラリは**同梱した Leaflet** (ADR 0016)。
// 閲覧者のブラウザが外へ出るのはタイルの取得だけで、他はこのリポジトリから配る。
//
// 点は Leaflet のマーカーではなく **1 枚の canvas** に自分で描く。地図に置ける
// 行が 23,482 あり、DOM 要素を 1 つずつ置ける数ではない。まとめ方は cluster.js
// (DOM に触れないので node から検査できる)。
//
// **地図は「さがす」の結果をそのまま映す。**地図側に別の絞り込みを持たせると、
// 一覧と地図で見えているものが食い違う。

import { CELL_SIZE, cluster, countMappable } from "./cluster.js";
import {
  DomUtil,
  Layer,
  latLngBounds,
  map as createLeafletMap,
  point,
  popup as createPopup,
  tileLayer,
} from "./vendor/leaflet/leaflet-src.esm.js";

// タイルの取り出し先は**ここだけ**に置く (ADR 0016)。規約が変わったときに
// 直す場所を 1 つにするため。
//
// OSM の共有タイルは切り替え先として ADR に残っているが、画面には出さない。
// 出す以上は出典表記 (`© OpenStreetMap contributors`) の切り替えまで要り、
// 表記を静的な HTML で保てなくなる。足すときは index.html の出典もあわせて直す。
const TILE_SOURCES = [
  {
    key: "pale",
    label: "淡色",
    url: "https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png",
  },
  {
    key: "std",
    label: "標準",
    url: "https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png",
  },
];

// 2 万を超える点を重ねるので、地物の描き込みが少ない淡色を初期表示にする (ADR 0016)。
const DEFAULT_SOURCE = TILE_SOURCES[0];

// 地理院タイルのズームは 5〜18。これより引いたタイルは存在しない (ADR 0016)。
const MIN_ZOOM = 5;
const MAX_ZOOM = 18;

// 最初に見えるもの。日本の外周の検査 (checks.py の `in_japan`) とは別物で、
// こちらは初期表示だけを決める。
const INITIAL_CENTER = [36.5, 137.5];
const INITIAL_ZOOM = 5;

// 点の世界座標を持つ基準のズーム。ここで一度だけ投影し、以後は倍率をかける。
const PROJECTION_ZOOM = MAX_ZOOM;

// 画面の外側にも描いておく余白の割合。地図を掴んで動かしている間、Leaflet は
// canvas ごと動かす (描き直すのは離した後) ので、余白が無いと縁に点の無い帯が出る。
const PADDING = 0.2;

const CLUSTER_FILL = "rgba(107, 79, 29, 0.82)";
const CLUSTER_TEXT = "#fdfdfb";
const POINT_FILL = "rgba(138, 28, 28, 0.9)";
const POINT_EDGE = "#fdfdfb";
const POINT_RADIUS = 4.5;

const NUMBER_FORMAT = new Intl.NumberFormat("ja-JP");

/**
 * 地図を組み立てる。返り値の `show(matched)` に絞り込みの結果を渡すと、
 * 地図がその集合に入れ替わる。
 */
export function createMapView(catalog, elements) {
  const map = createLeafletMap(elements.map, {
    center: INITIAL_CENTER,
    zoom: INITIAL_ZOOM,
    minZoom: MIN_ZOOM,
    maxZoom: MAX_ZOOM,
    // 出典は HTML 側に置いて常時見せる (ADR 0016)。ライブラリが作る表示に
    // 預けると、静的な検査 (tests/test_notices.py) から見えなくなる。
    attributionControl: false,
  });

  const tiles = tileLayer(DEFAULT_SOURCE.url, { minZoom: MIN_ZOOM, maxZoom: MAX_ZOOM }).addTo(map);
  renderTileChooser(elements.tiles, (source) => tiles.setUrl(source.url));

  const positions = project(map, catalog.coordinates);
  const layer = new PointLayer(positions, {
    onPick: (index) => showRecord(map, catalog, positions, index),
  }).addTo(map);

  return {
    show(matched) {
      layer.show(matched);
      renderSummary(elements.summary, countMappable(positions, matched), matched.length);
    },
  };
}

/** 経緯度を基準ズームの世界画素座標にしておく。地図に置けない行は `NaN`。 */
function project(map, { latitudes, longitudes }) {
  const x = new Float64Array(latitudes.length);
  const y = new Float64Array(latitudes.length);
  for (let index = 0; index < latitudes.length; index += 1) {
    if (Number.isNaN(latitudes[index]) || Number.isNaN(longitudes[index])) {
      x[index] = NaN;
      y[index] = NaN;
      continue;
    }
    const projected = map.project([latitudes[index], longitudes[index]], PROJECTION_ZOOM);
    x[index] = projected.x;
    y[index] = projected.y;
  }
  return { x, y };
}

// タイルの切り替えは素の radio で組む。ライブラリのコントロールを使うと
// 画像の同梱が要るうえ、キーボードでの扱いも素の input に及ばない。
function renderTileChooser(container, onChange) {
  container.replaceChildren(
    ...TILE_SOURCES.map((source) => {
      const label = document.createElement("label");
      label.className = "map-tile";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "map-tile";
      input.value = source.key;
      input.checked = source.key === DEFAULT_SOURCE.key;
      input.addEventListener("change", () => {
        if (input.checked) onChange(source);
      });
      const text = document.createElement("span");
      text.textContent = source.label;
      label.append(input, text);
      return label;
    }),
  );
}

function renderSummary(element, mappable, matched) {
  const parts = [`${NUMBER_FORMAT.format(mappable)} 件を地図に表示`];
  const missing = matched - mappable;
  // 位置を持たない行を黙って落とさない (Issue #32 §3)。数を示して、一覧の
  // 「地図に位置がない」へ繋ぐ。
  if (missing > 0) parts.push(`${NUMBER_FORMAT.format(missing)} 件は位置がないので一覧のみ`);
  element.textContent = parts.join(" / ");
}

// 点を描く canvas のレイヤ。
//
// ズームの間は `leaflet-zoom-hide` で隠し、終わってから描き直す (Leaflet 自身の
// 描画レイヤと同じ扱い)。途中経過に合わせて canvas を変形させる手もあるが、
// そちらはライブラリの内部 API に依るので、同梱の版を上げたときに黙って壊れる。
const PointLayer = Layer.extend({
  initialize(positions, { onPick }) {
    this._positions = positions;
    this._onPick = onPick;
    this._matched = [];
    this._clusters = [];
  },

  onAdd(map) {
    this._canvas = DomUtil.create("canvas", "map-points leaflet-zoom-hide");
    map.getPanes().overlayPane.appendChild(this._canvas);
    this._context = this._canvas.getContext("2d");
    map.on("click", this._onClick, this);
    map.on("mousemove", this._onHover, this);
    this._reset();
  },

  onRemove(map) {
    map.off("click", this._onClick, this);
    map.off("mousemove", this._onHover, this);
    this._canvas.remove();
  },

  getEvents() {
    return {
      viewreset: this._reset,
      resize: this._reset,
      moveend: this._reset,
      zoomend: this._reset,
    };
  },

  show(matched) {
    this._matched = matched;
    this._draw();
  },

  _reset() {
    const map = this._map;
    const size = map.getSize();
    const padding = point(Math.round(size.x * PADDING), Math.round(size.y * PADDING));
    const width = size.x + padding.x * 2;
    const height = size.y + padding.y * 2;
    // canvas の左上を「画面の左上より余白ぶん外側」に合わせる。以後の計算は
    // すべて canvas の左上を原点とする。
    DomUtil.setPosition(this._canvas, map.containerPointToLayerPoint(padding.multiplyBy(-1)));

    // 高解像度の画面でも丸と数字が滲まないように、実画素で持って縮めて見せる。
    const ratio = window.devicePixelRatio || 1;
    this._canvas.width = Math.round(width * ratio);
    this._canvas.height = Math.round(height * ratio);
    this._canvas.style.width = `${width}px`;
    this._canvas.style.height = `${height}px`;
    this._context.setTransform(ratio, 0, 0, ratio, 0, 0);

    const bounds = map.getPixelBounds();
    this._padding = padding;
    this._view = {
      originX: bounds.min.x - padding.x,
      originY: bounds.min.y - padding.y,
      width,
      height,
      scale: map.getZoomScale(map.getZoom(), PROJECTION_ZOOM),
      cellSize: CELL_SIZE,
    };
    this._draw();
  },

  _draw() {
    if (!this._view) return;
    this._clusters = cluster(this._positions, this._matched, this._view);
    const context = this._context;
    context.clearRect(0, 0, this._view.width, this._view.height);
    context.textAlign = "center";
    context.textBaseline = "middle";
    for (const item of this._clusters) {
      if (item.count === 1) drawPoint(context, item);
      else drawCluster(context, item);
    }
  },

  // 画面の座標から、そこにある丸を探す (canvas は画面より余白ぶん外側から始まる)。
  _at(containerPoint) {
    const x = containerPoint.x + this._padding.x;
    const y = containerPoint.y + this._padding.y;
    let found = null;
    let best = Infinity;
    for (const item of this._clusters) {
      const distance = Math.hypot(item.x - x, item.y - y);
      if (distance <= radiusOf(item) && distance < best) {
        best = distance;
        found = item;
      }
    }
    return found;
  },

  _onClick(event) {
    const found = this._at(event.containerPoint);
    if (!found) return;
    if (found.count === 1) this._onPick(found.index);
    else this._zoomInto(found);
  },

  // 指す先は地図の容れ物に付ける。canvas はクリックを受け取らない
  // (`pointer-events: none`) ので、そちらに書いても効かない。
  _onHover(event) {
    const container = this._map.getContainer();
    container.style.cursor = this._at(event.containerPoint) ? "pointer" : "";
  },

  // まとめた丸を押したら、中身が分かれて見える縮尺まで寄る。
  _zoomInto(item) {
    const map = this._map;
    const at = (x, y) => map.containerPointToLatLng([x - this._padding.x, y - this._padding.y]);
    const { minX, minY, maxX, maxY } = item.bounds;
    // 同じ地点に重なっているものは広がりを持たない。寄せても分かれないので、
    // 収める先ではなく倍率で寄る。
    if (maxX - minX < 1 && maxY - minY < 1) {
      map.setView(at(item.x, item.y), Math.min(map.getZoom() + 3, MAX_ZOOM));
      return;
    }
    map.fitBounds(latLngBounds(at(minX, minY), at(maxX, maxY)), { padding: [40, 40] });
  },
});

function radiusOf(item) {
  if (item.count === 1) return POINT_RADIUS + 3;
  // 件数は桁で効かせる。数に比例させると、数千件の丸が画面を覆う。
  return 11 + Math.min(Math.log10(item.count), 4) * 4.5;
}

function drawPoint(context, item) {
  context.beginPath();
  context.arc(item.x, item.y, POINT_RADIUS, 0, Math.PI * 2);
  context.fillStyle = POINT_FILL;
  context.fill();
  context.lineWidth = 1;
  context.strokeStyle = POINT_EDGE;
  context.stroke();
}

function drawCluster(context, item) {
  const radius = radiusOf(item);
  context.beginPath();
  context.arc(item.x, item.y, radius, 0, Math.PI * 2);
  context.fillStyle = CLUSTER_FILL;
  context.fill();
  context.fillStyle = CLUSTER_TEXT;
  context.font = `${Math.round(radius * 0.8)}px system-ui, sans-serif`;
  context.fillText(NUMBER_FORMAT.format(item.count), item.x, item.y);
}

// 点を押したときに出す吹き出し。**一覧と同じ情報 + 原本へのリンク**までに
// 留める (項目をすべて並べる詳細ビューは Issue #32 §4)。
function showRecord(map, catalog, positions, index) {
  const record = catalog.record(index);
  const content = document.createElement("div");
  content.className = "map-popup";

  const heading = document.createElement("p");
  heading.className = "record-name";
  const link = document.createElement("a");
  // 原本のページ。写真や図面はここにしかない (ADR 0007)。
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
  meta.textContent = [record.dataset, record.address, record.designatedYear]
    .filter(Boolean)
    .join(" / ");

  content.append(heading, meta);
  createPopup()
    .setLatLng(map.unproject([positions.x[index], positions.y[index]], PROJECTION_ZOOM))
    .setContent(content)
    .openOn(map);
}
