#!/usr/bin/env bash
# データリポジトリを取得する。
#
# **リポジトリ名の表を持たない** (ADR 0015)。org のリポジトリを列挙し、
# meta.json を持つものだけを残す。種別が増えても減っても、ここもサイトも変わらない。
#
# あわせて取得元の commit を `sources.txt` に残す。配布物の目録 (`MANIFEST.json`)
# に載せて、**どの状態を固めたのかを後から辿れる**ようにするため。`heritage-site`
# 側から `git` を呼ばずに済むよう、SHA を知っているここで書き出す。
set -euo pipefail

destination="${1:?取得先のディレクトリが未指定}"
org="${DATASET_ORG:-code4heritage}"
# サイト自身は対象外。データリポジトリと同じ org にいるため名指しで除く。
skip="${DATASET_SKIP:-heritages}"

mkdir -p "$destination"
sources="${destination}/sources.txt"
: >"$sources"

kept=0
skipped=0
# パイプではなくプロセス置換で読む (パイプだと while がサブシェルになり、
# 数えた結果がループの外に出てこない)。
while read -r name; do
  if [[ "$name" == "$skip" ]]; then
    continue
  fi
  git clone --depth 1 --quiet "https://github.com/${org}/${name}.git" "${destination}/${name}"
  if [[ -f "${destination}/${name}/meta.json" ]]; then
    kept=$((kept + 1))
    printf '%s %s\n' "$name" "$(git -C "${destination}/${name}" rev-parse HEAD)" >>"$sources"
  else
    # データの無い器 (ADR 0013) やサイトの補助リポジトリはここで落ちる。
    echo "対象外 (meta.json が無い): ${name}"
    rm -rf "${destination:?}/${name}"
    skipped=$((skipped + 1))
  fi
done < <(gh repo list "$org" --limit 200 --no-archived --visibility public --json name --jq '.[].name' | sort)

echo "データセット ${kept} 件を取得 (対象外 ${skipped} 件)"
if [[ "$kept" -eq 0 ]]; then
  echo "NG: meta.json を持つリポジトリが 1 つも無い" >&2
  exit 1
fi
