# Leaflet 1.9.4 (同梱)

地図ライブラリは CDN から読まず、ここに置いたものを配る
([ADR 0016](https://github.com/shinyaoguri/heritage-crawler/blob/main/docs/decisions/0016-gsi-tiles-and-vendored-map-library.md))。
閲覧者のブラウザが第三者のオリジンへ接続しないので、**外部へ出るのはタイルだけ**
という状態を目で確かめられる。

## 取得元と内容 (2026-08-13)

| ファイル | 取得元 | sha256 |
|---|---|---|
| `leaflet-src.esm.js` | https://unpkg.com/leaflet@1.9.4/dist/leaflet-src.esm.js | `39ee93464f11fe3847137e50c0dc8189f706c460e36989ea7871bf7d540f3306` |
| `leaflet.css` | https://unpkg.com/leaflet@1.9.4/dist/leaflet.css | `a7837102824184820dfa198d1ebcd109ff6d0ff9a2672a074b9a1b4d147d04c6` |
| `LICENSE` | https://unpkg.com/leaflet@1.9.4/LICENSE | `53e8dc25862014e4324741ca18fbe3611e11d42ef69f59f86ea8c5389647d4cb` |

**1 文字も変えていない。**この表と実ファイルが一致することは
`tests/test_vendor.py` が検査する — 同梱物に手を入れると、上流の版と照合できなく
なり「何を配っているのか」が言えなくなるため。差し替えるときは**ファイルごと
入れ替えて、この表を書き直す**。

## なぜ最小化版 (`leaflet.js`) ではないのか

このリポジトリにはビルド工程が無く、`site/` はそのまま配る素の ESM で書いている
(ADR 0015)。最小化版は UMD でグローバル `L` を生やすため `<script>` タグでの
読み込みが要り、中身も読めない。ESM 版なら他の `site/*.js` と同じ `import` で
つながり、**同梱しているものを読める**。

代償は転送量で、gzip 後 109 KB (最小化版なら 43 KB)。行の索引 `records.json` が
gzip 1.35 MB あるので、比率としては受け入れられる。

## 画像を同梱していない理由

`leaflet.css` は 3 つの画像を参照するが、どれもこのサイトでは使わない規則の中に
あるので取りに行かれない。

- `images/layers.png` / `images/layers-2x.png` — レイヤ切り替えコントロール。
  タイルの切り替えは素の `input[type=radio]` で組んでいる (キーボードで使えるため)
- `images/marker-icon.png` — 既定のマーカー。点は canvas に自分で描くので使わない
  (2 万を超える点に DOM 要素を 1 つずつ置けない)

**参照が生きるものを足すときは画像も同梱する。**外部オリジンへ取りに行かせない、
がこの同梱の目的なので、そこが破れると意味が無くなる。
