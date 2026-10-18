# V1 当前已知问题

本文记录 2026-09-30 V1 测试阶段结束时仍存在的限制。状态为“已通过 12 条 reviewed Eval”只表示当前
服务模式与经证据核验后的标注一致，不表示 production 数据和全部三模式已经完成验收。

## 问题清单

| ID | 状态 | 问题 | 当前影响 | 解除条件 |
| --- | --- | --- | --- | --- |
| V1-ISSUE-001 | 阻断 AUTO_REPLY 验收 | reviewed Eval 中没有满足证据要求的 `AUTO_REPLY` 案例 | `service_mode_accuracy=1.0`，但 `AUTO_REPLY precision` 为不可计算；不能据此宣称自动回复质量已通过 | 至少补充一条商品唯一匹配、知识有效且允许自动引用的真实案例，并验证自动发送门禁 |
| V1-ISSUE-002 | 待业务数据 | C-001 的“测试修护精华液30ml”没有真实 product ID、SKU 或中国市场官方保存说明 | 不能证明该商品无需冷藏，只能进入 `AGENT_ASSIST` | 提供完整商品名、SKU、包装保存说明和审核记录；以新 review 版本重新评估 |
| V1-ISSUE-003 | 待业务数据 | C-004 的 `#01赤茶红/#05枫叶红` 无法映射到具体口红系列和 SKU | 不能套用其他雾面口红的保湿或“不拔干”宣称，只能进入 `AGENT_ASSIST` | 提供具体系列、SKU 和该配方的官方质地说明，并完成人工审核 |
| V1-ISSUE-004 | 待集成 | 三产品知识与语义规则已转换为 JSON，但 runtime 尚未配置 JSON-backed `CompetitionRetrievalProvider` 和 routing rule loader | API 不会自动加载新知识 bundle；转换成功不等于在线检索生效 | 实现 provider、启动配置、失败降级、reload/version 策略和 integration test |
| V1-ISSUE-005 | 待上游数据 | 12 条 Eval 只有聊天和关联编号，没有完整商品、订单、工单、物流与知识 snapshot | `input_complete_rate=0.0`；订单、物流和售后动作不能进行完整端到端验证 | 上游按 P0 contract 提供带归属校验、时间戳和来源版本的完整 snapshot |
| V1-ISSUE-006 | 待人工评审 | 当前自动指标不判断回复质量、依据完整度和自然语言禁止项 | 12/12 只代表服务模式匹配，不能代表话术和依据达到最终比赛标准 | 冻结 rubric，完成人工或独立 LLM judge，并记录逐案例结论 |
| V1-ISSUE-007 | 待 production 接入 | 真实 RAG、售后/物流系统、认证授权和通知送达仍未接入 | 当前仍是本地 P0/Mock 能力，不应标记为 production-ready | 完成外部系统 contract、权限、timeout、retry、审计、监控和验收 |

## 已完成且不应回退的保护

- 原始 12 条数据不覆盖；修订通过 `config/eval_evidence_review_v1.json` 形成独立审计记录。
- review overlay 只能向更保守的模式调整，不能提升自动发送权限。
- LLM 只生成话术，不能修改 service mode、risk、发送权限或下一步动作。
- 模型、检索和运行记录失败均需可见降级，且不能泄露内部异常或 secret。
- `.env`、原始业务数据、Eval dataset 和生成报告均不得提交到 Git。

## 当前验证快照

2026-09-30 验证结果：

- reviewed Eval：12/12 服务模式匹配；
- expected/actual 分布：`AGENT_ASSIST=8`、`HUMAN_REQUIRED=4`、`AUTO_REPLY=0`；
- `HUMAN_REQUIRED recall=1.0`；
- `AUTO_REPLY precision`：不可计算；
- `input_complete_rate=0.0`；
- Ruff、format check 和 103 个 pytest 均通过。

上述数字用于标记 V1 当时状态。后续数据、规则或代码发生变化后必须重新执行测试并更新记录，不能把
本快照当作持续有效的测试证明。
