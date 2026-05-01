#!/usr/bin/env bash
# チャンネル URL と --fromto で videoids.txt を更新し、既定では続けて run_pipeline.sh を各 videoid で実行し、
# その処理全体を nohup でバックグラウンド起動する（Cloud Shell で切断後も続行）。
#   ./run_channel.sh 'https://www.youtube.com/@ANNnewsCH' --fromto 0:2
#   ./run_channel.sh --fromto 0:2 --url 'https://www.youtube.com/@ANNnewsCH'
#
# 明示フラグ（既定と同じなら省略可）: --gopipeline（既定 ON）、--nohup（既定 ON）
#
# --no-gopipeline … b01 と videoids.txt のみ（パイプライン連続はしない）
# --foreground | --no-nohup … フォアグラウンド実行（nohup しない）
#
# run_pipeline 間隔: CHANNEL_PIPELINE_GAP_SEC（秒、既定 61）。
# 起動直後（外側プロセスのみ）: リポジトリ直下の *.log を削除してから処理する。
#
# Windows (Git Bash) / WSL / Linux 共通: .venv の python を直接使用（activate 不要）

set -euo pipefail

usage() {
  echo "使い方: $0 <チャンネルURL> --fromto START:END [オプション]" >&2
  echo "     または: $0 --fromto START:END --url <チャンネルURL> [オプション]" >&2
  echo "  既定: パイプライン連続起動（旧 --gopipeline）＋ nohup ログ出力（旧 --nohup）" >&2
  echo "  例:   $0 'https://www.youtube.com/@ANNnewsCH' --fromto 0:2" >&2
  echo "  例:   $0 --fromto 0:2 --url 'https://www.youtube.com/@ANNnewsCH'" >&2
  echo "  明示: $0 '…' --fromto 0:2 --gopipeline --nohup （既定と同じで省略可）" >&2
  echo "  videoids のみ: $0 '…' --fromto 0:2 --no-gopipeline" >&2
  echo "  フォアグラウンド: $0 '…' --fromto 0:2 --foreground" >&2
  echo "  間隔: CHANNEL_PIPELINE_GAP_SEC（秒、既定 61）" >&2
  echo "  nohup ログ: CHANNEL_LOG（既定: リポジトリ直下 channel.log）" >&2
  exit 1
}

# PASS_ARGS を「チャンネルURL・--fromto・メタフラグ」に正規化（順不同可）。
# 出力: PASS_ARGS=( URL --fromto RANGE [--no-gopipeline] ... )
_rc_normalize_pass_args() {
  local -a raw=("${PASS_ARGS[@]}")
  local -a meta=()
  local url_opt="" fromto_val="" pos_url=""
  local i=0 n=${#raw[@]}

  while [[ "${i}" -lt "${n}" ]]; do
    local a="${raw[$i]}"
    case "${a}" in
      --no-gopipeline | --foreground | --no-nohup)
        meta+=("${a}")
        i=$((i + 1))
        ;;
      --url)
        i=$((i + 1))
        if [[ "${i}" -ge "${n}" ]]; then
          echo "エラー: --url の後に URL がありません。" >&2
          return 1
        fi
        if [[ -n "${url_opt}" ]]; then
          echo "エラー: --url は1回だけ指定してください。" >&2
          return 1
        fi
        url_opt="${raw[$i]}"
        i=$((i + 1))
        ;;
      --fromto)
        i=$((i + 1))
        if [[ "${i}" -ge "${n}" ]]; then
          echo "エラー: --fromto の後に START:END がありません。" >&2
          return 1
        fi
        if [[ -n "${fromto_val}" ]]; then
          echo "エラー: --fromto は1回だけ指定してください。" >&2
          return 1
        fi
        fromto_val="${raw[$i]}"
        i=$((i + 1))
        ;;
      -*)
        echo "エラー: 不明なオプション: ${a}" >&2
        return 1
        ;;
      *)
        if [[ -z "${pos_url}" ]]; then
          pos_url="${a}"
        else
          echo "エラー: チャンネル URL は1つだけ指定してください（余分: ${a}）。" >&2
          return 1
        fi
        i=$((i + 1))
        ;;
    esac
  done

  if [[ -n "${url_opt}" && -n "${pos_url}" ]]; then
    echo "エラー: --url と位置引数の URL を同時に指定できません。" >&2
    return 1
  fi
  local chan="${url_opt:-${pos_url}}"
  if [[ -z "${chan}" ]]; then
    echo "エラー: チャンネル URL を指定してください（位置引数または --url）。" >&2
    return 1
  fi
  if [[ -z "${fromto_val}" ]]; then
    echo "エラー: --fromto START:END を指定してください。" >&2
    return 1
  fi

  PASS_ARGS=("${chan}" "--fromto" "${fromto_val}" "${meta[@]}")
  return 0
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

