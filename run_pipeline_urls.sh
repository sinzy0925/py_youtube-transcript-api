#!/usr/bin/env bash
# urls.txt（1行1URL）を上から順に run_pipeline.sh で処理する。
# 直前の run_pipeline の起動から URLS_PIPELINE_GAP_SEC 秒あけてから次を起動（既定 65）。
#
#   ./run_pipeline_urls.sh
#   ./run_pipeline_urls.sh ~/my_urls.txt
#
# Windows (Git Bash) / WSL / Linux / Cloud Shell 共通

set -euo pipefail

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

usage() {
  echo "使い方: $0 [URLリストファイル]" >&2
  echo "  既定のリスト: ${ROOT}/urls.txt" >&2
  echo "  1行1URL。空行と # で始まる行は無視。" >&2
  echo "  間隔: 環境変数 URLS_PIPELINE_GAP_SEC（秒、既定 65）※各 run_pipeline 起動の間" >&2
  exit 1
}

case "${1:-}" in
-h | --help) usage ;;
esac

URLS_FILE="${1:-${ROOT}/urls.txt}"
if [[ ! -f "${URLS_FILE}" ]]; then
  echo "エラー: リストファイルがありません: ${URLS_FILE}" >&2
  exit 1
fi

GAP_SEC="${URLS_PIPELINE_GAP_SEC:-65}"
if ! [[ "${GAP_SEC}" =~ ^[0-9]+$ ]] || [[ "${GAP_SEC}" -lt 1 ]]; then
  echo "エラー: URLS_PIPELINE_GAP_SEC は 1 以上の整数にしてください（現在: ${URLS_PIPELINE_GAP_SEC:-未設定}）" >&2
  exit 1
fi

if [[ ! -f "${ROOT}/run_pipeline.sh" ]]; then
  echo "エラー: run_pipeline.sh が見つかりません: ${ROOT}/run_pipeline.sh" >&2
  exit 1
fi
RUN_PIPELINE=(bash "${ROOT}/run_pipeline.sh")

echo "=== URL リスト連続起動（間隔 ${GAP_SEC}s）: ${URLS_FILE} → run_pipeline.sh ==="

last_start_sec=0
idx=0

while IFS= read -r line || [[ -n "${line}" ]]; do
  url="${line//$'\r'/}"
  url="${url#"${url%%[![:space:]]*}"}"
  url="${url%"${url##*[![:space:]]}"}"
  [[ -z "${url}" ]] && continue
  [[ "${url}" == \#* ]] && continue

  idx=$((idx + 1))
  now_sec="$(date +%s)"
  if [[ "${last_start_sec}" -gt 0 ]]; then
    elapsed=$((now_sec - last_start_sec))
    if [[ "${elapsed}" -lt "${GAP_SEC}" ]]; then
      sleep_sec=$((GAP_SEC - elapsed))
      echo "間隔: ${sleep_sec}秒待機（直前の run_pipeline 起動から ${GAP_SEC}秒以上）"
      sleep "${sleep_sec}"
    fi
  fi

  last_start_sec="$(date +%s)"
  # 連番ログ（run_pipeline.sh の既定 batch1.log と衝突しない）
  PIPELINE_LOG="${ROOT}/batch_urls_${idx}.log"
  echo "=== [${idx}] ${RUN_PIPELINE[*]} （ログ: batch_urls_${idx}.log） ==="
  echo "${url}"
  PIPELINE_LOG="${PIPELINE_LOG}" "${RUN_PIPELINE[@]}" "${url}"
done < "${URLS_FILE}"

if [[ "${idx}" -eq 0 ]]; then
  echo "エラー: ${URLS_FILE} に有効な URL がありません。" >&2
  exit 1
fi

echo "=== URL リスト連続起動 完了: ${idx} 件の run_pipeline を起動しました ==="
