#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
workspace_root=${WORKSPACE_ROOT:-$(CDPATH= cd -- "$project_root/.." && pwd)}
venv_dir=${VENV_DIR:-"$workspace_root/.venv"}
service_dir="$workspace_root/services/evaluation"
pid_file="$service_dir/answer-evaluation.pid"
log_file="$service_dir/answer-evaluation.log"

mkdir -p "$service_dir"

if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
  echo "答案准确率评测已运行，PID=$(cat "$pid_file")"
  exit 0
fi

curl --fail --silent http://127.0.0.1:6333/ >/dev/null
curl --fail --silent http://127.0.0.1:8001/health >/dev/null
curl --fail --silent http://127.0.0.1:8002/health >/dev/null

(
  cd "$project_root/backend"
  nohup env \
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
    ANSWER_SOURCE_TYPES="${ANSWER_SOURCE_TYPES:-excel pdf word}" \
    sh -c '
      for source_type in $ANSWER_SOURCE_TYPES; do
        "$0" -m app.cli evaluate-answers \
          --source-type "$source_type" \
          --limit 100 \
          --top-k 5 \
          --retrieval-mode hybrid
      done
    ' "$venv_dir/bin/python" >"$log_file" 2>&1 </dev/null &
  echo "$!" >"$pid_file"
)

echo "答案准确率评测已启动，来源=${ANSWER_SOURCE_TYPES:-excel pdf word}，PID=$(cat "$pid_file")，日志=$log_file"
