#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
workspace_root=${WORKSPACE_ROOT:-$(CDPATH= cd -- "$project_root/.." && pwd)}
venv_dir=${VENV_DIR:-"$workspace_root/.venv"}
service_dir="$workspace_root/services/backend"
pid_file="$service_dir/backend.pid"
log_file="$service_dir/backend.log"

mkdir -p "$service_dir"

if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
  echo "后端服务已运行，PID=$(cat "$pid_file")"
  exit 0
fi

curl --fail --silent http://127.0.0.1:6333/ >/dev/null
curl --fail --silent http://127.0.0.1:8001/health >/dev/null
curl --fail --silent http://127.0.0.1:8002/health >/dev/null

(
  cd "$project_root/backend"
  nohup env \
    APP_ENV=production \
    DATABASE_URL="sqlite:////$workspace_root/runtime/trusted_rag.db" \
    DERIVED_DATA_DIR="$workspace_root/runtime/derived" \
    SOURCE_DATA_DIR="$workspace_root/nfra_page_attachments_500" \
    QA_WORKBOOK_PATH="$workspace_root/QA数据.xlsx" \
    EMBEDDING_PROVIDER=local \
    EMBEDDING_BASE_URL=http://127.0.0.1:8002/v1 \
    EMBEDDING_MODEL=BAAI/bge-m3 \
    EMBEDDING_TIMEOUT_SECONDS=600 \
    HYBRID_CANDIDATE_COUNT=40 \
    QDRANT_URL=http://127.0.0.1:6333 \
    QDRANT_COLLECTION="${QDRANT_COLLECTION:-regulatory_knowledge_bge_m3}" \
    LLM_PROVIDER=local \
    LLM_BASE_URL=http://127.0.0.1:8001/v1 \
    LLM_MODEL=Qwen/Qwen2.5-7B-Instruct \
    LLM_TIMEOUT_SECONDS=600 \
    LLM_MAX_TOKENS=800 \
    LLM_TEMPERATURE=0 \
    "$venv_dir/bin/python" -m uvicorn app.main:app \
      --host "${BACKEND_HOST:-127.0.0.1}" \
      --port 8000 \
      --log-level info >"$log_file" 2>&1 </dev/null &
  echo "$!" >"$pid_file"
)

i=0
until curl --fail --silent http://127.0.0.1:8000/api/v1/health >/dev/null; do
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then
    echo "后端启动超时，请检查 $log_file" >&2
    exit 1
  fi
  sleep 1
done

echo "后端已启动，PID=$(cat "$pid_file")，地址=http://127.0.0.1:8000"
