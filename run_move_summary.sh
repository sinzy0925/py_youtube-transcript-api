#!/usr/bin/env bash
# output/<接頭辞><番号>/summary.txt を
#   1) 同ディレクトリ内で summary_<番号>.txt にリネーム
#   2) <接頭辞>summary/summary_<番号>.txt にコピー
# 接頭辞は末尾に _ を含める想定（例: output/yuji_fujiyama_）。
# *_summary ディレクトリや <接頭辞>summary は番号ディレクトリとして扱わない。
#
# 使い方: ./run_move_summary.sh output/yuji_fujiyama_

set -euo pipefail

usage() {
  echo "使い方: $0 <接頭辞パス>" >&2
  echo "  例:   $0 output/yuji_fujiyama_" >&2
  echo "  → output/yuji_fujiyama_0/summary.txt … を summary_0.txt にリネームし、" >&2
  echo "    output/yuji_fujiyama_summary/summary_0.txt にコピー（番号付きディレクトリすべて）。" >&2
  exit 1
}

_script_path="${BASH_SOURCE[0]:-$0}"
while [[ -L "$_script_path" ]]; do
  _link_dir="$(cd "$(dirname "$_script_path")" && pwd -P)"
  _target="$(readlink "$_script_path")"
  if [[ "$_target" != /* ]]; then
    _target="${_link_dir}/${_target}"
  fi
  _script_path="$_target"
done
ROOT="$(cd -P "$(dirname "$_script_path")" && pwd)"
cd "$ROOT"

if [[ "${#}" -lt 1 ]] || [[ -z "${1:-}" ]]; then
  usage
fi

PREFIX="${1%/}"
DEST="${PREFIX}summary"

shopt -s nullglob
_matched=0
_any=0

for _d in "${PREFIX}"*; do
  [[ -e "${_d}" ]] || continue
  _any=1
  [[ -d "${_d}" ]] || continue
  _suf="${_d#"$PREFIX"}"
  [[ "${_suf}" =~ ^[0-9]+$ ]] || continue

  _src="${_d}/summary.txt"
  if [[ ! -f "${_src}" ]]; then
    echo "スキップ（summary.txt なし）: ${_d}" >&2
    continue
  fi

  mkdir -p "${DEST}"
  cp -f "${_src}" "${DEST}/summary_${_suf}.txt"
  mv -f "${_src}" "${_d}/summary_${_suf}.txt"
  echo "OK: ${_src} → ${_d}/summary_${_suf}.txt かつ ${DEST}/summary_${_suf}.txt"
  _matched=1
done

if [[ "${_any}" -eq 0 ]]; then
  echo "エラー: パターンに一致するパスがありません: ${PREFIX}*" >&2
  exit 1
fi
if [[ "${_matched}" -eq 0 ]]; then
  echo "エラー: 番号付きディレクトリで処理した summary.txt がありません（接頭辞: ${PREFIX}）。" >&2
  exit 1
fi
