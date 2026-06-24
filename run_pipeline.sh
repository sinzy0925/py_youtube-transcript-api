#!/usr/bin/env bash
# リポジトリルートで: URL だけ渡してパイプライン実行（.venv を作り requirements を入れる）
#   ./run_pipeline.sh "https://youtu.be/xxxx?si=..."
#
# Windows (Git Bash) / WSL / Linux 共通: activate の source に依存せず
#   .venv/Scripts/python.exe または .venv/bin/python を直接使う
#
# API キー / メール: リポジトリの .env をシェルに取り込んでから a05 の引数（--skip-email）を決める
#
# 実行例: ./run_pipeline.sh 'https://youtu.be/...'
#   urls.txt へ追記（--retry 用）。execute_urls.txt へ追記し、キューを上から直列実行（完了後に先頭行削除）。
#   複数回連続実行してもプロンプトはすぐ戻る（ワーカーが 1 本だけ直列処理）。
#   ./run_pipeline.sh --retry [N] … urls.txt から再実行（キューに入れない）
# 並列用: ./run_pipeline1.sh URL … ./run_pipeline5.sh URL（batch1.log…batch5.log、c.f. PIPELINE_SLOT）
#
# 環境変数 PIPELINE_OUTPUT_DIR … 設定時は a05 に -o として渡す（成果物ディレクトリ）。未設定時は a05 既定（日時_<id短縮>）。

set -euo pipefail

usage() {
  echo "使い方: $0 <YouTube_URL_または_video_id>" >&2
  echo "       $0 --retry [N]  （省略時 N=1＝最新、2 がその 1 つ前 …）" >&2
  echo "  例:   $0 'https://youtu.be/2UF8PHOIfrI?si=xxxx'" >&2
  echo "  通常実行時、urls.txt と execute_urls.txt に追記し、キューを直列処理します。" >&2
  echo "  --retry [N] … urls.txt から再実行（キューに入れず即時 1 件）。" >&2
  echo "  --finish-urls-batch-html … run_pipeline_urls.sh 用。キュー完了後に docs/ を1回生成（要 BUILD_HTML_SITE）。" >&2
  exit 1
}

