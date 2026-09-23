# 比赛 MVP API

当前 backend 实现消费者咨询、人工接管和品牌洞察的同一条服务闭环。所有示例知识、事件处理人和
经营数据均属于 `demo`，不得解释为真实欧莱雅业务数据或正式 SLA。

## PRD V1.1 比赛版接口

新 PRD 使用 `/v1/competition`，以 `AUTO_REPLY`、`AGENT_ASSIST`、`HUMAN_REQUIRED` 取代旧状态
作为比赛版服务模式，同时独立保存消息发送、人工处理、业务动作、问题结果和本地风险状态。旧 API
继续保留兼容，但新演示和后续数据/AI 联调应使用比赛版接口。

- `POST /v1/competition/sessions/analyze`：提交带 cutoff、归属、来源、时间和有效性的完整 context
  snapshot，返回并保存服务轨迹、共情理解、建议、evidence 和风险记录。
- `POST /v1/competition/conversations/{id}/analyze`：通过 `ContextDataProvider` 加载正式数据；未配置
  adapter 时返回 `503`，无 snapshot 返回 `404`。
- `GET /v1/competition/sessions`、`GET /v1/competition/sessions/{id}`：恢复风险优先队列和完整状态。
- `POST /v1/competition/sessions/{id}/messages`：分别处理 system/agent 发送，校验 decision、最新消息、
  接管锁和 idempotency；比赛回执固定标记 `SIMULATED`。
- `POST /v1/competition/sessions/{id}/takeover`：认领并锁定自动发送。
- `POST /v1/competition/sessions/{id}/actions`：只记录 `PENDING_MANUAL` 或 `SIMULATED` 售后动作。
- `PATCH /v1/competition/sessions/{id}/risk`：风险关闭必须有处理人、说明和 evidence。
- `PATCH /v1/competition/sessions/{id}/issue-result`：明确确认且无开放动作/风险才能解决；支持未确认
  归档和重开。
- `POST /v1/competition/sessions/{id}/suggestion-feedback`：采用、修改发送或拒绝建议。
- `POST /v1/competition/sessions/{id}/corrections`：保留 AI 原值、人工新值、操作者和原因。

完整字段、错误和接入边界见[比赛版 P0 技术合同](competition-p0-contract.md)。可运行工作台位于
`/workspace/competition`，页面内三个主演示场景均通过 HTTP 实时创建，且明确标记 Mock/SIMULATED。

## 消费者端

- `GET /v1/conversations/{conversation_id}`：恢复消费者会话当前状态、最新 `result_id` 以及按时间排列的
  user/assistant transcript。消费者 workspace 刷新后使用该接口重建对话；不存在的历史会话返回 `404`。

### 发起和继续咨询

`POST /v1/conversations` 创建会话，`POST /v1/conversations/{conversation_id}/messages`
在同一会话补充信息。request 的主要字段如下：

```json
{
  "message": "第一次使用面霜，应该怎么用？",
  "product": "演示面霜",
  "order_reference": "DEMO-ORDER-001",
  "attachments": []
}
```

response 只包含消费者可见的自然语言、状态、依据与可执行动作，不暴露情绪标签、内部风险规则、
模型名称或推理过程。底妆搓泥场景的 `GUIDE` 和兼容既有咨询的 `RESOLVE` 返回审核知识依据；
`ASK` 每轮只问一个关键问题；无审核依据时显式
进入 `HANDOFF`；命中高风险症状时进入 `BLOCK`，停止产品推荐并保留安全提醒。

每轮风险与意图判断以当前 `message` 为主，历史消息用于保存事实和补充必要的选购上下文，不会把
旧症状自动当作当前仍在发生。订单、退款、退换货等复合表达优先进入售后意图；现有 demo 知识不
覆盖交易、不良反应或功效承诺，因此这些请求不会因为包含“使用”或“粉底”而错误进入 `RESOLVE`。

附件字段当前只校验 `product_image` 或 `order_screenshot` metadata，属于后续文件 provider 的预留入口。
收到附件时 API 会明确告知无法读取内容并请求转人工，不执行
真实图片识别，也不保存文件内容。

### Case 和 Attempt

