#!/usr/bin/env bash
# 初回準備: run_pipeline*.sh / run_channel.sh に実行権限を付与し、親ディレクトリ（../）に同名のシンボリックリンクを作る
#   bash junbi.sh
#   または: chmod +x junbi.sh && ./junbi.sh
#   エイリアス aa/bb を「このプロンプトのシェル」にすぐ載せたい場合: source junbi.sh
# Cloud Shell 等: リポジトリが ~/py_youtube-transcript-api なら ~/run_pipeline.sh や ~/run_channel.sh からも実行しやすくなる

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$ROOT"

LINK_DIR="$(cd "${ROOT}/.." && pwd)"

for name in run_pipeline_urls.sh run_pipeline.sh run_pipeline1.sh run_pipeline2.sh run_pipeline3.sh run_pipeline4.sh run_pipeline5.sh run_channel.sh; do
  f="${ROOT}/${name}"
  if [[ ! -f "${f}" ]]; then
    continue
  fi
  chmod +x "${f}"
  echo "chmod +x ${name} しました。"
  ln -sf "${f}" "${LINK_DIR}/${name}"
  echo "リンク作成: ${LINK_DIR}/${name} -> ${f}"
done

# ~/.bashrc にエイリアスが無ければ追記（有れば何もしない）
BASHRC="${HOME}/.bashrc"
AA_LINE="alias aa='./run_pipeline.sh \"'"
BB_LINE="alias bb='cat ~/py_youtube-transcript-api/batch1.log'"

AA=0

if [[ ! -f "${BASHRC}" ]] || ! grep -Fxq "${AA_LINE}" "${BASHRC}" 2>/dev/null; then
  AA=1
  printf '%s\n' "${AA_LINE}" >> "${BASHRC}"
  echo "追記: ${BASHRC} に ${AA_LINE}"
else
  echo "${BASHRC} に既に ${AA_LINE} があります。スキップ。"
fi

if [[ ! -f "${BASHRC}" ]] || ! grep -Fxq "${BB_LINE}" "${BASHRC}" 2>/dev/null; then
  AA=2
  printf '%s\n' "${BB_LINE}" >> "${BASHRC}"
  echo "追記: ${BASHRC} に ${BB_LINE}"
else
  echo "${BASHRC} に既に ${BB_LINE} があります。スキップ。"
fi

if [[ -f "${BASHRC}" ]] && [[ "${AA}" != 0 ]] ; then
  # shellcheck source=/dev/null
  source "${BASHRC}"
  echo "反映: 現在のシェルに source ${BASHRC} しました。"
  echo "新規シェルから aa / bb コマンドが使えます。"
  echo 'aa実行後、YoutubeのURLを貼り付け、最後に半角の"を付けてEnterを押すと実行されます。'
  echo "bb実行後、batch1.logを表示します。"
fi
