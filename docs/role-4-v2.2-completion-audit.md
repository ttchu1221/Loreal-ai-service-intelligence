# 4号开发与集成职责代码完成度审计

本文依据 Delivery Plan V2.2 核对 4 号在代码、接口、持久化、部署和文档方面的责任。附件只作为
需求来源；其中明确说明 V2.2 本身没有重新复核代码，因此本文件以当前 repository 的实际实现和
本次自动化测试为准。结论是：09 月 16 日架构门所需的工程合同和 Mock 已具备可评审版本，核心
P0 主链路已经可运行，但真实 AI/RAG 联调、正式权限、通知送达以及后续阶段验收不能标记完成。

## 当前结论

| V2.2任务 | 当前状态 | 代码或文档证据 | 尚需输入或后续动作 |
| --- | --- | --- | --- |
| T-10 系统架构、状态、领域模型、API、AI封装 | 已完成可评审稿 | `domain/models.py`、`providers/interfaces.py`、系统架构文档 | ProductContext、Hypothesis、Improvement 当前是合同模型，尚无独立业务 API |
| T-10A AI系统架构合同V1 | 工程侧完成，待联合冻结 | architecture、状态机、Provider contracts、ADR-001、Mock API | 3号确认 AI 语义、1号确认业务规则后才能把 ADR 改为 Accepted |
| T-11 Case API与版本持久化 | 已完成 | Case create/read/revision；更正同步 EmpathyCard `case_revision` 和 entities | 需要按 1 号正式 AC-01 至 AC-03 记录实际验收结果 |
| T-12 Attempt API | 已完成 | proposed/executed/skipped、observation、outcome 分离；重复建议返回冲突 | 语义级同义去重依赖 3 号策略候选 |
| T-14 编排集成 | 已完成工程解耦 | Orchestrator 只调度 `DecisionPolicy`；安全门在候选策略前强制执行 | 3号交付真实 DecisionPolicy 后注入回归 |
| T-16A 消费者模拟版 | 基本完成 | Mock、消费者 workspace、ASK/GUIDE、反馈、转人工 | 需与 1/5 号按最终原型逐按钮签字 |
| T-16B 真实AI与检索联调 | 部分完成，不得虚报 | 已提供 OpenAI-compatible intent/上下文回复 adapter 和 runtime factory | 缺正式评测通过的 3号 DecisionPolicy 和真实 KnowledgeProvider |
| T-17 日志、异常、降级、首次部署 | 部分完成 | audit trail、Mongo 503、LLM timeout/retry/fallback、本地启动脚本 | 缺独立新环境首次部署记录、正式 tracing 与外部服务错误分类；当前不含 Docker |
| T-20 Ticket与交接 | 已完成最小闭环 | 确认建单、幂等、交接包、取消不建单、结果事件、重开 | 外部售后系统和通知仍未接入 |
| T-21 客服工作台 | 部分完成 | 队列、交接详情、人工回复记录、动作完成、用户确认解决、重开 | AI草稿、真实送达凭据、认证客服身份未完成 |
| T-25 缺陷与回归 | 持续项 | regression tests、`scripts/check.sh`、`scripts/demo_smoke.py` | 需要 1 号缺陷表和挑战集后滚动关闭问题 |
| T-32A/T-32B V2候选集成与回归 | 未开始 | injection contract 已准备 | 等待 T-31 AI候选A；计划日期为 10 月 8 至 10 日 |
| T-38 部署恢复 | 文档基线完成，验收未完成 | `docs/deployment.md`、`scripts/demo-start.sh` | 10 月 14 至 16 日需基于锁定版本复核；非开发者冷启动属于 T-40 |

## 已冻结的工程边界

调用方向是 `api -> services -> domain`。`DecisionPolicy`、`IntentProvider`、`ResponseProvider` 和
`KnowledgeProvider` 是无副作用 contract；它们不能写数据库、建 Ticket 或执行客服动作。任何候选
DecisionPolicy 都先经过 `SafetyFirstDecisionPolicy`，因此不能通过注入绕开每轮风险检查。输出再由
Pydantic Schema 验证后才进入 persistence。

真实 LLM 的当前接入点为 `providers/openai_compatible.py`。启用后负责 intent 结构化识别，并在
确定性状态和审核 evidence 范围内结合最近对话生成消费者回复；模型异常、timeout、非法 JSON、
非法 intent、低置信度或非法回复均由现有 fallback 处理。最终状态写入和人工动作仍由服务端控制。
这个范围不能描述为完整 AI 已接入。

## 发布阻断项

以下内容在完成前只能用于本地 Demo，不能公开部署为 production：

- JWT/SSO、RBAC、真实客服身份和数据访问范围；
- 真实 RAG 的知识来源、地区、审核状态和 evidence ID 校验；
- 外部售后/通知送达、失败重试队列和可核验凭据；
- 独立新环境冷启动、备份恢复、并发认领和 rollback 演练；
- 3 号 AI 行为合同、Prompt、DecisionPolicy 候选和正式评测结果；
- 1 号 AC-01 至 AC-24 的逐例实际结果及 2 号真实用户测试记录。

## 验证命令

```bash
scripts/check.sh
.venv/bin/python scripts/demo_smoke.py
```

只有检查结果和 smoke 输出被实际保存后，才能在阶段验收中写“通过”；计划、Mock 或接口存在均不
等于真实集成完成。
