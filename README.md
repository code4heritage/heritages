# heritages

[国指定文化財等データベース](https://kunishitei.bunka.go.jp/bsys/index) (文化庁) から
取り出した建造物・記念物のデータを、地図と一覧で見るサイト。**非公式**です。

データそのものは種別ごとの別リポジトリにあり
([code4heritage](https://github.com/code4heritage))、このリポジトリは**サイトだけ**を
持ちます。取得しているのはクローラー
([shinyaoguri/heritage-crawler](https://github.com/shinyaoguri/heritage-crawler))
で、決定ログ (ADR) とロードマップもそちらが正本です。

種別横断のサイトを 1 つだけ置いています。種別ごとに分けるのはデータであって
コードではなく、**同じ棟が複数の種別に現れる複合指定**が 114 件あるためです
(ADR 0015)。

## 作り

```
site/     配る静的ファイル (バンドラなしの素の ESM)
src/      配信ディレクトリを組み立てるビルド (Python 標準ライブラリのみ)
scripts/  データリポジトリの取得と、PR タイトルの検査
```

ビルドがすることは 3 つだけです。

1. データリポジトリの `meta.json` を束ねた `index.json` を書く
2. 地図が読む軽い索引 `points.json` を書く
3. `data/*.jsonl` を**変換せずそのまま**並べ、静的ファイルを重ねる

**JSON Lines に手を入れません。**サイトが見せているのはデータリポジトリのあの行
そのもの、と言える状態を保ちます。生成するのは索引だけです。

**データセットはリポジトリ名の表ではなく `meta.json` の有無で見つけます。**
種別が増えても減っても、サイト側に変更は要りません。

## 動かす

```bash
pip install -e '.[dev]'
```

データリポジトリを並べたディレクトリを指してビルドします。

```bash
./scripts/fetch-datasets.sh data-repos   # org から取ってくる (gh が要る)
heritage-site build --data-dir data-repos --out dist
python3 -m http.server -d dist
```

## 検証

```bash
ruff check .
mypy src
pytest -q
```

CI はこれを Python 3.12 / 3.13 / 3.14 で回し、あわせて PR タイトルの
Conventional Commits 形式を検査します (squash merge でタイトルがそのまま main の
コミットメッセージになるため)。

## ビルド時の不変条件

サイトはデータリポジトリを読むだけで、直せる立場にありません。検査の役目は
**壊れた状態で黙って配信されるのを止めること**に絞っています。

| 検査 | 破れたとき |
|---|---|
| `schema_version` がサイトの対応版か | 止める |
| 利用日が 45 日より古くないか | 止める (月次更新が止まった) |
| `meta.json` の宣言と実在ファイルが一致するか | 止める |
| `meta.json` の件数と実際の行数が一致するか | 止める |
| 索引に要る項目 (`ledger_id` / `managed_id` / `name` / `url`) が空でないか | 止める |
| 複数の種別に現れる棟が同じ原本 `url` を指すか | 止める |
| 座標の無い行が急増していないか | 止める (台帳の取得漏れを疑う) |
| 日本の外周の外にある座標 | 報せて地図から除く |

止めても配信済みのサイトは残ります (Pages は最後に成功したデプロイを配り続ける)
ので、構造の壊れは止める側に倒しています。逆に**上流データの誤り 1 件で毎月の
反映は止めません**。

## 配信

GitHub Pages。ソースは **GitHub Actions** で、ビルド結果はアーティファクトとして
配ります (生成物はコミットしません)。`.github/workflows/pages.yml` が
main への push・月次・手動実行で走ります。

## ライセンス

サイトのコードは [MIT](LICENSE)。掲載しているデータは出典元である文化庁
「国指定文化財等データベース」の利用規約に従います。
