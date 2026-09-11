# 比赛 MVP API

当前 backend 实现消费者咨询、人工接管和品牌洞察的同一条服务闭环。所有示例知识、事件处理人和
经营数据均属于 `demo`，不得解释为真实欧莱雅业务数据或正式 SLA。

## 消费者端

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
模型名称或推理过程。`RESOLVE` 返回审核知识依据；`ASK` 每轮只问一个关键问题；无审核依据时显式
进入 `HANDOFF`；命中高风险症状时进入 `BLOCK`，停止产品推荐并保留安全提醒。

附件字段当前只校验 `product_image` 或 `order_screenshot` metadata，属于后续文件 provider 的预留入口。
收到附件时 API 会明确告知无法读取内容并请求转人工，不执行
真实图片识别，也不保存文件内容。

### 人工交接和反馈

- `POST /v1/conversations/{conversation_id}/handoff`：记录用户是否同意转人工；同意时使用
  `idempotency_key` 幂等创建服务事件。
- `GET /v1/events/{event_id}`：查看等待接管、处理中或已完成状态及演示预计响应时间。
- `POST /v1/conversations/{conversation_id}/feedback`：把是否解决和开放反馈绑定到最新
  `result_id`。反馈只进入待分析数据，不自动训练模型或修改风险规则。

## 人工客服工作台

- `GET /v1/agent/events`：按风险优先级和等待时间返回事件队列。
- `GET /v1/agent/conversations/{conversation_id}`：返回消费者原话、共情卡、事实与推断、缺失
  信息、风险、知识依据、建议下一步和审计轨迹。
- `POST /v1/agent/events/{event_id}/actions`：记录回复、索要材料、建立售后记录、升级专家或关闭
  事件。比赛版记录统一使用 `demo_agent`，生产环境必须接入身份认证与授权。

## 品牌洞察

`GET /v1/insights/overview` 返回咨询量、反馈解决率、转人工率、重复提问率和高频未解决问题。
每项指标包含时间范围、样本数和 `demo`/`real` 属性；默认且当前实际支持的属性为 `demo`。

## 状态和版本

全局状态为 `RESOLVE`、`ASK`、`HANDOFF` 和 `BLOCK`。MongoDB 持久化保存状态切换原因、规则版本、
知识版本、结果编号、人工动作和反馈。当前版本由 `SCHEMA_VERSION`、`RULE_VERSION` 和
`KNOWLEDGE_VERSION` 配置。

## 错误行为

- 空白或超过限制的输入返回 `422`。
- 不存在的会话或事件返回 `404`。
- feedback 的 `result_id` 不是该会话最新结果时返回 `409`。
- 无知识命中不会生成产品事实，而是显式请求转人工。