- `GET /v1/conversations/{conversation_id}/case`：读取消费者原话、当前事实版本和全部修订历史。
- `POST /v1/conversations/{conversation_id}/case/revisions`：追加更正版本，不覆盖历史版本。
- `GET /v1/conversations/{conversation_id}/attempts`：读取建议及执行历史。
- `POST /v1/conversations/{conversation_id}/attempts`：记录一个包含目的、操作、观察点和退出条件的
  单条件建议；相同建议返回 `409`，防止重复尝试。
- `PATCH /v1/conversations/{conversation_id}/attempts/{attempt_id}`：分别记录执行或跳过、观察内容
  和结果；执行过的建议没有观察内容时返回 `422`。

### 人工交接和反馈

- AI/规则状态机判定为 `HANDOFF` 或 `BLOCK` 时，会自动、幂等创建服务事件，消费者响应直接返回
  `event_id`、`event_status` 和预计响应时间，无需再次点击确认。
- 用户可直接在对话中表达“转人工”“人工客服”“找客服”等选择，此意图优先于普通澄清问题并立即
  建单；若用户没有选择人工，可回答时继续 AI 流程，仅在已审核知识无法可靠回答或安全规则阻断时
  自动建单。
- Ticket 建立后，后续 `messages` 请求会追加消费者消息到共享 transcript，不再重新调用 AI
  决策；普通人工会话保持 `HANDOFF`，高风险会话保持 `BLOCK`。
- `POST /v1/conversations/{conversation_id}/handoff`：保留给消费者主动要求人工的兼容入口，使用
  `idempotency_key` 幂等创建服务事件；如果已经自动建单，则返回现有事件，不重复创建。
- `GET /v1/events/{event_id}`：查看等待接管、处理中或已完成状态及演示预计响应时间。
- `GET /v1/conversations/{conversation_id}/ticket`：消费者轮询人工服务进度，并读取最新一条人工
  回复；不会暴露内部审计与客服操作明细。
- `POST /v1/conversations/{conversation_id}/ticket/results`：由消费者确认已解决或反馈仍需处理；
  该入口不接受伪造人工回复或客服动作完成事件。
- `POST /v1/conversations/{conversation_id}/feedback`：把是否解决和开放反馈绑定到最新
  `result_id`。反馈只进入待分析数据，不自动训练模型或修改风险规则。

## 人工客服工作台

- `POST /v1/agent/intakes`：agent-first 主入口。接收 `customer_id`、当前消息、已有 transcript、订单
  快照和历史工单快照，并可用 `source_conversation_id` 保留上游会话关联；消费者进线时立即创建
  `processing` 客服事件，无需等待 AI 失败。响应包含服务轨迹、意图、情绪、紧急度、已知/未知、
  历史承诺、未完成事项、字段级来源依据、风险、可审核回复草稿、下一步动作，以及
  `after_sales`、`logistics`、`complaint` 或 `risk_specialist` 升级方向。上游系统只需映射 typed
  snapshot，不应把订单或工单 credential 传入本服务。
- `GET /v1/agent/events`：按风险优先级和等待时间返回事件队列。
  已关闭或由消费者确认解决的事件不再出现在待处理队列；消费者选择“仍需处理”后会重新入队。
- `GET /v1/agent/conversations/{conversation_id}`：返回消费者原话、包含 `user`、`assistant`、
  `agent` role 的完整 transcript、共情卡、事实与推断、缺失信息、风险、知识依据、Case 修订、
  建议执行结果、自动转人工原因、建议下一步和审计轨迹。
- `POST /v1/agent/events/{event_id}/actions`：记录回复、索要材料、建立售后记录、升级专家或关闭
  事件。`reply` 必须提供非空 `parameters.note`，并会把回复写入共享 transcript；`close` 将事件标为
  `completed` 并移出待处理队列，但保留 Ticket、transcript 和审计。鉴权接入前审计
  主体明确记录为 `unauthenticated_agent_api`；生产环境必须用认证身份替换。
- `POST /v1/agent/conversations/{conversation_id}/ticket/results`：分别记录人工回复、动作完成、
  用户确认解决或重开；这些结果不会相互冒充。
- `POST /v1/agent/conversations/{conversation_id}/suggestion-feedback`：记录客服对 AI 草稿的
  `adopted`、`edited` 或 `rejected` 决策；edited 必须提供最终回复，rejected 必须提供原因。
- `PATCH /v1/agent/conversations/{conversation_id}/risk`：维护风险 `open`、`monitoring`、
  `escalated`、`closed` 生命周期。关闭时必须提供说明，状态变化进入审计轨迹。

