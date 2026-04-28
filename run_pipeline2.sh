#!/usr/bin/env bash
# run_pipeline.sh と同じ。ログは batch2.log（PIPELINE_SLOT=2）。並列実行用。
set -euo pipefail
export PIPELINE_SLOT=2
_script="${BASH_SOURCE[0]:-$0}"
while [[ -L "$_script" ]]; do
  _link_dir="$(cd "$(dirname "$_script")" && pwd -P)"
  _target="$(readlink "$_script")"
  if [[ "$_target" != /* ]]; then
    _target="${_link_dir}/${_target}"
  fi
  _script="$_target"
done
_ROOT="$(cd -P "$(dirname "$_script")" && pwd)"
exec "$_ROOT/run_pipeline.sh" "$@"
