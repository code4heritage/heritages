# heritages

**https://code4heritage.github.io/heritages/**

文化庁「[国指定文化財等データベース](https://kunishitei.bunka.go.jp/bsys/index)」を
定期的に確認して、そこにある建造物・記念物のデータを種別ごとにまとめ、地図と一覧で
見られるようにしています。**非公式**のサイトです — 文化庁および国の機関が作成・
運営するものではありません。

- **地図**で探す。位置を持たない指定は件数を示して一覧へ繋ぎます
- **名称・ふりがな・棟名・所在地**から探す。「とうだいじ」でも当たります
- **種別・時代・所在都道府県**などで絞り込む
- 元になった行は JSON Lines のまま配っているので、ブラウザを使わずに読むこともできます

画面に出ている「**利用日**」は、その種別のデータを国指定文化財等データベースから
取り出した日です。表示している内容はその時点のものです。

## データ

データそのものは種別ごとの別リポジトリ
([code4heritage](https://github.com/code4heritage)) にあり、このリポジトリは
**サイトだけ**を持ちます。データを取り出しているのはクローラー
([shinyaoguri/heritage-crawler](https://github.com/shinyaoguri/heritage-crawler))
です。

サイトは受け取った行に手を入れません。**見えているのはデータリポジトリのあの行
そのもの**で、内容を直す立場にはありません。

## ライセンス

サイトのコードは [MIT](LICENSE)。掲載しているデータは出典元である文化庁
「国指定文化財等データベース」の利用規約に従います。同梱している Leaflet は
BSD 2-Clause で、原文を [`site/vendor/leaflet/LICENSE`](site/vendor/leaflet/LICENSE)
に置いています。地図のタイルは国土地理院の
[地理院タイル](https://maps.gsi.go.jp/development/ichiran.html)です。

---

サイトの作り・組み立て方・検証は [CONTRIBUTING.md](CONTRIBUTING.md) にあります。
