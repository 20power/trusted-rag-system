#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
workspace_root=${WORKSPACE_ROOT:-$(CDPATH= cd -- "$project_root/.." && pwd)}
venv_dir=${VENV_DIR:-"$workspace_root/.venv"}
service_dir="$workspace_root/services/embedding"
pid_file="$service_dir/embedding.pid"
log_file="$service_dir/embedding.log"

mkdir -p \
  "$service_dir" \
  "$workspace_root/models/huggingface" \
  "$workspace_root/models/torch"

if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
  echo "Embedding 服务已运行，PID=$(cat "$pid_file")"
  exit 0
fi

if [ ! -x "$venv_dir/bin/python" ]; then
  echo "虚拟环境不存在：$venv_dir，请先运行 install-model-runtime.sh" >&2
  exit 1
fi

(
  cd "$project_root/backend"
  nohup env \
    CUDA_VISIBLE_DEVICES="${EMBEDDING_CUDA_VISIBLE_DEVICES:-1}" \
    HF_HOME="$workspace_root/models/huggingface" \
    HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}" \
    HF_HUB_DISABLE_XET=1 \
    TORCH_HOME="$workspace_root/models/torch" \
    EMBEDDING_SERVER_MODEL="${EMBEDDING_SERVER_MODEL:-BAAI/bge-m3}" \
    EMBEDDING_SERVER_DEVICE="${EMBEDDING_SERVER_DEVICE:-cuda:0}" \
    EMBEDDING_SERVER_BATCH_SIZE="${EMBEDDING_SERVER_BATCH_SIZE:-32}" \
    EMBEDDING_SERVER_MAX_SEQUENCE_LENGTH="${EMBEDDING_SERVER_MAX_SEQUENCE_LENGTH:-1024}" \
    "$venv_dir/bin/python" -m uvicorn app.embedding_server:app \
      --host 127.0.0.1 \
      --port 8002 \
      --log-level info >"$log_file" 2>&1 </dev/null &
  echo "$!" >"$pid_file"
)

echo "Embedding 服务正在加载模型，PID=$(cat "$pid_file")，日志=$log_file"
