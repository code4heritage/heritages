// 地図に置く点のまとめ方 (Issue #3 / Issue #32 §3)。
//
// **DOM にも Leaflet にも触れない。**地図の見た目は人が見るしかないが、
// 「どの点を出すか」「どうまとめるか」は機械で確かめられる規則なので、
// 描画 (map.js) から切り離して node から検査する。
//
// 23,482 行を点のまま置くと、引いた縮尺では塗り潰しにしかならない。画面の
// 升目 (セル) ごとにまとめ、件数を書いた丸を 1 つ描く。まとめる単位を
// **地物の距離ではなく画面の画素**にしているので、縮尺を変えれば同じ密度で
// まとまり直す。

// セルの一辺 (画素)。丸の直径よりわずかに大きくして、隣り合う丸が重ならない
// ようにしている。
export const CELL_SIZE = 56;

/**
 * 画面に入る点をセルごとにまとめる。
 *
 * `positions` は**全行ぶん**の「基準ズームでの世界画素座標」で、地図に置けない
 * 行は `NaN`。`matched` は今見せている行の番号 (絞り込みの結果)。
 *
 * 返す座標は canvas の左上を原点とする画素。`count` が 1 のときだけ `index` が
 * その行を指す (2 件以上をまとめた丸は、どれか 1 行を代表させない)。
 */
export function cluster(
  positions,
  matched,
  { originX, originY, width, height, scale, cellSize = CELL_SIZE, margin = 0 },
) {
  const cells = new Map();
  // 行の並び順に依らず同じ結果になるよう、セルの番号は座標だけから決める。
  const columns = Math.ceil((width + margin * 2) / cellSize) + 1;

  for (const index of matched) {
    const worldX = positions.x[index];
    const worldY = positions.y[index];
    // 座標を持たない行と、日本の外周から外れた行は `NaN` で入っている。
    // **NaN は比較がすべて偽になるので、範囲の判定では落とせない。**
    if (Number.isNaN(worldX) || Number.isNaN(worldY)) continue;

    const x = worldX * scale - originX;
    const y = worldY * scale - originY;
    if (x < -margin || x > width + margin) continue;
    if (y < -margin || y > height + margin) continue;

    const key =
      Math.floor((y + margin) / cellSize) * columns + Math.floor((x + margin) / cellSize);
    const cell = cells.get(key);
    if (cell === undefined) {
      cells.set(key, { sumX: x, sumY: y, count: 1, index, minX: x, minY: y, maxX: x, maxY: y });
      continue;
    }
    cell.sumX += x;
    cell.sumY += y;
    cell.count += 1;
    cell.minX = Math.min(cell.minX, x);
    cell.minY = Math.min(cell.minY, y);
    cell.maxX = Math.max(cell.maxX, x);
    cell.maxY = Math.max(cell.maxY, y);
  }

  return [...cells.values()].map((cell) => ({
    // 丸の位置はセルの中心ではなく、まとめた点の平均。中心に置くと、実際には
    // 何も無いところに丸が出る。
    x: cell.sumX / cell.count,
    y: cell.sumY / cell.count,
    count: cell.count,
    index: cell.count === 1 ? cell.index : null,
    bounds: { minX: cell.minX, minY: cell.minY, maxX: cell.maxX, maxY: cell.maxY },
  }));
}

/** 地図に置ける行の数。置けない行を「黙って落としていない」と示すために数える。 */
export function countMappable(positions, matched) {
  let found = 0;
  for (const index of matched) {
    if (!Number.isNaN(positions.x[index]) && !Number.isNaN(positions.y[index])) found += 1;
  }
  return found;
}
