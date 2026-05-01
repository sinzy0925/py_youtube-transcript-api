#!/usr/bin/env bash
# リポジトリルートで: チャンネル URL と --fromto で videoids.txt を更新する
#   ./run_channel.sh https://www.youtube.com/@ANNnewsCH --fromto 0:2
#
# --gopipeline … b01 のあと videoids.txt の各行を youtu.be URL にして run_pipeline.sh を順に起動する。
#   直前の run_pipeline.sh 起動時刻から次の起動まで最低 CHANNEL_PIPELINE_GAP_SEC 秒（既定 61）空ける。
#   （run_pipeline.sh は nohup で即終了するため、「起動間隔」による間引き）
#
# Windows (Git Bash) / WSL / Linux 共通: .venv の python を直接使用（activate 不要）

set -euo pipefail

usage() {
  echo "使い方: $0 <チャンネルURL> --fromto START:END [--gopipeline]" >&2
  echo "  例:   $0 'https://www.youtube.com/@ANNnewsCH' --fromto 0:2" >&2
  echo "  例:   $0 'https://www.youtube.com/@ANNnewsCH' --fromto 0:2 --gopipeline" >&2
  echo "  間隔: 環境変数 CHANNEL_PIPELINE_GAP_SEC（秒、既定 61）" >&2
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

GO_PIPELINE=0
B01_ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--gopipeline" ]]; then
    GO_PIPELINE=1
  else
    B01_ARGS+=("$arg")
  fi
done

if [[ "${#B01_ARGS[@]}" -lt 1 ]] || [[ -z "${B01_ARGS[0]:-}" ]]; then
  usage
fi

PYTHON_CMD_ARR=()
if [[ -n "${PYTHON:-}" ]]; then
  read -ra PYTHON_CMD_ARR <<< "${PYTHON}"
  if ! "${PYTHON_CMD_ARR[@]}" -c "import sys" 2>/dev/null; then
    echo "エラー: 指定の PYTHON= が import できません: ${PYTHON}" >&2
    exit 1
  fi
elif command -v py >/dev/null 2>&1 && py -3 -c "import sys" 2>/dev/null; then
  PYTHON_CMD_ARR=(py -3)
elif command -v python3 >/dev/null 2>&1 && python3 -c "import sys" 2>/dev/null; then
  PYTHON_CMD_ARR=(python3)
elif command -v python >/dev/null 2>&1 && python -c "import sys" 2>/dev/null; then
  PYTHON_CMD_ARR=(python)
else
  echo "エラー: 使える Python がありません。" >&2
  exit 1
fi

echo "使う Python: $("${PYTHON_CMD_ARR[@]}" -c "import sys; print(sys.executable)" 2>/dev/null || echo "${PYTHON_CMD_ARR[*]}")"

VENV_DIR="${VENV_DIR:-${ROOT}/.venv}"

_venv_python() {
  if [[ -f "${VENV_DIR}/Scripts/python.exe" ]]; then
    echo "${VENV_DIR}/Scripts/python.exe"
  elif [[ -f "${VENV_DIR}/bin/python" ]]; then
    echo "${VENV_DIR}/bin/python"
  elif [[ -f "${VENV_DIR}/bin/python3" ]]; then
    echo "${VENV_DIR}/bin/python3"
  else
    echo ""
  fi
}

if [[ ! -d "${VENV_DIR}" ]] || [[ -z "$(_venv_python)" ]]; then
  if [[ -d "${VENV_DIR}" ]]; then
    echo "既存の .venv を置き換えます: ${VENV_DIR}"
    rm -rf "${VENV_DIR}"
  else
    echo "仮想環境を作成: ${VENV_DIR}"
  fi
  if ! "${PYTHON_CMD_ARR[@]}" -m venv "${VENV_DIR}"; then
    echo "エラー: python -m venv に失敗しました。" >&2
    exit 1
  fi
fi

VENV_PY="$(_venv_python)"
if [[ -z "${VENV_PY}" ]]; then
  echo "エラー: 仮想環境内の python が見つかりません: ${VENV_DIR}" >&2
  exit 1
fi

echo "仮想環境の python: ${VENV_PY}"

_ensure_pip_in_venv() {
  if "${VENV_PY}" -m pip --version >/dev/null 2>&1; then
    return 0
  fi
  echo "仮想環境に pip がありません。bootstrap します..." >&2
  if "${VENV_PY}" -m ensurepip --upgrade >/dev/null 2>&1; then
    return 0
  fi
  local _gp
  _gp="$(mktemp)"
  if command -v curl >/dev/null 2>&1; then
    if ! curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "${_gp}"; then
      rm -f "${_gp}"
      return 1
    fi
  elif command -v wget >/dev/null 2>&1; then
    if ! wget -qO "${_gp}" https://bootstrap.pypa.io/get-pip.py; then
      rm -f "${_gp}"
      return 1
    fi
  else
    rm -f "${_gp}"
    echo "エラー: curl または wget が必要です。" >&2
    return 1
  fi
  if ! "${VENV_PY}" "${_gp}"; then
    rm -f "${_gp}"
    return 1
  fi
  rm -f "${_gp}"
}

if ! _ensure_pip_in_venv; then
  exit 1
fi

if ! "${VENV_PY}" -m pip install -q -r requirements.txt; then
  echo "エラー: pip install に失敗しました。" >&2
  exit 1
fi

echo "=== b01_channel_to_videoid: ${B01_ARGS[*]} ==="
if [[ "${GO_PIPELINE}" -eq 0 ]]; then
  exec "${VENV_PY}" -u "${ROOT}/b01_channel_to_videoid.py" "${B01_ARGS[@]}"
fi

if ! "${VENV_PY}" -u "${ROOT}/b01_channel_to_videoid.py" "${B01_ARGS[@]}"; then
  echo "エラー: b01_channel_to_videoid が失敗しました。" >&2
  exit 1
fi

VIDEOS_FILE="${ROOT}/videoids.txt"
if [[ ! -f "${VIDEOS_FILE}" ]]; then
  echo "エラー: ${VIDEOS_FILE} がありません（b01 が出力したはずです）。" >&2
  exit 1
fi

GAP_SEC="${CHANNEL_PIPELINE_GAP_SEC:-61}"
# 整数のみ許可（未設定・不正時は 61）
if ! [[ "${GAP_SEC}" =~ ^[0-9]+$ ]] || [[ "${GAP_SEC}" -lt 1 ]]; then
  GAP_SEC=61
fi

echo "=== --gopipeline: run_pipeline.sh を videoid ごとに起動（間隔 ${GAP_SEC}s） ==="

RUN_PIPELINE=(bash "${ROOT}/run_pipeline.sh")
last_start_sec=0
idx=0

while IFS= read -r line || [[ -n "${line}" ]]; do
  vid="${line//$'\r'/}"
  vid="${vid#"${vid%%[![:space:]]*}"}"
  vid="${vid%"${vid##*[![:space:]]}"}"
  [[ -z "${vid}" ]] && continue
  [[ "${vid}" == \#* ]] && continue

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
  url="https://youtu.be/${vid}"
  echo "=== [${idx}] ${RUN_PIPELINE[*]} ${url} （ログ: batch_channel_${vid}.log） ==="
  PIPELINE_LOG="${ROOT}/batch_channel_${vid}.log" "${RUN_PIPELINE[@]}" "${url}"
done < "${VIDEOS_FILE}"

if [[ "${idx}" -eq 0 ]]; then
  echo "エラー: ${VIDEOS_FILE} に有効な videoid がありません。" >&2
  exit 1
fi

echo "=== --gopipeline 完了: ${idx} 件の run_pipeline を起動しました ==="
