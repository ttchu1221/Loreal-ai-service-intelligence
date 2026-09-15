# ADR 001 Provider和决策边界

状态：Proposed，等待 3 号确认 AI 语义和 1 号确认业务规则

## 背景

Delivery Plan V2.2 要求 3、4 号共同冻结状态机、领域模型、AI Schema、Provider、异常降级、日志
字段和版本。4 号负责稳定实现，但不能把 AI 判断策略固化在 HTTP route 或数据库 adapter 中。

## 决策

- `ConversationOrchestrator` 只负责流程调度、持久化和副作用。
- `DecisionPolicy` 负责返回一张经过 Schema 校验的 EmpathyCard，不执行副作用。
- `IntentProvider` 和 `KnowledgeProvider` 分别提供结构化意图和审核知识依据。
- 所有候选 DecisionPolicy 先经过 `SafetyFirstDecisionPolicy`，风险命中时不调用下游候选。
- 外部 LLM 输出被视为不可信；异常、timeout、非法结构和低置信度使用 deterministic fallback。
- Schema、rule、knowledge、model 和 Prompt 必须独立版本化；共享 Schema 变更需 3、4 号共同确认。

## 影响

真实 AI、Mock 和 deterministic fallback 可以通过同一 application factory 注入。测试可以替换
provider 而不连接外部服务。代价是需要维护 adapter contract 和额外的 regression tests；真实模型
接入前仍需补 model/Prompt version、调用审计以及经过批准的 AI 语义。

## 冻结条件

3 号确认 DecisionPolicy、Intent 和 evidence 的语义，1 号确认 ASK/GUIDE/HANDOFF/BLOCK 业务规则
后，将状态改为 Accepted，并记录确认日期和对应 commit。任何字段变更需新增 ADR 或修订本 ADR，
不能仅修改代码。
