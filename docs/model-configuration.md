# 模型配置说明

## 是否必须申请云端账号

不是。系统在不配置生成模型时仍能完成资料入库、检索、证据展示和
Excel 确定性取数。文本自然语言归纳可选择以下任一种方式：

- 本地模式：在甲方或自有 GPU 服务器运行 OpenAI-compatible 模型服务。
- 云端模式：向模型服务商申请账号和 API Key，通过 HTTPS 调用。

两种模式共用同一套后端协议，切换时不修改业务代码。

## 本地与云端的区别

| 项目 | 本地模型 | 云端模型 |
|---|---|---|
| 数据边界 | 问题和证据留在指定环境 | 问题和检索证据片段会发送给服务商 |
| 硬件 | 需要 GPU、显存和运维能力 | 本地无需 GPU |
| 成本 | 主要是服务器和运维成本 | 通常按 Token 或调用量计费 |
| 上手速度 | 需要部署推理服务 | 申请 Key 后通常更快 |
| 可控性 | 模型版本和日志策略可完全控制 | 受服务商接口、配额和策略影响 |
| 断网运行 | 支持 | 不支持 |

正式交付默认推荐本地模式；云端模式适合开发期快速验证。即使只发送
Top-K 证据片段，也属于数据离开指定环境，部署方必须据此确认安全要求。

本次 GPU 验收采用本地 `Qwen/Qwen2.5-7B-Instruct` FP16，并通过项目内
OpenAI-compatible 服务运行在独立 GPU：

```bash
./scripts/cloud/install-model-runtime.sh
./scripts/cloud/start-llm.sh
```

该轻量服务用于单机验收和低并发部署；高并发生产环境仍可将同一
`LLM_BASE_URL` 切换到 vLLM 等兼容服务，业务代码无需修改。

## 环境变量

复制 `.env.example` 为 `.env`，只在部署环境填写真实值：

```dotenv
LLM_PROVIDER=disabled
LLM_BASE_URL=http://model-server:8000/v1
LLM_API_KEY=
LLM_MODEL=
LLM_TIMEOUT_SECONDS=60
LLM_MAX_TOKENS=800
LLM_TEMPERATURE=0
```

- `LLM_PROVIDER=disabled`：禁用文本生成，系统使用证据模式。
- 启用时可将 `LLM_PROVIDER` 写为 `local` 或 `cloud`；该值用于状态展示。
- `LLM_BASE_URL` 必须指向带 `/v1` 的 OpenAI-compatible 根地址。
- `LLM_MODEL` 必须与推理服务暴露的模型标识一致。
- 本地服务不要求鉴权时，`LLM_API_KEY` 可留空。
- `.env` 和任何真实密钥不得提交到源码仓库。

本地示例：

```dotenv
LLM_PROVIDER=local
LLM_BASE_URL=http://host.docker.internal:8001/v1
LLM_API_KEY=
LLM_MODEL=your-local-instruct-model
```

云端示例：

```dotenv
LLM_PROVIDER=cloud
LLM_BASE_URL=https://provider.example.com/v1
LLM_API_KEY=replace-with-runtime-secret
LLM_MODEL=provider-model-id
```

## 接口约束与失败策略

后端调用 `POST /chat/completions`，要求模型返回：

```json
{"answer":"可核验答案。[1]","citations":[1]}
```

后端不会直接信任模型输出。以下任一情况都会自动退回原始证据模式：

- 请求超时或服务不可达；
- 返回体不符合 OpenAI-compatible 结构；
- 模型未返回合法 JSON；
- 引用编号越界或正文缺少引用标记；
- 答案出现证据中不存在的数字。

Excel 精确取数不经过生成模型，因此无论是否配置模型，都可返回带工作表和
单元格位置的确定性答案。
