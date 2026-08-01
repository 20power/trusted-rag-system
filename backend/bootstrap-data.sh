#!/bin/sh
set -eu

python -m app.cli doctor
python -m app.cli scan
python -m app.cli parse --limit 500 --extension xlsx
python -m app.cli parse --limit 500 --extension docx
python -m app.cli parse --limit 500 --extension pdf
python -m app.cli convert-legacy --limit 500
python -m app.cli doctor

if [ "${EMBEDDING_PROVIDER:-disabled}" != "disabled" ]; then
  python -m app.cli vector-index
fi