# urls.txt の末尾から N 番目の有効行を返す（N=1 が最新。空行・# は除外）
_urls_txt_entry_from_end() {
  local _f="$1" _n="$2" _line
  local -a _entries=()
  if [[ ! -f "${_f}" ]] || ! [[ "${_n}" =~ ^[1-9][0-9]*$ ]]; then
    return 1
  fi
  while IFS= read -r _line || [[ -n "${_line}" ]]; do
    _line="${_line//$'\r'/}"
    _line="${_line#"${_line%%[![:space:]]*}"}"
    _line="${_line%"${_line##*[![:space:]]}"}"
    [[ -z "${_line}" ]] && continue
    [[ "${_line}" == \#* ]] && continue
    _entries+=("${_line}")
  done < "${_f}"
  if [[ "${#_entries[@]}" -lt "${_n}" ]]; then
    return 1
  fi
  printf '%s' "${_entries[$(( ${#_entries[@]} - _n ))]}"
}

_append_urls_txt() {
  local _url="$1"
  printf '%s\n' "${_url}" >>"${URLS_TXT}"
  echo "追記: ${URLS_TXT}" >&2
}

_execute_urls_trim_line() {
  local _line="$1"
  _line="${_line//$'\r'/}"
  _line="${_line#"${_line%%[![:space:]]*}"}"
  _line="${_line%"${_line##*[![:space:]]}"}"
  printf '%s' "${_line}"
}

_append_execute_urls_txt() {
  local _url="$1"
  printf '%s\n' "${_url}" >>"${EXECUTE_URLS_TXT}"
  echo "キュー追記: ${EXECUTE_URLS_TXT}" >&2
}

# 先頭の有効行（空行・# 除く）を表示
_execute_urls_peek_first() {
  local _f="$1" _line _t
  [[ -f "${_f}" ]] || return 1
  while IFS= read -r _line || [[ -n "${_line}" ]]; do
    _t="$(_execute_urls_trim_line "${_line}")"
    [[ -z "${_t}" ]] && continue
    [[ "${_t}" == \#* ]] && continue
    printf '%s' "${_t}"
    return 0
  done <"${_f}"
  return 1
}

# 先頭の有効行を 1 行削除（残りを書き戻す）
_execute_urls_pop_first() {
  local _f="$1" _line _t _tmp _popped=0
  [[ -f "${_f}" ]] || return 0
  _tmp="$(mktemp "${_f}.XXXXXX")"
  while IFS= read -r _line || [[ -n "${_line}" ]]; do
    _t="$(_execute_urls_trim_line "${_line}")"
    if [[ "${_popped}" -eq 0 ]]; then
      if [[ -z "${_t}" ]] || [[ "${_t}" == \#* ]]; then
        continue
      fi
      _popped=1
      continue
    fi
    printf '%s\n' "${_line}" >>"${_tmp}"
  done <"${_f}"
  if [[ "${_popped}" -eq 1 ]]; then
    mv -f "${_tmp}" "${_f}"
  else
    rm -f "${_tmp}"
    : >"${_f}"
  fi
}

_execute_urls_has_pending() {
  _execute_urls_peek_first "${EXECUTE_URLS_TXT}" >/dev/null 2>&1
}

_is_execute_queue_worker_active() {
  [[ -d "${EXECUTE_QUEUE_LOCK_DIR}" ]]
}

_wait_execute_queue_idle() {
  echo "=== execute_urls キュー完了を待機 ===" >&2
  local _tick=0
  while _execute_urls_has_pending || _is_execute_queue_worker_active; do
    _tick=$((_tick + 1))
    if [[ $((_tick % 4)) -eq 0 ]]; then
      echo "  待機中…（キュー処理の完了を待っています）" >&2
    fi
    sleep 15
  done
  echo "=== execute_urls キュー待機完了 ===" >&2
}

# シンボリックリンク経由（例: ~/run_pipeline.sh → リポジトリ内）でもリポジトリルートに cd する
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
URLS_TXT="${ROOT}/urls.txt"
EXECUTE_URLS_TXT="${ROOT}/execute_urls.txt"
EXECUTE_QUEUE_LOCK="${ROOT}/execute_urls.lock"
EXECUTE_QUEUE_LOCK_DIR="${ROOT}/execute_urls.lock.d"
EXECUTE_QUEUE_LOG="${ROOT}/execute_queue.log"
EXECUTE_QUEUE_LOCK_MODE=""
RUN_PIPELINE_SELF="${ROOT}/$(basename "${_script_path}")"

# ログ: 環境変数 PIPELINE_LOG で直指定。PIPELINE_SLOT=1..5 で batch{1..5}.log（並列で log 衝突を避ける）
if [[ -n "${PIPELINE_LOG:-}" ]]; then
  :
elif [[ -n "${PIPELINE_SLOT:-}" ]] && [[ "${PIPELINE_SLOT}" =~ ^[1-5]$ ]]; then
  PIPELINE_LOG="${ROOT}/batch${PIPELINE_SLOT}.log"
else
  PIPELINE_LOG="${ROOT}/batch1.log"
fi

RETRY_N=0
QUEUE_DRAIN=0
FINISH_URLS_BATCH_HTML=0
VIDEO_REF=""
while [[ "${#}" -gt 0 ]]; do
  case "${1}" in
    --drain-execute-queue)
      QUEUE_DRAIN=1
      shift
      ;;
    --finish-urls-batch-html)
      FINISH_URLS_BATCH_HTML=1
      shift
      ;;
    --retry)
      shift
      _retry_arg="${1:-}"
      if [[ -z "${_retry_arg}" ]]; then
        RETRY_N=1
      else
        _retry_arg="${_retry_arg#\"}"
        _retry_arg="${_retry_arg%\"}"
        if ! [[ "${_retry_arg}" =~ ^[1-9][0-9]*$ ]]; then
          echo "エラー: --retry の番号は 1 以上の整数にしてください（例: $0 --retry 1）" >&2
          exit 1
        fi
        RETRY_N="${_retry_arg}"
        shift
      fi
      ;;
    -h | --help)
      usage
      ;;
    -*)
      echo "エラー: 不明なオプション: ${1}" >&2
      usage
      ;;
    *)
      if [[ -n "${VIDEO_REF}" ]]; then
        echo "エラー: URL は 1 つだけ指定してください。" >&2
        usage
      fi
      VIDEO_REF="${1}"
      shift
      ;;
  esac
done

if [[ "${QUEUE_DRAIN}" -eq 1 ]] && [[ -n "${VIDEO_REF}" ]]; then
  echo "エラー: --drain-execute-queue に URL 引数は付けられません。" >&2
  exit 1
fi

if [[ "${FINISH_URLS_BATCH_HTML}" -eq 1 ]]; then
  if [[ -n "${VIDEO_REF}" ]] || [[ "${RETRY_N}" -gt 0 ]] || [[ "${QUEUE_DRAIN}" -eq 1 ]]; then
    echo "エラー: --finish-urls-batch-html に URL や他のモード引数は付けられません。" >&2
    exit 1
  fi
fi

if [[ "${RETRY_N}" -gt 0 ]]; then
  if [[ -n "${VIDEO_REF}" ]]; then
    echo "エラー: --retry ${RETRY_N} のとき URL 引数は不要です。" >&2
    exit 1
  fi
  if ! VIDEO_REF="$(_urls_txt_entry_from_end "${URLS_TXT}" "${RETRY_N}")"; then
    echo "エラー: urls.txt に末尾から ${RETRY_N} 番目の URL がありません: ${URLS_TXT}" >&2
    exit 1
  fi
  echo "再実行（urls.txt の末尾から ${RETRY_N} 番目）: ${VIDEO_REF}" >&2
elif [[ "${QUEUE_DRAIN}" -eq 0 ]] && [[ "${FINISH_URLS_BATCH_HTML}" -eq 0 ]]; then
  if [[ -z "${VIDEO_REF}" ]]; then
    usage
  fi
  _append_urls_txt "${VIDEO_REF}"
  _append_execute_urls_txt "${VIDEO_REF}"
fi

# 動作する Python を選ぶ（Windows の「python3」が Store スタブで venv 失敗する件は py -3 で回避）
PYTHON_CMD_ARR=()
if [[ -n "${PYTHON:-}" ]]; then
  # 例: PYTHON="py -3" やフルパス
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
  echo "エラー: 使える Python がありません。py -3 または python3 / python（import 可）を用意してください。" >&2
  exit 1
fi

# バージョン表示（診断用）
echo "使う Python: $("${PYTHON_CMD_ARR[@]}" -c "import sys; print(sys.executable)" 2>/dev/null || echo "${PYTHON_CMD_ARR[*]}")"

VENV_DIR="${VENV_DIR:-${ROOT}/.venv}"

# 仮想環境内の python のパス（source activate を使わない）
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

# venv が無いか中身が壊れていれば作り直す
if [[ ! -d "${VENV_DIR}" ]] || [[ -z "$(_venv_python)" ]]; then
  if [[ -d "${VENV_DIR}" ]]; then
    echo "既存の .venv を置き換えます: ${VENV_DIR}"
    rm -rf "${VENV_DIR}"
  else
    echo "仮想環境を作成: ${VENV_DIR}"
  fi
  if ! "${PYTHON_CMD_ARR[@]}" -m venv "${VENV_DIR}"; then
    echo "エラー: python -m venv に失敗しました。Python をインストールしたか確認してください。" >&2
    exit 1
  fi
fi

VENV_PY="$(_venv_python)"
if [[ -z "${VENV_PY}" ]]; then
  echo "エラー: 仮想環境内の python が見つかりません: ${VENV_DIR}" >&2
  exit 1
fi

echo "仮想環境の python: ${VENV_PY}"

# 既存 .venv に pip が無い場合（Cloud Shell / Debian 系の venv、--without-pip など）
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
    echo "エラー: pip を入れるには curl または wget が必要です。または rm -rf .venv して python3 -m venv をやり直してください。" >&2
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

# pip も仮想環境の python 経由（PATH に依存しない）
if ! "${VENV_PY}" -m pip install -q -r requirements.txt; then
  echo "エラー: pip install に失敗しました。" >&2
  exit 1
fi

# プロジェクトの .env をシェル環境に反映（a05 より前に MAIL_TO 等を見える化）
# ※ 値は Python shlex でエスケープ（BOM/CRLF 可。python-dotenv 優先、失敗時は行パース）
# ※ 変数名にハイフン等がある行（例: my-api-key）は bash の export 不可のためスキップ。
#    その値は a05 / a01 の load_dotenv でそのまま読み込まれます。
if [[ -f "${ROOT}/.env" ]]; then
  set +e
  # shellcheck disable=SC2016,SC1090,SC2046,SC2086
  _env_exports="$(
    "${VENV_PY}" - "${ROOT}" <<'PY'
import re
import shlex
import sys
from pathlib import Path

# bash の export 名は [A-Za-z_][A-Za-z0-9_]* のみ（ハイフン付き名は不可）。
# それ以外は Python 側の load_dotenv で読めるため、ここではスキップする。
_BASH_EXPORTABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _bash_export_line(key: str, val: str):
    k = key.strip()
    if not k or k.startswith("#") or not _BASH_EXPORTABLE.match(k):
        return None
    return "export " + k + "=" + shlex.quote(val)


root = Path(sys.argv[1])
p = root / ".env"
if not p.is_file():
    sys.exit(0)
out: list[str] = []
try:
    from dotenv import dotenv_values

    d = dotenv_values(p, encoding="utf-8-sig")
    for k, v in (d or {}).items():
        if v is None or not str(k).strip():
            continue
        k = str(k).strip()
        if not k or k.startswith("#"):
            continue
        line = _bash_export_line(k, str(v))
        if line:
            out.append(line)
except Exception:
    try:
        text = p.read_text(encoding="utf-8-sig")
    except OSError:
        sys.exit(0)
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k, v = k.strip(), v.rstrip()
        if not k:
            continue
        v = v.strip()
        if len(v) >= 2 and v[0] in "\"'" and v[0] == v[-1]:
            v = v[1:-1]
        ex = _bash_export_line(k, v)
        if ex:
            out.append(ex)
for L in out:
    print(L)
PY
  )"
  _py_env_ec=$?
  set -e
  if [[ "${_py_env_ec}" -ne 0 ]]; then
    echo "警告: .env の展開に失敗 (exit ${_py_env_ec})。a05 側の load_dotenv に任せます。" >&2
  elif [[ -n "${_env_exports}" ]]; then
    eval "$_env_exports"
    echo "読み取り: ${ROOT}/.env → シェル環境に反映（--skip-email 判定用）"
  fi
fi

ARGS=(a05_pipeline_youtube_to_email.py)
if [[ -n "${PIPELINE_OUTPUT_DIR:-}" ]]; then
  ARGS+=(-o "${PIPELINE_OUTPUT_DIR}")
fi
if [[ -z "${MAIL_TO:-}" ]] && [[ -z "${TO_EMAIL:-}" ]]; then
  ARGS+=(--skip-email)
else
  echo "メール送信: MAIL_TO または TO_EMAIL が設定されているため --skip-email しません"
fi
if [[ "${PIPELINE_SKIP_BUILD_HTML:-}" != "1" ]] && [[ -n "${BUILD_HTML_SITE:-}" ]] && [[ "${BUILD_HTML_SITE}" != "0" ]]; then
  ARGS+=(--build-html)
  echo "HTML サイト: BUILD_HTML_SITE が有効のため --build-html を付与します"
fi

if [[ "${FINISH_URLS_BATCH_HTML}" -eq 1 ]]; then
  if [[ -z "${BUILD_HTML_SITE:-}" ]] || [[ "${BUILD_HTML_SITE}" == "0" ]]; then
    echo "BUILD_HTML_SITE 未設定のため docs 生成をスキップします。" >&2
    exit 0
  fi
  _wait_execute_queue_idle
  echo "=== docs/ 静的サイト生成（URLリスト一括完了後） ===" >&2
  if ! "${VENV_PY}" -u build_html_site.py; then
    echo "エラー: build_html_site.py に失敗しました。" >&2
    exit 1
  fi
  exit 0
fi

_log_dir="$(dirname "${PIPELINE_LOG}")"
if [[ ! -d "${_log_dir}" ]]; then
  mkdir -p "${_log_dir}"
fi

# 1 件を起動して終了まで待つ（キュー直列用）
_run_pipeline_wait() {
  local _url="$1"
  echo "=== パイプライン実行（直列・完了待ち）: ${_url} ===" >&2
  if ! "${VENV_PY}" -u "${ARGS[@]}" "${_url}" >"${PIPELINE_LOG}" 2>&1; then
    echo "警告: パイプライン終了コード非0: ${_url} （ログ: ${PIPELINE_LOG}）" >&2
    return 1
  fi
  return 0
}

# --retry など即時 1 件（従来どおりバックグラウンド）
_run_pipeline_background() {
  local _url="$1"
  echo "=== パイプライン実行: ${_url} ===" >&2
  if command -v nohup >/dev/null 2>&1; then
    echo "nohup バックグラウンド: ログ → ${PIPELINE_LOG}（python -u）" >&2
    nohup "${VENV_PY}" -u "${ARGS[@]}" "${_url}" >"${PIPELINE_LOG}" 2>&1 &
    echo "起動しました PID $!。進捗: cat ${PIPELINE_LOG}" >&2
    return 0
  fi
  echo "注意: nohup がありません。バックグラウンド起動 → ${PIPELINE_LOG}" >&2
  "${VENV_PY}" -u "${ARGS[@]}" "${_url}" >"${PIPELINE_LOG}" 2>&1 &
  echo "起動しました PID $!。進捗: cat ${PIPELINE_LOG}" >&2
}

# キューワーカー用ロック（Linux: flock / Git Bash・Windows: mkdir）
_acquire_execute_queue_lock() {
  if command -v flock >/dev/null 2>&1; then
    exec 9>>"${EXECUTE_QUEUE_LOCK}"
    if flock -n 9; then
      EXECUTE_QUEUE_LOCK_MODE=flock
      trap '_release_execute_queue_lock' EXIT
      return 0
    fi
    return 1
  fi
  if mkdir "${EXECUTE_QUEUE_LOCK_DIR}" 2>/dev/null; then
    echo "$$" >"${EXECUTE_QUEUE_LOCK_DIR}/pid"
    EXECUTE_QUEUE_LOCK_MODE=mkdir
    trap '_release_execute_queue_lock' EXIT
    return 0
  fi
  return 1
}

_release_execute_queue_lock() {
  case "${EXECUTE_QUEUE_LOCK_MODE}" in
    flock)
      flock -u 9 2>/dev/null || true
      ;;
    mkdir)
      rm -rf "${EXECUTE_QUEUE_LOCK_DIR}"
      ;;
  esac
  EXECUTE_QUEUE_LOCK_MODE=""
}

