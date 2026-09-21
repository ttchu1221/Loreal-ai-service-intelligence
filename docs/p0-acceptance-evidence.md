# 比赛版 P0 验收执行记录

本文记录 4号开发与集成范围内的可重复自动化证据。产品清单中的 TC 是验收设计，不等于官方数据或
模型质量结果；当前测试使用显式 Mock snapshot，验证接口、权限、状态和失败行为。官方数据绑定和
Gold 标签到位后，可以在不修改 API 的情况下替换 fixture 重跑。

## 覆盖结果

| 用例 | 工程验证 | 自动化证据 |
| --- | --- | --- |
| TC01 TC02 | W01/W02 只在商品和有效知识齐全时自动，回执为 SIMULATED | `test_tc01_auto_reply_requires_valid_whitelist_evidence_and_records_receipt` |
| TC03 TC04 | W03/W04 要求单一归属正确且有效的订单，草稿含快照时间 | Competition service whitelist tests and contract |
| TC05 TC06 | 售后进入辅助人工，历史承诺和处理中状态可追溯，不宣称到账 | `test_tc06_repeated_refund_intake_restores_promise_without_claiming_completion` |
| TC07 | 附件存在时进入人工辅助，不执行图片识别 | deterministic route and workspace text |
| TC08 TC09 TC10 | 不适、就医、明确人工均强制人工并设置锁；风险不生成消费者回复 | `test_tc08_tc09_*` and `test_tc10_*` |
| TC11 TC12 TC13 TC14 | 缺商品只补问一个主问题；无效证据/同时点冲突强制人工；多订单辅助 | `test_tc11_*`, `test_tc12_*`, `test_tc14_*` |
| TC15 TC16 TC17 TC18 | 首次未解决辅助、第二次强制；投诉/安全异常强制；冲突不自动执行 | `test_tc14_*`, `test_tc16_tc17_*`, conflict tests |
| TC19 | provider 未配置返回 503；source failure 输入强制人工 | `test_tc19_provider_missing_*` |
| TC20 TC21 TC22 | UNKNOWN 锁发送；接管锁跨分析保留；发送 idempotency 防重复 | `test_tc20_*`, `test_tc21_*`, TC01 repeat send |
| TC23 | 拒绝保留原草稿和原因；人工更正保留原值 | `test_tc23_feedback_and_correction_preserve_ai_original` |
| TC24 | 售后动作只保存 PENDING_MANUAL 或 SIMULATED，绝不标记外部执行 | `test_tc24_external_actions_are_only_pending_manual_or_simulated` |
| TC25 TC26 | 明确确认且无开放风险/动作才能解决；归档和重开保留人工锁 | `test_tc25_*`, `test_tc26_*` |
| TC27 | repository 异常由统一 503 处理；业务层不在写入失败时宣称成功 | existing database failure regression and atomic save boundary |
| TC28 | 错误 owner 强制人工且不返回他人记录 evidence | `test_tc28_wrong_owner_is_blocked_and_never_exposed_as_evidence` |
| TC29 | cutoff 后消息在 Schema 边界拒绝；空/失效 evidence 不进入自动发送 | `test_tc29_future_message_is_rejected_at_schema_boundary` |
| TC30 | 比赛工作台可启动，包含三模式、四区域与 SIMULATED 标识 | `test_tc30_competition_workspace_exposes_three_modes_and_four_regions` |

## 执行命令

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
.venv/bin/python scripts/demo_smoke.py
```

验收报告必须记录实际运行结果，不得把本表中的目标或用例设计写成模型质量成绩。外部通道、官方数据
和真实业务执行仍未接入，当前状态固定标记 Mock 或 SIMULATED。
