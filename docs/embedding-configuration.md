# 混合检索配置

## 运行模式

系统始终保留可离线运行的字符级稀疏检索。配置 Embedding 服务后，问答接口会：

1. 用稀疏检索召回候选知识块；
2. 调用 OpenAI-compatible `/embeddings` 生成问题向量；
3. 从 Qdrant 召回语义相近知识块；
4. 对 Word/普通文本使用加权 RRF 合并两路排名；
5. 对显式或候选结果明确为 PDF/Excel 的精确型问题使用稀疏优先策略；
6. 返回 `retrieval_mode=hybrid` 或 `retrieval_mode=lexical_policy`。

如果 Embedding 超时、协议异常或 Qdrant 不可用，接口返回
`retrieval_mode=lexical_fallback` 和警告，同时继续使用稀疏检索回答。
未配置 Embedding 时返回 `retrieval_mode=lexical`。

该路由来自真实 300 题对照评测：BGE-M3 明显改善 Word 证据排序，而 PDF 和
Excel 的标题、候选表述、工作表与单元格精确匹配更稳定。系统不会为了形式上
“全部走向量”而牺牲已验证的证据命中率。

## 配置

```dotenv
EMBEDDING_PROVIDER=local
EMBEDDING_BASE_URL=http://host.docker.internal:8002/v1
EMBEDDING_API_KEY=
EMBEDDING_MODEL=your-embedding-model
EMBEDDING_TIMEOUT_SECONDS=60
EMBEDDING_BATCH_SIZE=32
HYBRID_CANDIDATE_COUNT=40
QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=regulatory_knowledge
```

本次离线验收使用 `BAAI/bge-m3`（1024 维）和集合
`regulatory_knowledge_bge_m3`。项目自带的 OpenAI-compatible 服务入口为：

```bash
./scripts/cloud/start-embedding.sh
./scripts/cloud/start-vector-index.sh
```

Embedding 服务必须兼容：

```http
POST /v1/embeddings
Content-Type: application/json

{"model":"your-embedding-model","input":["文本一","文本二"]}
```

本地服务无鉴权时 `EMBEDDING_API_KEY` 可留空。使用云端 Embedding 时，
知识块文本和用户问题会发送给服务商，其数据边界与云端生成模型相同。

## 建库

容器首次部署推荐执行：

```bash
docker compose exec backend sh ./bootstrap-data.sh
```

该脚本依次检查环境、扫描 500 份原始资料、解析现代格式、转换旧格式，并在
Embedding 已启用时建立 Qdrant 索引。所有步骤均可重复执行。

只重建向量索引：

```bash
docker compose exec backend python -m app.cli vector-index
```

开发期可限制数量验证协议：

```bash
python -m app.cli vector-index --limit 100
```

向量点 ID 由知识块 ID 确定性派生，重复执行为幂等覆盖。若更换 Embedding
模型且向量维度改变，命令会拒绝写入并提示集合维度不一致；部署人员应先备份，
再明确删除或更换 Qdrant 集合名称，系统不会自行破坏现有索引。

## 旧格式转换预检

```bash
python -m app.cli doctor
python -m app.cli convert-legacy --limit 500
```

`doctor` 会报告 LibreOffice 路径、待转换数量、模型配置和数据目录。
如果当前设备没有 LibreOffice，`convert-legacy` 会在改变数据库状态前停止；
本项目 Docker 镜像已经包含 Writer 和 Calc 转换组件。
