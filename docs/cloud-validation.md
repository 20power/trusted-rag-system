# GPU 云服务器验证说明

## 验证环境

- Ubuntu 22.04 容器，30 核 CPU、约 180 GiB 内存。
- 2 × RTX 3090 24GB，驱动 580.105.08。
- 30GB 系统盘；项目、模型、缓存、索引和日志均放在 150GB 持久盘。
- 当前租赁环境本身是容器，不支持嵌套 Docker，因此本轮使用原生进程验证；
  `docker-compose.yml` 仍是最终独立 Linux 主机的交付部署基线。

## 已验证组件

| 组件 | 版本/模型 | 监听地址 | GPU |
|---|---|---|---|
| Qdrant | 1.14.1 静态 musl 二进制 | `127.0.0.1:6333` | 无 |
| Embedding | `BAAI/bge-m3`，1024 维 | `127.0.0.1:8002` | GPU 1 |
| 生成模型 | `Qwen/Qwen2.5-7B-Instruct`，FP16 | `127.0.0.1:8001` | GPU 0 |
| FastAPI 后端 | 项目源码 | `127.0.0.1:8000` | 间接调用 |

模型缓存、Qdrant 数据、SQLite、派生文件和日志都位于持久工作目录。服务默认只
监听回环地址；需要浏览器访问时应使用 SSH 端口转发或由部署方配置受控反向代理，
不得直接暴露模型和向量数据库端口。

## 原生部署入口

按顺序执行：

```bash
./scripts/cloud/install-model-runtime.sh
./scripts/cloud/start-qdrant.sh
./scripts/cloud/start-embedding.sh
./scripts/cloud/start-vector-index.sh
./scripts/cloud/start-llm.sh
./scripts/cloud/start-backend.sh
python ./scripts/cloud/smoke-test.py
```

评测入口：

```bash
./scripts/cloud/start-hybrid-evaluation.sh
./scripts/cloud/start-answer-evaluation.sh
```

所有启动脚本都会写 PID 和日志，重复执行时会识别仍在运行的进程。模型仓库在
网络受限环境通过 `HF_ENDPOINT` 配置镜像传输，下载完成后可复用本地缓存运行。

## 已完成的数据验收

- 500/500 文件完成解析和索引，最终失败 0。
- 232 份 XLS、32 份 DOC 均通过 LibreOffice 转换，原始文件未修改。
- 生成 69,632 个知识块；排除 1 份重复文档后写入 Qdrant 69,578 个向量点。
- Qdrant 集合为 1024 维 Cosine，重复建库使用确定性点 ID 幂等覆盖。
- Excel 与 Word 真实问题均通过端到端冒烟测试，返回定位证据和引用。

最终指标以 `docs/development-status.md` 和持久目录中的 JSON 评测报告为准。
