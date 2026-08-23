// 地図の要約文 (Issue #23)。
//
// **地図そのものは人が見るしかないが、何を言うかは機械で確かめられる。**
// 地図に出せる行が 0 件のとき何と言うかは、場所に結び付かない種別が加わって
// 初めて要るようになった判断なので、文言ごとテストで固定する
// (tests/test_map.py)。`map.js` に置くと Leaflet ごと読み込むことになり、
// node から呼べない — DOM に触れない判断を切り出しておくのは cluster.js と同じ。

const NUMBER_FORMAT = new Intl.NumberFormat("ja-JP");

export function summaryText(mappable, matched, { placeless = false } = {}) {
  // 1 件も当たらなかった回は一覧の側が「ありません」と言う。地図まで数を
  // 繰り返すと、同じことを 2 か所が読み上げる。
  if (matched === 0) return "";
  if (mappable === 0) {
    return placeless
      ? `${NUMBER_FORMAT.format(matched)} 件はいずれも場所に結び付かない種別です。一覧で見られます`
      : `${NUMBER_FORMAT.format(matched)} 件はいずれも所在地が公開されていません。一覧で見られます`;
  }
  const parts = [`${NUMBER_FORMAT.format(mappable)} 件を地図に表示`];
  const missing = matched - mappable;
  // 位置を持たない行を黙って落とさない (Issue #32 §3)。数を示して、一覧の
  // 「地図に位置がない」へ繋ぐ。
  if (missing > 0) parts.push(`${NUMBER_FORMAT.format(missing)} 件は位置がないので一覧のみ`);
  return parts.join(" / ");
}
