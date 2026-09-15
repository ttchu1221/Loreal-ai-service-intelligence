# Configuration

应用通过 `pydantic-settings` 读取 environment variable。

## 加载方式

默认读取项目根目录的 `.env`。如果设置了 `APP_CONFIG_FILE`，则读取该文件作为默认配置；process
environment 中的同名变量始终拥有更高优先级。

```bash
APP_CONFIG_FILE=config/test.example python -m loreal_ai_service_intelligence.cli
```

`scripts/dev.sh` 默认选择不会被 Git 追踪的根目录 `.env`。本地 `.env` 只需填写 LLM 接入项，其他
设置使用下表中的代码默认值；也可以传入其他完整配置文件：

```bash
scripts/dev.sh config/production.example
```

## 可用设置

| Key | 类型 | 默认值 | 用途 |
| --- | --- | --- | --- |
| `APP_NAME` | string | `L'Oreal AI Service Intelligence` | API 显示名称 |
| `APP_ENV` | enum | `development` | 当前 environment |
| `LOG_LEVEL` | string | `INFO` | application log level |
| `APP_HOST` | string | `127.0.0.1` | bind address |
| `APP_PORT` | integer | `8000` | bind port |
| `APP_RELOAD` | boolean | `false` | 是否启用 hot reload |
| `DATA_DIR` | path | `data` | data root directory |
| `MONGODB_URI` | string | `mongodb://127.0.0.1:27017` | MongoDB connection URI；credential 只能由 `.env` 或 runtime 注入 |
| `MONGODB_DATABASE` | string | `loreal_ai_service_intelligence` | MongoDB database name |
| `MONGODB_TIMEOUT_MS` | integer | `3000` | MongoDB connect 和 server selection timeout |
| `SCHEMA_VERSION` | string | `1.0` | 共情卡和人工接管包 Schema 版本 |
| `RULE_VERSION` | string | `risk-rules-v1` | 状态机和风险规则版本 |
| `KNOWLEDGE_VERSION` | string | `demo-knowledge-v1` | 当前演示知识版本 |
| `HANDOFF_ETA_MINUTES` | integer | `30` | 演示人工响应时间；不代表正式 SLA |
| `INTENT_MINIMUM_CONFIDENCE` | float | `0.7` | 外部意图 provider 结果被采用的最低置信度 |
| `MOCK_API_ENABLED` | boolean | `true` | 是否开放 deterministic AI Mock endpoint；production 模板为 `false` |
| `LLM_ENABLED` | boolean | `false` | 是否启用 OpenAI-compatible intent 与上下文回复 provider |
| `LLM_API_KEY` | secret | 无 | LLM credential，只能通过 `.env` 或 runtime secret 注入 |
| `LLM_BASE_URL` | string | `https://api.openai.com/v1` | OpenAI-compatible API base URL |
| `LLM_MODEL` | string | 空 | provider model name；启用 LLM 时必填 |
| `LLM_TIMEOUT_SECONDS` | float | `10` | 单次模型 HTTP 请求 timeout，最大 60 秒 |
| `LLM_RETRY_LIMIT` | integer | `1` | network timeout 的额外重试次数，范围 0 至 3 |

## LLM adapter

当前 adapter 使用 OpenAI-compatible `/chat/completions`，适用于支持相同 contract 的供应商。它
先输出经过 Schema 校验的 intent，再在确定性决策完成后根据最近对话、当前消息、状态和已审核依据
生成消费者话术。生成模型不能修改状态，也不能补充未提供的知识；`BLOCK`、`HANDOFF` 不调用生成
模型。非法、空白、超长输出或调用异常均回退确定性模板。
intent 阶段输出 `intent`、`confidence` 和后端生成的 `source`；回复阶段只输出消费者可见的
`message`，两个阶段都不能执行状态变化：

```dotenv
LLM_ENABLED=true
LLM_API_KEY=replace-with-runtime-secret
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=replace-with-approved-model
```

启用但缺少 key 或 model 时启动会明确失败；provider runtime 失败、非法 JSON、Schema 不合法或低于
`INTENT_MINIMUM_CONFIDENCE` 时退回 rule-based intent。真实 model、Prompt 和 endpoint 需经 3 号
确认后再写入部署环境，repository 不保存 API key。

## 安全边界

`config/` 中只能放非敏感默认值。API key、credential 和 private endpoint 必须存放在不被 Git
追踪的 `.env` 中，或由 deployment platform 注入。所有实际 `*.env` 均由 `.gitignore` 和
`scripts/check.sh` 双重阻止；可提交模板只能使用 `*.example` 且不得包含真实值。production 不应
启用 `APP_RELOAD`。
