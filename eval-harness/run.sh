#!/bin/bash
cd "$(dirname "$0")" || exit 1
export PATH="$HOME/.local/bin:$PATH"
exec ~/.hermes/.venv/bin/python src/harness.py "$@"
