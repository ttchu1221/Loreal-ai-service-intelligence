# L'Oréal AI Service Intelligence

面向美妆消费者咨询、风险识别、人工接管和服务洞察的 AI service intelligence backend。
当前实现采用 FastAPI、MongoDB、可替换的 `IntentProvider`/`KnowledgeProvider` 和确定性安全
fallback，可在没有外部 LLM 的情况下运行完整演示流程。

## 环境要求

- Python 3.9+

## 本地开发

```bash
scripts/bootstrap.sh
scripts/mongo-dev.sh  # 在独立 terminal 启动 MongoDB
scripts/dev.sh
```

服务启动后可访问：

- 健康检查：<http://127.0.0.1:8000/health>
- API 文档：<http://127.0.0.1:8000/docs>

## 已实现能力

- 消费者多轮咨询及 `RESOLVE`、`ASK`、`HANDOFF`、`BLOCK` 四状态编排。
- 当前消息优先的风险识别，支持常见否定、假设、第三方主体和已恢复表达。
- 可注入的 LLM 意图识别边界，以及 timeout、非法输出和低置信度 fallback。
- 可注入的 RAG/知识库边界，以及知识可回答性过滤和可追踪 evidence。
- MongoDB 会话、审计、反馈、幂等人工事件和客服动作持久化。
- 人工客服视图、事件队列和基础品牌洞察 API。

当前附件只进行 metadata 校验；系统会明确告知无法读取内容并建议转人工。订单系统、真实文件
存储、登录鉴权和 webhook 等 external integration 尚未选型，不会在演示中伪造已接入状态。

完整 API contract 与演示边界见
[比赛 MVP API](docs/api.md)，实现结构见
[比赛 MVP Backend Architecture](docs/architecture.md)。

## 质量检查

```bash
scripts/check.sh
```

## 项目结构

```text
src/loreal_ai_service_intelligence/  # 应用代码
tests/                               # 自动化测试
docs/                                # 详细项目文档
config/                              # environment 配置
data/                                # 本地数据分层
sandbox/                             # 本地实验区
scripts/                             # 开发与验证脚本
```

## 开发规范

仓库级开发要求见 [AGENTS.md](AGENTS.md)，版本变更记录见
[CHANGELOG.md](CHANGELOG.md)，详细文档索引见 [docs/README.md](docs/README.md)。

config、data、sandbox 和 scripts 的完整说明见
[开发环境文档](docs/development.md)。

## 当前边界

内置规则与知识仅用于 deterministic demo，不代表 production 模型效果、真实商品知识或正式客服
SLA。上线前仍需接入真实 LLM/RAG、认证与 RBAC、文件处理、订单/售后系统、通知 webhook、分页、
事件认领和并发控制；具体风险和接入顺序见
[Backend Architecture](docs/architecture.md#production-接入路线)。
