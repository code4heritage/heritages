// 検索文字列の正規化 (Issue #32 §2)。
//
// **ビルド側 (src/heritage_site/search.py) と同じ結果を返さなければならない。**
// 索引を作るのは Python、打たれた語を均すのはここで、ずれると「打った語が
// 当たらない」という形で静かに壊れる。両者は共通の事例表 (tests/normalization.json)
// で突き合わせて固定してある。**片方だけ直さないこと。**

// ひらがなと 1:1 に対応するカタカナの範囲 (ァ〜ヶ)。
const KATAKANA_FIRST = 0x30a1;
const KATAKANA_LAST = 0x30f6;
const HIRAGANA_OFFSET = 0x60;

// 落とす文字。空白は書き下す — JS の \s と Python の str.isspace は対象が
// わずかに違い、どちらかの既定に寄せると両側の正規化がずれる。
const DROPPED = new Set([
  " ",
  "\t",
  "\n",
  "\r",
  "\v",
  "\f",
  "\u00a0",
  "\u3000",
  "・",
]);

export function normalize(text) {
  const folded = text.normalize("NFKC").toLowerCase();
  let result = "";
  for (const character of folded) {
    const code = character.codePointAt(0);
    if (code >= KATAKANA_FIRST && code <= KATAKANA_LAST) {
      result += String.fromCodePoint(code - HIRAGANA_OFFSET);
    } else if (!DROPPED.has(character)) {
      result += character;
    }
  }
  return result;
}
