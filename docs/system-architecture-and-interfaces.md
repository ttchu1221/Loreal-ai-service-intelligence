# P0 系统架构与技术接口

本文档是 4 号开发与集成负责人的 P0 技术交付基线，覆盖系统架构、数据库对象、状态机、业务 API
以及供前端和 3 号 AI 模块联调的 Mock contract。当前结论是：核心接口均可本地调用；真实 AI、真实
知识库和外部售后系统仍通过稳定边界接入，未接入时不得伪造成功。

## 系统结构

```text
消费者工作区 ─┐
               ├─ FastAPI typed routes ─ ConversationOrchestrator ─ StorageRepository ─ MongoDB
客服工作台 ───┘                              │                    └ MemoryRepository
                                              ├ IntentProvider
                                              └ KnowledgeProvider

前端和 AI 联调 ─ POST /v1/mock/decisions ─ MockDecisionService
                                            └ 无 network、database 或 Ticket 副作用
```

route 只执行 Schema validation、HTTP error mapping 和 service 调用。业务优先级、状态选择、Case、
Attempt 和 Ticket 行为由 service 层处理。provider 返回值必须先通过 Pydantic 校验；AI 输出不能直接
写数据库、建立 Ticket 或执行客服动作。

## 数据库对象

| Collection | 核心对象 | 一致性约束 |
| --- | --- | --- |
| `conversations` | 会话、Case revision、Attempt、当前 Ticket、最新结果 | `conversation_id` unique；整份会话原子替换 |
| `audit_events` | 状态切换、Case/Attempt/Ticket 操作 | 按 `conversation_id + created_at` 排序 |
| `service_events` | 人工接管队列 | `event_id` unique；`conversation_id + idempotency_key` unique |
| `feedback` | 用户反馈和 `result_id` | 只接受当前会话最新结果 |
| `service_actions` | 人工回复、建售后、升级或关闭动作 | 按 `event_id + created_at` 排序 |

`CaseRecord` 保留原始陈述和不可覆盖的 revision history。`AttemptRecord` 分离 proposed、executed、
skipped、observation 和 outcome。`TicketRecord` 分离 agent replied、action completed、user confirmed
resolved 和 reopened，客服动作完成不能自动等于用户确认解决。

## 状态机

优先级固定如下：

```text
当前轮风险 ─────────────► BLOCK
明确人工或售后意图 ─────► HANDOFF
缺少一个关键条件 ───────► ASK
有审核证据且可单步排查 ─► GUIDE
既有通用知识可回答 ─────► RESOLVE  仅作 backward compatibility
无审核证据 ─────────────► HANDOFF
```

`BLOCK` 不能由普通继续按钮解除。搓泥流程一次只允许一个主要问题和一个单条件 GUIDE；两次执行后
仍无改善，Mock contract 必须返回 `HANDOFF`。所有 persistence 状态变化写入 audit trail。

## 业务 API

| Endpoint | 用途 | 主要 error |
| --- | --- | --- |
| `POST /v1/conversations` | 创建 Case 并开始排查 | `422` input invalid；`503` database unavailable |
| `POST /v1/conversations/{id}/messages` | 继续当前会话 | `404` conversation missing |
| `GET /v1/conversations/{id}/case` | 读取 Case 和全部 revision | `404` case missing |
| `POST /v1/conversations/{id}/case/revisions` | 追加事实更正 | `404` case missing |
| `POST /v1/conversations/{id}/attempts` | 记录单条件建议 | `409` duplicate attempt |
| `PATCH /v1/conversations/{id}/attempts/{attempt_id}` | 记录执行、跳过、观察和结果 | `422` executed without observation |
| `POST /v1/conversations/{id}/handoff` | 用户确认后幂等建单 | `404` conversation missing |
| `GET /v1/agent/conversations/{id}` | 获取完整交接包 | `404` conversation missing |
| `POST /v1/agent/conversations/{id}/ticket/results` | 写入四类 Ticket 结果事件 | `404` ticket missing |
| `POST /v1/mock/decisions` | 使用冻结 contract 返回 deterministic AI Mock | `404` Mock disabled；`422` Schema invalid |

完整 request 和 response 可在启动后的 `/docs` 查看。

## AI Mock 输入合同

```json
{
  "request_id": "demo-001",
  "schema_version": "1.0",
  "current_message": "底妆还是搓泥",
  "case_revision": 2,
  "confirmed_facts": {
    "pilling_step": "粉底后",
    "failed_history": "已经换过粉扑"
  },
  "unknown_fields": ["skincare_amount"],
  "attempts": [],
  "requested_handoff": false
}
```

输入采用 `extra=forbid`：未冻结字段返回 `422`，避免前后端悄悄依赖未确认的数据。Attempt 输入只含
recommendation、execution status 和 outcome。Mock API 不接受 credential、图片内容或 raw model
prompt。

## AI Mock 输出合同

```json
{
  "request_id": "demo-001",
  "schema_version": "1.0",
  "state": "GUIDE",
  "risk_level": "low",
  "assistant_message": "其他条件保持不变，只把底妆前护肤品用量减少一半。",
  "question": null,
  "guide": {
    "purpose": "排除底妆前产品用量过多",
    "instruction": "其他条件保持不变，只把底妆前护肤品用量减少一半。",
    "observation_target": "观察同一区域是否仍起屑或结块。",
    "exit_condition": "无改善、情况变差或出现不适时停止并选择转人工。"
  },
  "handoff_reason": null,
  "evidence_ids": ["KB-PILLING-001"],
  "provider": "deterministic_mock",
  "rule_version": "risk-rules-v1",
  "knowledge_version": "demo-knowledge-v1"
}
```

输出只给出决策建议，不产生 side effect。业务 service 仍需验证 evidence ID、重新执行安全规则，并在
用户确认后才创建 Ticket。`rule_version`、`knowledge_version` 和 `schema_version` 用于联调冻结与
问题追踪。

## Mock 包调用

HTTP 调用：

```bash
curl -sS http://127.0.0.1:8000/v1/mock/decisions \
  -H 'Content-Type: application/json' \
  -d '{"request_id":"demo-001","current_message":"底妆搓泥"}'
```

Python 直接调用：

```python
from loreal_ai_service_intelligence.mock_api import MockDecisionRequest, MockDecisionService

service = MockDecisionService("risk-rules-v1", "demo-knowledge-v1")
result = service.decide(MockDecisionRequest(request_id="demo-001", current_message="底妆搓泥"))
```

development 和 test 默认启用 Mock API；production 配置必须保持 `MOCK_API_ENABLED=false`。真实 AI
接入时实现相同 input/output contract，并保留 deterministic Mock 作为 frontend fallback 和 regression
fixture。
