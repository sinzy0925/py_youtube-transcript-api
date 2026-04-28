#!/usr/bin/env bash
# 初回準備: run_pipeline*.sh に実行権限を付与し、親ディレクトリ（../）に同名のシンボリックリンクを作る
#   bash junbi.sh
#   または: chmod +x junbi.sh && ./junbi.sh
# Cloud Shell 等: リポジトリが ~/py_youtube-transcript-api なら ~/run_pipeline.sh や ~/run_pipeline1.sh からも実行しやすくなる

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$ROOT"

LINK_DIR="$(cd "${ROOT}/.." && pwd)"

for name in run_pipeline.sh run_pipeline1.sh run_pipeline2.sh run_pipeline3.sh run_pipeline4.sh run_pipeline5.sh; do
  f="${ROOT}/${name}"
  if [[ ! -f "${f}" ]]; then
    continue
  fi
  chmod +x "${f}"
  echo "chmod +x ${name} しました。"
  ln -sf "${f}" "${LINK_DIR}/${name}"
  echo "リンク作成: ${LINK_DIR}/${name} -> ${f}"
done