`GET /workspace/consumer` 和 `GET /workspace/agent` 提供无额外 frontend dependency 的最小可运行
工作区，用于联调消费者输入和人工队列。消费者端每两秒同步 Ticket，并把人工回复显示为客服消息
气泡；客服端以聊天气泡显示双方完整对话，每三秒刷新队列和当前会话、自动打开首个新 Ticket，并将
UTC 时间转换为浏览器本地时间。客服可在处理结束后关闭会话；人工回复/动作由客服提交，解决确认/
继续处理由消费者提交。它们不包含 production 登录能力。

当前消费者 API 继续保留以兼容既有演示，但新业务集成应优先从 `/v1/agent/intakes` 进入客服工作台。
工作台中的 draft 只作为建议，必须由人工客服审核后发送；`HANDOFF` 仅为旧消费者流程兼容状态，新
主流程通过 `escalation_target` 表达售后、物流、投诉和风险专员升级。

## AI Mock 接口

`POST /v1/mock/agent-assists` 是人工客服插件主 Mock：输入与正式 agent intake 使用相同 context，输出
服务轨迹、共情理解、建议和风险跟踪四个固定区域，且不会写数据库或产生 Ticket。字段级 evidence
明确指向 chat、order 或 ticket 的 source ID，供前端和 3 号 AI 模块直接联调。

`POST /v1/mock/decisions` 作为旧消费者流程兼容接口，使用冻结的 typed contract 返回 `ASK`、
`GUIDE`、`HANDOFF` 或 `BLOCK`，
用于在真实 AI 模块接入前进行 frontend 和 backend 联调。Mock 无 network、database 或 Ticket side
effect；风险与售后优先于普通 GUIDE，两次执行无改善后返回 `HANDOFF`，无 evidence 时不会生成产品
事实。完整字段和示例见[系统架构与技术接口](system-architecture-and-interfaces.md#ai-mock-输入合同)。

development 和 test 默认启用；production 的 `MOCK_API_ENABLED=false`，访问时返回 `404`。

## LLM provider

设置 `LLM_ENABLED=true` 并提供 `LLM_API_KEY`、`LLM_BASE_URL` 和 `LLM_MODEL` 后，application factory
会注入 OpenAI-compatible adapter。它调用 `/chat/completions`：intent 输出必须通过 Schema 校验；
普通消费者回复会结合最近八条对话、当前消息、固定状态和审核知识生成。模型无权改变决策状态，
`BLOCK`/`HANDOFF` 保持确定性话术，任何生成失败都会回退模板。
intent 阶段返回 `intent` 与 `confidence`；timeout、network error、非法 JSON、非法字段或低置信度会回退到
rule-based provider。高风险判断在候选 provider 之前执行，模型结果不能直接写数据库或创建 Ticket。

这不是 RAG 接入；当前状态机与内置演示知识仍由 backend 控制，完整配置见
[Configuration](configuration.md#llm-adapter)。

## 品牌洞察

`GET /v1/insights/overview` 返回咨询量、反馈解决率、转人工率、重复提问率和高频未解决问题。
每项指标包含时间范围、样本数和 `demo`/`real` 属性；默认且当前实际支持的属性为 `demo`。

## 状态和版本

全局状态为 `GUIDE`、`RESOLVE`、`ASK`、`HANDOFF` 和 `BLOCK`。MongoDB 持久化保存状态切换原因、规则版本、
知识版本、结果编号、人工动作和反馈。当前版本由 `SCHEMA_VERSION`、`RULE_VERSION` 和
`KNOWLEDGE_VERSION` 配置。

## 错误行为

- 空白或超过限制的输入返回 `422`。
- 不存在的会话或事件返回 `404`。
- feedback 的 `result_id` 不是该会话最新结果时返回 `409`。
- MongoDB 暂时不可用时返回不包含连接信息的 `503`。
- 无知识命中不会生成产品事实，而是显式请求转人工。

## 尚未实现

- 附件二进制上传、图片识别、语音转文字和真实文件存储。
- 订单/售后系统、企业登录或 SSO、消息通知和客服 webhook。
- 真实 RAG、消费者回复生成、AI 客服草稿和模型效果评测。
- 客服队列分页、事件认领、RBAC、optimistic locking 和多人并发冲突处理。

这些能力尚未选定 vendor。当前 API 只保留业务边界，不宣称 external service 已接入。
