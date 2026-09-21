# 比赛版 P0 技术合同与运行边界

本文冻结《欧莱雅 AI 客服助手比赛版 PRD V1.1》和《欧莱雅 P0 产品规则与验收清单 V1.0》中由
4号开发与集成负责人实现的代码合同。比赛版接口与旧消费者咨询接口并行存在，避免破坏已发布调用；
新演示与后续 2号、3号数据及 AI 联调统一使用 `/v1/competition`。

## 交付结论

比赛版已经提供可调用的 typed API、MongoDB 与 Memory 持久化、三模式路由、发送门禁、人工接管锁、
本地风险记录、模拟业务动作、问题结果、审计日志、三栏工作台和自动化验收。聊天、订单、工单、商品
和知识数据通过 `ContextDataProvider` 读取。正式数据 adapter 尚未提供时，按会话读取接口返回明确的
`503 context data provider is not configured`，不会构造“真实查询成功”。

## 模块结构

```text
比赛版工作台或上游系统
  -> /v1/competition typed routes
  -> CompetitionP0Service
       -> 固定安全及权限规则
       -> ContextDataProvider 只读数据边界
       -> StorageRepository
            -> MongoRepository production-like local demo
            -> MemoryRepository deterministic tests
```

主要代码位置：

- `domain/competition.py`：输入快照、输出决策和六类独立状态；
- `providers/context.py`：真实数据待接入接口、未配置 adapter 和内存 Mock adapter；
- `services/competition.py`：R01 至 R03、发送门禁、接管、风险、动作和问题结果；
- `api/competition.py`：HTTP contract 和 error mapping；
- `api/competition_workspace.py`：三栏比赛版工作台。

## 输入快照

`P0ContextSnapshot` 以 `snapshot_id`、`case_id`、`conversation_id`、`issue_id`、`customer_id`、
`current_message_id`、`cutoff_message_seq` 和 `context_version` 为主键与版本基础。聊天中任何
`message_seq` 大于 cutoff 的消息都会在 Schema 边界返回 `422`，防止未来信息泄漏。

商品、订单、工单和知识包含 source、observed time、valid until 或 valid flag。订单和工单额外包含
`owner_customer_id`；归属错误会进入 `HUMAN_REQUIRED`，且错误记录不会出现在 decision evidence。
`scene_minor` 可以为空，但未映射官方标签时禁止自动发送。

正式数据接入实现以下 interface：

```python
class ContextDataProvider(Protocol):
    def load_context(
        self, conversation_id: str, cutoff_message_seq: int | None = None
    ) -> P0ContextSnapshot | None: ...
```

adapter 只能读取和映射快照，不得把 credential 放入模型输入或 API response。

## 三模式和独立状态

路由优先级固定为：

1. `HUMAN_REQUIRED`：当前风险、就医、明确人工、投诉/法律升级、账号支付或隐私异常、数据归属失败、
   同时点关键冲突、工具失败、证据失效、第二次明确未解决；
2. `AGENT_ASSIST`：普通售后、第一次明确未解决、不满、缺字段、多订单、附件人工查看，以及不在自动
   白名单内的低风险咨询；
3. `AUTO_REPLY`：仅 W01 至 W04 且商品/订单归属、知识、有效期、消息版本和接管锁全部通过。

服务模式不能代替其他状态：

| 维度 | 枚举 |
| --- | --- |
| 消息发送 | `DRAFT PENDING SENT FAILED UNKNOWN CANCELLED` |
| 人工处理 | `NONE WAITING CLAIMED` |
| 业务动作 | `SUGGESTED PENDING_MANUAL SIMULATED COMPLETED FAILED` |
| 问题结果 | `OPEN PENDING_CONFIRMATION USER_CONFIRMED_RESOLVED ARCHIVED_UNCONFIRMED REOPENED` |
| 本地风险 | `DETECTED ACKNOWLEDGED HANDLING CLOSED` |

接管锁一旦由强制人工、人工认领、发送失败或 UNKNOWN 设置，本会话重新分析和刷新不会解除。比赛版
不提供自动解锁接口。

## API

| Endpoint | 行为 | 关键错误 |
| --- | --- | --- |
| `POST /v1/competition/sessions/analyze` | 使用完整 snapshot 分析并持久化 | `422` Schema/cutoff invalid |
| `POST /v1/competition/conversations/{id}/analyze` | 通过数据 provider 读取并分析 | `503` provider missing；`404` snapshot missing |
| `GET /v1/competition/sessions` | 风险优先返回队列 | `503` database unavailable |
| `GET /v1/competition/sessions/{id}` | 恢复完整会话与四区域数据 | `404` session missing |
| `POST /v1/competition/sessions/{id}/messages` | 系统或人工发送并记录模拟回执 | `403` permission；`409` stale decision/message |
| `POST /v1/competition/sessions/{id}/takeover` | 认领并永久锁定本会话自动发送 | `409` claimed by another agent |
| `POST /v1/competition/sessions/{id}/actions` | 记录待人工或模拟售后动作 | `404` session missing |
| `PATCH /v1/competition/sessions/{id}/risk` | 更新本地风险 | `409` backward transition/close evidence missing |
| `PATCH /v1/competition/sessions/{id}/issue-result` | 解决、未确认归档或重开 | `409` confirmation/open item invalid |
| `POST /v1/competition/sessions/{id}/suggestion-feedback` | 采用、修改发送或拒绝 | `409` stale decision |
| `POST /v1/competition/sessions/{id}/corrections` | 保存人工更正及原值 | `404` session missing |

## 发送与动作权限

生成结果、发送授权和执行回执是三个对象。`AUTO_REPLY` 只代表候选决策，实际发送仍校验
`decision_id`、`based_on_message_id`、当前接管锁和 idempotency key。`FAILED` 或 `UNKNOWN` 会锁定
自动发送；不同 key 的盲目重试返回 `403`。比赛发送记录固定标记 `SIMULATED`。

退款、补发、换货、改址和赔偿 endpoint 只接受 `pending_manual` 或 `simulated`，持久化结果固定
`external_execution=false`。系统不会调用外部售后 API，也不会把模拟状态写成 `COMPLETED`。

## 风险和问题结束

风险关闭必须填写处理人、处置说明和 evidence ID。关闭风险不会自动解决问题。只有消费者明确确认
原话存在，且无 `PENDING_MANUAL` 动作、无未关闭风险时，才能进入
`USER_CONFIRMED_RESOLVED`。静默、谢谢、客服回复、模拟动作或工单关闭均不能代替该条件。

`ARCHIVED_UNCONFIRMED` 必须保存归档原因；`REOPENED` 保留并重新设置人工锁。

## 工作台与演示

启动后访问 <http://127.0.0.1:8000/workspace/competition>。页面固定为左侧队列、中间原始聊天与发送区、
右侧四区域；顶部始终显示 service mode、reason、处理人和 `SIMULATED`。页面内提供 TC01、TC06、
TC08 三个明确标识的 Mock 场景，现场点击后调用真实 HTTP API，而非静态截图。

## 当前外部依赖

以下接口已留好，但没有上游提供前保持“未接入”，不计真实集成完成：

- 官方会话、商品、订单、工单和知识 adapter；
- 3号经过 Gold 评测的 AI decision/生成 provider；
- 真实消息通道 receipt、企业身份与 RBAC；
- 外部 CRM 或退款、换货、补发、改址、赔偿执行接口。

这些缺失不会阻止 Mock、页面和本地持久化演示，但 production 上线必须另行验收。
