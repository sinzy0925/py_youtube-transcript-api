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

if [[ ! -f "${BASHRC}" ]] || ! grep -Fxq "${AA_LINE}" "${BASHRC}" 2>/dev/null; then
  printf '%s\n' "${AA_LINE}" >> "${BASHRC}"
  echo "追記: ${BASHRC} に ${AA_LINE}"
else
  echo "${BASHRC} に既に ${AA_LINE} があります。スキップ。"
fi

if [[ ! -f "${BASHRC}" ]] || ! grep -Fxq "${BB_LINE}" "${BASHRC}" 2>/dev/null; then
  printf '%s\n' "${BB_LINE}" >> "${BASHRC}"
  echo "追記: ${BASHRC} に ${BB_LINE}"
else
  echo "${BASHRC} に既に ${BB_LINE} があります。スキップ。"
fi

# bash junbi.sh / ./junbi.sh は子プロセスで動く。末尾の source はその子にしか効かず、
# いま入力している対話シェルにはエイリアスが伝わらない（手動 source と違う）。
# source junbi.sh のときだけ .bashrc を現在のシェルに読み込む。
if [[ -f "${BASHRC}" ]]; then
  if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
    # shellcheck source=/dev/null
    source "${BASHRC}"
    echo "反映: 現在のシェルに source ${BASHRC} しました（aa / bb が使えます）。"
  else
    echo "注意: この起動方法では .bashrc の source は子シェルにだけ効きます。プロンプト側には届きません。"
    echo "      このターミナルで aa / bb を使うには:  source ${BASHRC}"
    echo "      次回から一発で載せたい場合は:      source junbi.sh"
  fi
fi