# execute_urls.txt を上から直列処理（ワーカー 1 本）
_drain_execute_urls_queue() {
  if ! _acquire_execute_queue_lock; then
    echo "キュー: 別ワーカーが処理中のため終了します。" >&2
    exit 0
  fi

  echo "=== execute_urls キュー処理開始 ===" >&2
  local _url _n=0
  while _url="$(_execute_urls_peek_first "${EXECUTE_URLS_TXT}")"; do
    _n=$((_n + 1))
    echo "--- キュー [${_n}] ${_url} ---" >&2
    _run_pipeline_wait "${_url}" || true
    _execute_urls_pop_first "${EXECUTE_URLS_TXT}"
    echo "キューから先頭行を削除しました: ${EXECUTE_URLS_TXT}" >&2
  done
  echo "=== execute_urls キュー処理完了（処理件数: ${_n}） ===" >&2
}

_spawn_execute_queue_drainer() {
  if command -v nohup >/dev/null 2>&1; then
    nohup bash "${RUN_PIPELINE_SELF}" --drain-execute-queue >>"${EXECUTE_QUEUE_LOG}" 2>&1 &
    echo "キューワーカー起動 PID $!。進捗: cat ${EXECUTE_QUEUE_LOG} / cat ${PIPELINE_LOG}" >&2
  else
    bash "${RUN_PIPELINE_SELF}" --drain-execute-queue >>"${EXECUTE_QUEUE_LOG}" 2>&1 &
    echo "キューワーカー起動 PID $!。進捗: cat ${EXECUTE_QUEUE_LOG}" >&2
  fi
}

if [[ "${QUEUE_DRAIN}" -eq 1 ]]; then
  _drain_execute_urls_queue
  exit 0
fi

if [[ "${RETRY_N}" -gt 0 ]]; then
  _run_pipeline_background "${VIDEO_REF}"
  exit 0
fi

echo "キューに登録しました（直列処理はバックグラウンド）: ${VIDEO_REF}" >&2
_spawn_execute_queue_drainer
exit 0
