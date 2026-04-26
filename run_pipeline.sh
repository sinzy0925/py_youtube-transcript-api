#!/usr/bin/env bash
# リポジトリルートで: URL だけ渡してパイプライン実行（.venv を作り requirements を入れる）
#   ./run_pipeline.sh "https://youtu.be/xxxx?si=..."
#
# Windows (Git Bash) / WSL / Linux 共通: activate の source に依存せず
#   .venv/Scripts/python.exe または .venv/bin/python を直接使う
#
# API キー / メール: リポジトリの .env をシェルに取り込んでから a05 の引数（--skip-email）を決める

set -euo pipefail

usage() {
  echo "使い方: $0 <YouTube_URL_または_video_id>" >&2
  echo "  例:   $0 'https://youtu.be/2UF8PHOIfrI?si=xxxx'" >&2
  exit 1
}

if [[ "${#}" -lt 1 ]] || [[ -z "${1:-}" ]]; then
  usage
fi

VIDEO_REF="$1"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$ROOT"

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
exec "${VENV_PY}" "${ARGS[@]}" "${VIDEO_REF}"
