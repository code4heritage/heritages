# heritages

**https://code4heritage.github.io/heritages/**

文化庁「[国指定文化財等データベース](https://kunishitei.bunka.go.jp/bsys/index)」を
定期的に確認して、そこにある建造物・記念物のデータを種別ごとにまとめ、地図と一覧で
見られるようにしています。**非公式**のサイトです — 文化庁および国の機関が作成・
運営するものではありません。

- **地図**で探す。位置を持たない指定は件数を示して一覧へ繋ぎます
- **名称・ふりがな・棟名・所在地**から探す。「とうだいじ」でも当たります
- **種別・時代・所在都道府県**などで絞り込む
- 1 件ずつ開けば、**解説文・員数・構造及び形式等・指定基準など持っている項目は
  すべて**読めます。写真や図面は原本のページにあります
- 元になった行は JSON Lines のまま配っているので、ブラウザを使わずに読むこともできます。
  **全種別を 1 つにまとめた ZIP** も置いています (下記)

画面に出ている「**利用日**」は、その種別のデータを国指定文化財等データベースから
取り出した日です。表示している内容はその時点のものです。「**最終確認**」は、変更が
無いかを見にいった最後の日です。**毎週見ていますが、変更が無ければ取り出し直さない
ので、利用日は動きません。**

## データ

データそのものは種別ごとの別リポジトリ
([code4heritage](https://github.com/code4heritage)) にあり、このリポジトリは
**サイトだけ**を持ちます。データを取り出しているのはクローラー
([shinyaoguri/heritage-crawler](https://github.com/shinyaoguri/heritage-crawler))
です。

サイトは受け取った行に手を入れません。**見えているのはデータリポジトリのあの行
そのもの**で、内容を直す立場にはありません。

## まとめてダウンロードする

全種別を 1 つにまとめた ZIP を
[リリース](https://github.com/code4heritage/heritages/releases)で配っています
(約 7 MB)。この URL は常に最新を指します。

```
https://github.com/code4heritage/heritages/releases/latest/download/heritages-jsonl.zip
```

中身は種別ごとの JSON Lines と `meta.json`、それに件数・利用日・照合値を持つ
目録 `MANIFEST.json` です。**種別ごとのぶんは各データリポジトリのリリース**に、
展開すればそのリポジトリの中身になる形で置いています。

**リリースノートには、前回配ったときからどの文化財の何が変わったかを書いています。**
新しく指定されたもの・指定から外れたもの・内容が変わったものが、名前で分かります。
データが変わらなかった回はリリースを作りません。

## ライセンス

サイトのコードは [MIT](LICENSE)。掲載しているデータは出典元である文化庁
「国指定文化財等データベース」の利用規約に従います。同梱している Leaflet は
BSD 2-Clause で、原文を [`site/vendor/leaflet/LICENSE`](site/vendor/leaflet/LICENSE)
に置いています。地図のタイルは国土地理院の
[地理院タイル](https://maps.gsi.go.jp/development/ichiran.html)です。

---

サイトの作り・組み立て方・検証は [CONTRIBUTING.md](CONTRIBUTING.md) にあります。
