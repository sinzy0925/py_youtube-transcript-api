#!/usr/bin/env bash
# output/<接頭辞><番号>/ ごとに次のどちらかを処理する。
#   A) summary.txt がある → summary_<番号>.txt にリネームし、<接頭辞>summary/ にコピー
#   B) summary_<番号>.txt のみ（A 済み等）→ <接頭辞>summary/summary_<番号>.txt に上書きコピーのみ
# 接頭辞は末尾に _ を含める想定（例: output/yuji_fujiyama_）。
# *_summary ディレクトリや <接頭辞>summary は番号ディレクトリとして扱わない。
#
# 使い方: ./run_move_summary.sh output/yuji_fujiyama_

set -euo pipefail

usage() {
  echo "使い方: $0 <接頭辞パス>" >&2
  echo "  例:   $0 output/yuji_fujiyama_" >&2
  echo "  → summary.txt がある番号フォルダ: summary_<番号>.txt にリネームし _summary へコピー。" >&2
  echo "    summary_<番号>.txt のみのフォルダ: _summary へ上書きコピーのみ。" >&2
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

  _plain="${_d}/summary.txt"
  _named="${_d}/summary_${_suf}.txt"

  mkdir -p "${DEST}"
  if [[ -f "${_plain}" ]]; then
    cp -f "${_plain}" "${DEST}/summary_${_suf}.txt"
    mv -f "${_plain}" "${_named}"
    echo "OK: ${_plain} → ${_named} かつ ${DEST}/summary_${_suf}.txt"
    _matched=1
  elif [[ -f "${_named}" ]]; then
    cp -f "${_named}" "${DEST}/summary_${_suf}.txt"
    echo "OK: ${_named} を ${DEST}/summary_${_suf}.txt に上書きコピー"
    _matched=1
  else
    echo "スキップ（summary.txt / summary_${_suf}.txt ともなし）: ${_d}" >&2
    continue
  fi
done

if [[ "${_any}" -eq 0 ]]; then
  echo "エラー: パターンに一致するパスがありません: ${PREFIX}*" >&2
  exit 1
fi
if [[ "${_matched}" -eq 0 ]]; then
  echo "エラー: 番号付きディレクトリで summary.txt / summary_<番号>.txt のいずれも処理できませんでした（接頭辞: ${PREFIX}）。" >&2
  exit 1
fi
