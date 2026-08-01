#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
workspace_root=${WORKSPACE_ROOT:-$(CDPATH= cd -- "$project_root/.." && pwd)}
venv_dir=${VENV_DIR:-"$workspace_root/.venv"}

mkdir -p "$workspace_root/models/pip-cache"

if [ ! -x "$venv_dir/bin/python" ]; then
  python3 -m venv "$venv_dir"
fi

export PIP_CACHE_DIR="$workspace_root/models/pip-cache"
"$venv_dir/bin/python" -m pip install --upgrade pip
"$venv_dir/bin/python" -m pip install \
  torch \
  --index-url https://download.pytorch.org/whl/cu124
"$venv_dir/bin/python" -m pip install -e "$project_root/backend[model-runtime]"

"$venv_dir/bin/python" -c \
  "import torch; print({'torch': torch.__version__, 'cuda': torch.cuda.is_available(), 'devices': torch.cuda.device_count()})"
