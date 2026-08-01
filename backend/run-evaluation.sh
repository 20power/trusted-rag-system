#!/bin/sh
set -eu

mode="${1:-lexical}"
python_command="${PYTHON:-python}"

"$python_command" -m app.cli evaluate --source-type excel --limit 100 --top-k 5 --mode "$mode"
"$python_command" -m app.cli evaluate --source-type pdf --limit 100 --top-k 5 --mode "$mode"
"$python_command" -m app.cli evaluate --source-type word --limit 100 --top-k 5 --mode "$mode"
