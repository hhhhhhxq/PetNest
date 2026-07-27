#!/usr/bin/env sh
set -eu
if [ ! -x ".venv/bin/python" ]; then
  echo "未找到 .venv。请先执行：python3 -m venv .venv" >&2
  exit 1
fi
. .venv/bin/activate
export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"
exec python -m petnest
