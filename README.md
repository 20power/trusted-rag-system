# 可信监管 RAG 系统

面向银行业监管制度、政策规章和监管统计报表的离线优先、证据可追溯 RAG 问答系统。

## 当前状态

项目已在 GPU 云服务器完成 500 份资料全量解析、264 份旧 DOC/XLS 转换、
69,632 个可定位知识块入库，以及 69,578 个有效知识块的 BGE-M3/Qdrant
向量索引。Excel 精确取数由确定性逻辑完成，文本问答使用本地
Qwen2.5-7B-Instruct，并执行 JSON、引用范围、正文引用标记和证据外数字校验。
模型或向量服务不可用时自动降级，不生成伪答案。

## 目标能力

- 解析 `.doc`、`.docx`、`.pdf`、`.xls`、`.xlsx`。
- 保留章节、条款、页码、工作表、表头、单位、期间和单元格位置。
- 综合稀疏检索、向量检索、元数据过滤和重排。
- 回答制度事实、条款阈值、业务流程、表格取数、比较计算和跨文件问题。
- 答案返回可核验的原文或单元格证据。
- 证据不足、版本不明或来源冲突时澄清或拒答。
- 支持本地 GPU 模型，也可配置 OpenAI-compatible 云端接口。

## 项目结构

```text
trusted-rag-system/
├─ backend/               FastAPI 后端、入库、检索和评测
├─ frontend/              React 管理与问答界面
├─ docs/                  架构、决策和评测口径
├─ scripts/               本地开发与云端原生服务入口
├─ docker-compose.yml     完整离线部署编排
└─ .env.example           配置示例
```

甲方提供的原始材料保留在项目目录外层，通过 `SOURCE_DATA_DIR` 只读挂载。系统不得覆盖、重命名或修改原始文件。

## 已确认的项目决策

1. 最终交付为完整系统，不只提供单个 API。
2. 系统必须能在甲方设备完整复现和使用。
3. 默认本地离线部署；云端模型接口是可选扩展，不是运行前提。
4. 当前 500 份附件视为 v1 冻结语料。
5. 第一版不自动抓取监管网站，管理员通过文件夹扫描或上传增量入库。
6. 原始来源 manifest 缺失，由系统生成本地 manifest。
7. `.doc/.xls` 允许转换为 `.docx/.xlsx` 中间格式，但原文件永久保留。
8. 数据切分按来源文件分组，避免近重复问题泄漏。
9. 最终评测同时包含选择题和开放式可信问答。
10. 系统输出是合规辅助信息，不构成自动审批、法律意见或最终业务决策。

## 自主设计声明

甲方未指定的内容由本项目按行业通用实践设计，并在 `docs/decisions.md` 中记录。当前自主选择包括：

- 前端 React + TypeScript，后端 Python + FastAPI。
- PostgreSQL 保存业务数据、知识块和表格事实，Qdrant 保存稠密向量索引；
  稀疏检索直接基于业务库中的规范化文本完成。
- Docker Compose 作为正式部署基线，Linux x86-64 为主要目标环境。
- 本机开发允许使用 SQLite，以免数据库服务阻塞代码和测试。
- 模型通过 OpenAI-compatible 接口抽象，本地 vLLM/Ollama 和云端服务可切换。
- 表格精确取数绕过生成模型；文本模型必须返回 JSON 和证据编号，校验失败自动降级。
- 性能、准确率、引用和拒答指标采用 `docs/evaluation.md` 定义。
- 制度有效状态无法核验时标记为“未知”，不得默认为现行有效。

这些选择均可通过配置或后续架构决策调整，不应硬编码到业务逻辑。

## 本地开发

后端默认使用 SQLite，适合当前无 Docker 的开发设备：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item ..\.env.example .env
uvicorn app.main:app --reload --port 8000
```

数据处理与检索基线：

```powershell
python -m app.cli scan
python -m app.cli doctor
python -m app.cli parse --limit 500 --extension xlsx
# 解析器升级后可安全重建派生结果：
python -m app.cli parse --limit 500 --extension docx --force
python -m app.cli index --limit 500
python -m app.cli search "根据《商业银行资本管理办法》，交易账簿包括什么？"
python -m app.cli evaluate --source-type excel --limit 100 --top-k 5 --mode lexical
python -m app.cli evaluate-answers --source-type excel --limit 100 --top-k 5
```

模型为可选配置；本地服务、云端服务以及安全边界见
[模型配置说明](docs/model-configuration.md)。
Embedding 与 Qdrant 的建库、混合检索及降级行为见
[混合检索配置](docs/embedding-configuration.md)。
本次 GPU 云服务器的原生部署和验收记录见
[云端验证说明](docs/cloud-validation.md)。

前端：

```powershell
cd frontend
pnpm install
pnpm dev
```

接口文档：`http://localhost:8000/docs`

## Docker 部署

在已安装 Docker、Docker Compose 和 NVIDIA Container Toolkit 的 Linux 服务器上：

```bash
cp .env.example .env
# 修改 SOURCE_DATA_DIR、密码和模型配置
docker compose up -d --build
docker compose exec backend sh ./bootstrap-data.sh
```

默认入口：

- Web：`http://localhost:8080`
- API：`http://localhost:8000`
- API 文档：`http://localhost:8000/docs`
- Qdrant：`http://localhost:6333`

## 安全说明

- `.env`、API Key、数据库密码和模型凭据不得提交到 Git。
- 原始监管文件以只读方式挂载。
- 日志不得保存客户、账户、交易明细等敏感数据。
- 云端模式由使用方自行配置凭据；仓库不包含任何真实密钥。

## 相关文档

- [架构说明](docs/architecture.md)
- [设计决策与假设](docs/decisions.md)
- [评测口径](docs/evaluation.md)
- [最终评测报告](docs/evaluation-results)
- [当前开发状态](docs/development-status.md)
- [模型配置说明](docs/model-configuration.md)
- [混合检索配置](docs/embedding-configuration.md)
- [云端验证说明](docs/cloud-validation.md)
- [外层需求与规划](../项目需求理解与开发规划.md)
