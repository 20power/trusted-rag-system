#!/bin/sh
set -eu

qdrant_version=${QDRANT_VERSION:-1.14.1}
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
workspace_root=${WORKSPACE_ROOT:-$(CDPATH= cd -- "$project_root/.." && pwd)}
service_dir="$workspace_root/services/qdrant"
binary="$service_dir/bin/qdrant"
pid_file="$service_dir/qdrant.pid"
log_file="$service_dir/qdrant.log"

mkdir -p "$service_dir/bin" "$service_dir/storage" "$service_dir/snapshots"

if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
  echo "Qdrant 已运行，PID=$(cat "$pid_file")"
  exit 0
fi

if [ ! -x "$binary" ]; then
  archive="$service_dir/qdrant-$qdrant_version.tar.gz"
  url="https://github.com/qdrant/qdrant/releases/download/v$qdrant_version/qdrant-x86_64-unknown-linux-musl.tar.gz"
  curl \
    --fail \
    --location \
    --retry 5 \
    --retry-delay 2 \
    --continue-at - \
    "$url" \
    --output "$archive"
  if ! tar -xzf "$archive" -C "$service_dir/bin"; then
    if [ ! -x "$binary" ] || ! "$binary" --version; then
      echo "Qdrant 归档校验或解压失败，请删除断点文件后重试：$archive" >&2
      exit 1
    fi
    echo "归档包含多余尾部字节，但已提取的 Qdrant 二进制校验通过。" >&2
  fi
  chmod 755 "$binary"
fi

(
  cd "$service_dir"
  nohup env \
    QDRANT__SERVICE__HOST=127.0.0.1 \
    QDRANT__SERVICE__HTTP_PORT=6333 \
    QDRANT__SERVICE__GRPC_PORT=6334 \
    QDRANT__STORAGE__STORAGE_PATH="$service_dir/storage" \
    QDRANT__STORAGE__SNAPSHOTS_PATH="$service_dir/snapshots" \
    QDRANT__TELEMETRY_DISABLED=true \
    "$binary" >"$log_file" 2>&1 </dev/null &
  echo "$!" >"$pid_file"
)

i=0
until curl --fail --silent http://127.0.0.1:6333/ >/dev/null; do
  i=$((i + 1))
  if [ "$i" -ge 30 ]; then
    echo "Qdrant 启动超时，请检查 $log_file" >&2
    exit 1
  fi
  sleep 1
done

echo "Qdrant 已启动，PID=$(cat "$pid_file")，数据目录=$service_dir/storage"
curl --fail --silent http://127.0.0.1:6333/
echo
