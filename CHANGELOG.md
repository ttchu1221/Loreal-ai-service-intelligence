# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added repository-wide development instructions and documentation conventions.
- Added the initial FastAPI service skeleton and health endpoint.
- 新增 development、test 和 production 的 config 模板与类型化 runtime settings。
- 新增本地 sandbox、data 分层和可重复执行的开发 scripts。
- 新增 config 与本地开发流程文档。
- 新增比赛 MVP 的消费者咨询、四状态编排、风险守卫、知识依据和反馈 API。
- 新增 MongoDB 会话、审计、幂等人工事件、客服动作和品牌洞察持久化能力。
- 新增人工客服队列与完整接管包 API，并保留消费者端内部标签隔离。
- 新增比赛 MVP API、architecture、演示边界和 error behavior 文档。
- 新增 MongoDB 本地启动脚本、collection/index 文档和 database unavailable 安全降级。
- 新增可注入的 `IntentProvider` 和规则 fallback；外部模型异常、非法输出或低置信度时自动降级，高风险安全规则始终优先执行。
- 新增可注入的 `KnowledgeProvider` interface，为后续真实 RAG provider 保留稳定边界。

### Changed

- Defined Chinese as the default language for non-technical communication while keeping
  established technical terms in English.
- 调整对话理解为当前消息优先，避免历史风险词污染后续轮次，并修正交易与使用等重叠意图优先级。
- 回复会按意图选择文案；未接入文件处理时明确告知附件不可读取，非风险转人工拒绝不再显示医疗提示。

### Fixed

- 修复否定、假设、第三方主体和已恢复症状被简单关键词误判为高风险的问题。
- 修复通用知识因单个关键词命中而错误回答不良反应、功效承诺或订单问题的问题。
- 修复固定场景、固定推断和伪造 `demo_agent` 审计主体造成的误导。

## [0.1.0] - 2026-09-09

### Added

- Initialized the project repository.
