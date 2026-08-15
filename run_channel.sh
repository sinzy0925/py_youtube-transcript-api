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
#   1 件のキュー処理が終わってから次を登録するまでの待機（起動同士の間隔ではない）。
# 成果物フォルダ: output/<チャンネルスラッグ>_<公開日YYYYMMDD>_<videoid>/
#   既に同 videoid の成果物（summary.txt 等）があればスキップ。
#   videoids.txt は b01 が videoid[TAB]YYYYMMDD で書く（公開日不明時は videoid のみ可）。
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
  echo "  間隔: CHANNEL_PIPELINE_GAP_SEC（秒、既定 61）※前件完了後→次件登録前の待機" >&2
  echo "  出力: output/<CHANNEL_OUTPUT_SLUG>_<公開日YYYYMMDD>_<videoid>/（取得済みはスキップ）" >&2
  echo "  出力名: CHANNEL_OUTPUT_SLUG（省略時は URL から @handle 等を推定）" >&2
  echo "  nohup ログ: CHANNEL_LOG（既定: リポジトリ直下 channel.log）" >&2
  exit 1
}

# チャンネル URL → ファイル名向けスラッグ（@handle /channel/ID /c/… 等）
_rc_channel_slug_from_url() {
  local u slug lc
  u="${1%%#*}"
  u="${u%%\?*}"
  u="${u%/}"
  u="${u#*://}"
  u="${u#www.}"
  u="${u#m.}"
  lc="$(printf '%s' "${u}" | tr '[:upper:]' '[:lower:]')"
  if [[ "${lc}" =~ ^youtube\.com/@([^/?#]+) ]]; then
    slug="${BASH_REMATCH[1]}"
  elif [[ "${lc}" =~ ^youtube\.com/channel/([^/?#]+) ]]; then
    slug="ch_${BASH_REMATCH[1]}"
  elif [[ "${lc}" =~ ^youtube\.com/c/([^/?#]+) ]]; then
    slug="${BASH_REMATCH[1]}"
  elif [[ "${lc}" =~ ^youtube\.com/user/([^/?#]+) ]]; then
    slug="${BASH_REMATCH[1]}"
  else
    slug="channel"
  fi
  slug="$(printf '%s' "${slug}" | LC_ALL=C tr -cs 'A-Za-z0-9_-' '_' | sed 's/^_\|_$//g')"
  [[ -z "${slug}" ]] && slug="channel"
  if [[ "${#slug}" -gt 80 ]]; then
    slug="${slug:0:80}"
  fi
  printf '%s' "${slug}"
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

# シェル未設定なら .env の CHANNEL_PIPELINE_GAP_SEC を使う
if [[ -z "${CHANNEL_PIPELINE_GAP_SEC:-}" ]] && [[ -f "${ROOT}/.env" ]]; then
  CHANNEL_PIPELINE_GAP_SEC="$("${VENV_PY}" -c "
from pathlib import Path
import sys
try:
    from dotenv import dotenv_values
    d = dotenv_values(Path(sys.argv[1]), encoding='utf-8-sig') or {}
    print((d.get('CHANNEL_PIPELINE_GAP_SEC') or '').strip())
except Exception:
    pass
" "${ROOT}/.env" 2>/dev/null || true)"
fi

GAP_SEC="${CHANNEL_PIPELINE_GAP_SEC:-61}"
# 0 以上の整数のみ許可（未設定・不正時は 61）
if ! [[ "${GAP_SEC}" =~ ^[0-9]+$ ]]; then
  GAP_SEC=61
fi

echo "=== パイプライン連続起動: run_pipeline.sh を videoid ごとに（前件完了後 ${GAP_SEC}s 待機） ==="

if [[ -n "${CHANNEL_OUTPUT_SLUG:-}" ]]; then
  _rc_ch_slug="${CHANNEL_OUTPUT_SLUG}"
else
  _rc_ch_slug="$(_rc_channel_slug_from_url "${PASS_ARGS[0]}")"
fi
echo "出力フォルダ: output/${_rc_ch_slug}_<公開日YYYYMMDD>_<videoid>/ （取得済み videoid はスキップ）"

# execute_urls キューが空かつワーカー未稼働になるまで待つ（1 件完了の合図）
_rc_wait_execute_queue_idle() {
  local _tick=0
  local _f="${ROOT}/execute_urls.txt"
  local _lock_d="${ROOT}/execute_urls.lock.d"
  echo "=== 前件のキュー処理完了を待機 ==="
  while true; do
    local _pending=0
    if [[ -f "${_f}" ]]; then
      while IFS= read -r _line || [[ -n "${_line}" ]]; do
        _line="${_line//$'\r'/}"
        _line="${_line#"${_line%%[![:space:]]*}"}"
        _line="${_line%"${_line##*[![:space:]]}"}"
        [[ -z "${_line}" ]] && continue
        [[ "${_line}" == \#* ]] && continue
        _pending=1
        break
      done < "${_f}"
    fi
    if [[ "${_pending}" -eq 0 ]] && [[ ! -d "${_lock_d}" ]]; then
      break
    fi
    _tick=$((_tick + 1))
    if [[ $((_tick % 4)) -eq 0 ]]; then
      echo "  待機中…（キュー処理の完了を待っています）"
    fi
    sleep 5
  done
  echo "=== 前件のキュー処理完了 ==="
}

# 既に同 videoid の成果物があればスキップ（旧 ga-ko_N 形式も含む）
_rc_already_have_videoid() {
  local _vid="$1"
  "${VENV_PY}" -c "
from pathlib import Path
import json
import sys
vid = sys.argv[1]
root = Path(sys.argv[2])
if not root.is_dir():
    raise SystemExit(1)
for child in root.iterdir():
    if not child.is_dir():
        continue
    name = child.name
    has_summary = (child / 'summary.txt').is_file()
    has_info = (child / 'video_info.json').is_file()
    if name == vid or name.endswith('_' + vid):
        if has_summary or has_info:
            print(str(child))
            raise SystemExit(0)
    if has_info:
        try:
            data = json.loads((child / 'video_info.json').read_text(encoding='utf-8'))
        except Exception:
            continue
        if str(data.get('video_id') or '').strip() == vid and has_summary:
            print(str(child))
            raise SystemExit(0)
raise SystemExit(1)
" "${_vid}" "${ROOT}/output" 2>/dev/null
}

# 公開日が無い行向け: yt-dlp で YYYYMMDD を取る（失敗時は空）
_rc_fetch_upload_date() {
  local _vid="$1"
  "${VENV_PY}" -c "
from b01_channel_to_videoid import fetch_upload_date
import sys
print(fetch_upload_date(sys.argv[1]), end='')
" "${_vid}" 2>/dev/null || true
}

RUN_PIPELINE=(bash "${ROOT}/run_pipeline.sh")
seen=0
ran=0
skipped=0

while IFS= read -r line || [[ -n "${line}" ]]; do
  line="${line//$'\r'/}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  [[ -z "${line}" ]] && continue
  [[ "${line}" == \#* ]] && continue

  vid=""
  pub_date=""
  if [[ "${line}" == *$'\t'* ]]; then
    vid="${line%%$'\t'*}"
    pub_date="${line#*$'\t'}"
  elif [[ "${line}" == *' '* ]]; then
    # 互換: 空白区切り videoid YYYYMMDD
    vid="${line%% *}"
    pub_date="${line#* }"
  else
    vid="${line}"
  fi
  vid="${vid#"${vid%%[![:space:]]*}"}"
  vid="${vid%"${vid##*[![:space:]]}"}"
  pub_date="${pub_date#"${pub_date%%[![:space:]]*}"}"
  pub_date="${pub_date%"${pub_date##*[![:space:]]}"}"
  [[ -z "${vid}" ]] && continue
  seen=$((seen + 1))

  if ! [[ "${pub_date}" =~ ^[0-9]{8}$ ]]; then
    pub_date="$(_rc_fetch_upload_date "${vid}")"
  fi
  if ! [[ "${pub_date}" =~ ^[0-9]{8}$ ]]; then
    pub_date="$(date +%Y%m%d)"
    echo "警告: ${vid} の公開日が取れないため実行日 ${pub_date} を使います" >&2
  fi

  _rc_out="output/${_rc_ch_slug}_${pub_date}_${vid}"
  _rc_log="batch_channel_${_rc_ch_slug}_${pub_date}_${vid}.log"

  if _existing="$(_rc_already_have_videoid "${vid}")"; then
    echo "=== スキップ（取得済み）: ${vid} （既存: ${_existing}） → 予定 ${_rc_out}/ ==="
    skipped=$((skipped + 1))
    continue
  fi

  # 実際に処理する件のあいだだけ待機（スキップは間隔に含めない）
  if [[ "${ran}" -gt 0 ]] && [[ "${GAP_SEC}" -gt 0 ]]; then
    echo "間隔: ${GAP_SEC}秒待機（前件完了後 → 次件登録前）"
    sleep "${GAP_SEC}"
  fi

  url="https://youtu.be/${vid}"
  echo "=== ${RUN_PIPELINE[*]} ${url} → ${_rc_out}/ （ログ: ${_rc_log}） ==="
  PIPELINE_SKIP_BUILD_HTML=1 \
    PIPELINE_LOG="${ROOT}/${_rc_log}" \
    PIPELINE_OUTPUT_DIR="${_rc_out}" \
    "${RUN_PIPELINE[@]}" "${url}"
  # キュー登録は即戻るため、当該件の処理完了まで待つ
  _rc_wait_execute_queue_idle
  ran=$((ran + 1))
done < "${VIDEOS_FILE}"

if [[ "${seen}" -eq 0 ]]; then
  echo "エラー: ${VIDEOS_FILE} に有効な videoid がありません。" >&2
  exit 1
fi

if [[ "${ran}" -gt 0 ]] && [[ -n "${BUILD_HTML_SITE:-}" ]] && [[ "${BUILD_HTML_SITE}" != "0" ]]; then
  echo "=== チャンネル一括: キュー完了待ち → docs/ を1回生成 ==="
  bash "${ROOT}/run_pipeline.sh" --finish-urls-batch-html
elif [[ "${ran}" -eq 0 ]] && [[ "${skipped}" -gt 0 ]]; then
  echo "=== 全件スキップのため docs/ 再生成は行いません（必要なら python build_html_site.py） ==="
fi

echo "=== パイプライン連続起動 完了: 処理 ${ran} 件 / スキップ ${skipped} 件 / 対象 ${seen} 件 ==="
