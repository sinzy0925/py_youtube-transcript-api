#!/usr/bin/env bash
# 初回準備: run_pipeline.sh に実行権限を付与し、親ディレクトリ（../）に同名のシンボリックリンクを作る
#   bash junbi.sh
#   または: chmod +x junbi.sh && ./junbi.sh
# Cloud Shell 等: リポジトリが ~/py_youtube-transcript-api なら ~/run_pipeline.sh からも実行しやすくなる

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$ROOT"

TARGET_SH="${ROOT}/run_pipeline.sh"
LINK_PATH="$(cd "${ROOT}/.." && pwd)/run_pipeline.sh"

if [[ ! -f "${TARGET_SH}" ]]; then
  echo "エラー: ${TARGET_SH} がありません。" >&2
  exit 1
fi

chmod +x "${TARGET_SH}"
echo "chmod +x run_pipeline.sh しました。"

ln -sf "${TARGET_SH}" "${LINK_PATH}"
echo "リンク作成: ${LINK_PATH} -> ${TARGET_SH}"
