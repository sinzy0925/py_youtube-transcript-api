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
# 並列用: ./run_pipeline1.sh URL … ./run_pipeline5.sh URL（batch1.log…batch5.log、c.f. PIPELINE_SLOT）
# nohup あり（Linux / Cloud Shell 等）: 既定 batch1.log などへ出力しバックグラウンド。nohup なし: フォアグラウンド（エラーにしない）

set -euo pipefail

usage() {
  echo "使い方: $0 <YouTube_URL_または_video_id>" >&2
  echo "  例:   $0 'https://youtu.be/2UF8PHOIfrI?si=xxxx'" >&2
  exit 1
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

# ログ: 環境変数 PIPELINE_LOG で直指定。PIPELINE_SLOT=1..5 で batch{1..5}.log（並列で log 衝突を避ける）
if [[ -n "${PIPELINE_LOG:-}" ]]; then
  :
elif [[ -n "${PIPELINE_SLOT:-}" ]] && [[ "${PIPELINE_SLOT}" =~ ^[1-5]$ ]]; then
  PIPELINE_LOG="${ROOT}/batch${PIPELINE_SLOT}.log"
else
  PIPELINE_LOG="${ROOT}/batch1.log"
fi

if [[ "${#}" -lt 1 ]] || [[ -z "${1:-}" ]]; then
  usage
fi

VIDEO_REF="$1"

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
if [[ -f "${ROOT}/.env" ]]; then
  set +e
  # shellcheck disable=SC2016,SC1090,SC2046,SC2086
  _env_exports="$(
    "${VENV_PY}" - "${ROOT}" <<'PY'
import shlex
import sys
from pathlib import Path

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
        out.append("export " + k + "=" + shlex.quote(str(v)))
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
        out.append("export " + k + "=" + shlex.quote(v))
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
if [[ -z "${MAIL_TO:-}" ]] && [[ -z "${TO_EMAIL:-}" ]]; then
  ARGS+=(--skip-email)
else
  echo "メール送信: MAIL_TO または TO_EMAIL が設定されているため --skip-email しません"
fi

echo "=== パイプライン実行: ${VIDEO_REF} ==="

_log_dir="$(dirname "${PIPELINE_LOG}")"
if [[ ! -d "${_log_dir}" ]]; then
  mkdir -p "${_log_dir}"
fi

if command -v nohup >/dev/null 2>&1; then
  echo "nohup バックグラウンド: ログ → ${PIPELINE_LOG}（python -u）" >&2
  nohup "${VENV_PY}" -u "${ARGS[@]}" "${VIDEO_REF}" >"${PIPELINE_LOG}" 2>&1 &
  _bg_pid=$!
  echo "PID ${_bg_pid}  （確認: cat ${PIPELINE_LOG}）" >&2
  cat ${PIPELINE_LOG}
  exit 0
fi

echo "注意: nohup がありません。フォアグラウンド実行します（端末を閉じると停止します）。" >&2
exec "${VENV_PY}" -u "${ARGS[@]}" "${VIDEO_REF}"