# リポジトリ直下の *.log を削除（batch*.log / channel.log 等）。
# nohup の子プロセスでは、リダイレクト先の channel.log を消さないようスキップする。
if [[ -z "${RUN_CHANNEL_NOHUP_CHILD:-}" ]]; then
  shopt -s nullglob
  _rc_logs=(./*.log)
  if [[ "${#_rc_logs[@]}" -gt 0 ]]; then
    rm -f "${_rc_logs[@]}"
  fi
  shopt -u nullglob
fi

GO_PIPELINE=1
GO_NOHUP=1
PASS_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --gopipeline) ;;
    --no-gopipeline)
      GO_PIPELINE=0
      PASS_ARGS+=("$arg")
      ;;
    --nohup) ;;
    --foreground | --no-nohup)
      GO_NOHUP=0
      PASS_ARGS+=("$arg")
      ;;
    *)
      PASS_ARGS+=("$arg")
      ;;
  esac
done

if [[ "${#PASS_ARGS[@]}" -lt 1 ]]; then
  usage
fi

if ! _rc_normalize_pass_args; then
  exit 2
fi

if [[ "${#PASS_ARGS[@]}" -lt 1 ]] || [[ -z "${PASS_ARGS[0]:-}" ]]; then
  usage
fi

B01_ARGS=()
for arg in "${PASS_ARGS[@]}"; do
  case "$arg" in
    --no-gopipeline | --foreground | --no-nohup) ;;
    *) B01_ARGS+=("$arg") ;;
  esac
done

# 外側を nohup 化（venv より前）。nohup が無い環境ではフォアグラウンドへ。
if [[ "${GO_NOHUP}" -eq 1 ]] && [[ -z "${RUN_CHANNEL_NOHUP_CHILD:-}" ]]; then
  if ! command -v nohup >/dev/null 2>&1; then
    echo "警告: nohup が無いためフォアグラウンドで実行します（Linux / Cloud Shell では通常 nohup があります）。" >&2
    GO_NOHUP=0
  fi
fi

if [[ "${GO_NOHUP}" -eq 1 ]] && [[ -z "${RUN_CHANNEL_NOHUP_CHILD:-}" ]]; then
  LOG_FILE="${CHANNEL_LOG:-${ROOT}/channel.log}"
  nohup env RUN_CHANNEL_NOHUP_CHILD=1 bash "${ROOT}/run_channel.sh" "${PASS_ARGS[@]}" >"${LOG_FILE}" 2>&1 &
  _rc_pid=$!
  echo "nohup 起動しました PID=${_rc_pid}" >&2
  echo "ログ: ${LOG_FILE} （確認例: tail -f ${LOG_FILE}）" >&2
  exit 0
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

echo "=== パイプライン連続起動: run_pipeline.sh を videoid ごとに（間隔 ${GAP_SEC}s） ==="

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

echo "=== パイプライン連続起動 完了: ${idx} 件の run_pipeline を起動しました ==="
