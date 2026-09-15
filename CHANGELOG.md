# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- 人工客服工作台将完整 transcript 改为与消费者端一致的聊天气泡布局，交接摘要折叠展示；客服可在
  处理完成后关闭会话，关闭项会移出待处理队列，消费者反馈“仍需处理”时自动重新入队。
- 客服端状态改为中文可读文案，回复框支持 `Enter` 发送和 `Shift+Enter` 换行，并增加空内容校验、
  操作中状态和重复提交保护；README 新增消费者端与客服端界面预览。
- 启用 LLM 后，消费者普通回复会结合最近对话、用户当前表达、决策状态和已审核知识动态生成，不再只展示固定模板；安全阻断与转人工仍保持确定性话术。
- 转人工后的消费者消息会保持在人工服务流程，并与客服回复共同写入共享 transcript；客服与消费者现在可以围绕同一 Ticket 持续对话。
- 高风险 `BLOCK` 会话进入人工接管后保持安全阻断状态；消费者后续消息仍会同步给客服，但不会由新一轮 AI 分类解除阻断。

### Fixed

- 修复 LLM 仅参与 intent 分类、配置真实模型后消费者话术仍然单一的问题；生成异常或非法输出会自动回退且不影响主流程。
- 修复消费者转人工后客服工作台只刷新队列但不打开工单，以及部分浏览器因隐式 DOM 全局变量导致页面无反应的问题；新工单现会自动展示，并显示同步状态或错误。
- 修复消费者发送消息后，部分浏览器因 `message`、`messages` 等隐式 DOM 全局变量失效而造成页面卡住的问题；同时取消 `ASK` 状态下自动覆盖消费者输入，并支持长消息安全换行。
- 修复消费者对话区的消息气泡被 flex 布局压缩、无法形成有效滚动区域的问题；现在顶部栏和输入区固定，消息气泡不收缩，支持鼠标滚轮和触摸滑动。发送时输入框会立即清空，并新增“清空会话”入口以开始新的本地会话。
- 消费者与客服演示 workspace 现在返回 `Cache-Control: no-store`，避免重启后浏览器继续展示旧版页面资源。
- 修复客服工作台内嵌 JavaScript 的换行符被服务端模板错误展开、导致整个脚本语法错误且无法加载消费者会话的问题。
- 修复消费者工作台“清空会话”文案中的换行符破坏内嵌 JavaScript、导致发送按钮完全无响应的问题。
- 修复客服队列把无时区 MongoDB 时间误当作浏览器本地时间的问题；队列时间现在按 UTC 解析后转换为本地时间。

### Added

- 新增 agent-first `/v1/agent/intakes` 主入口，可融合聊天、订单和历史工单，消费者进线即创建客服
  事件，并生成服务轨迹、意图、情绪、风险、回复草稿、依据、下一步动作与业务升级方向；客服工作台
  可直接展示并使用该辅助包。
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
- 新增底妆搓泥 `GUIDE` 短链路、可更正 Case、独立 Attempt 执行记录和带版本 Ticket 结果事件。
- 新增消费者与人工客服最小 web workspace，以及部署恢复说明。
- 新增 4 号 P0 系统架构与技术接口文档，以及支持 HTTP/Python 调用的 typed deterministic AI Mock
  decision package。
- 新增可重复执行的虚构数据全链路演示 smoke test，并补齐消费者继续对话、反馈、转人工和客服
  Ticket 操作页面。
- 新增一键演示启动脚本，自动启动 MongoDB 与 API、等待服务就绪并打开两个演示 workspace。
- 新增 V2.2 4号职责代码完成度审计、Provider/DecisionPolicy ADR 和 OpenAI-compatible intent
  adapter；支持结构化输出校验、timeout、有限 retry 与 deterministic fallback。
- 新增 ProductContext、Hypothesis、KnowledgeItem、Improvement 领域合同，并将安全策略与
  DecisionPolicy 从编排器中解耦。

### Changed

- 重设计消费者与客服 workspace：消费者端采用响应式聊天界面、消息气泡和服务进度，客服端采用
  工单队列、可读交接面板、回复区与处理动作分区，并补充键盘 focus 和 reduced-motion 支持。

- Defined Chinese as the default language for non-technical communication while keeping
  established technical terms in English.
- 应用代码按 `api`、`domain`、`services`、`providers` 和 `infrastructure` 职责重新分包，并保留
  原有 ASGI `main` 入口兼容现有启动方式，为真实 LLM/RAG adapter 提供明确落点。
- 调整对话理解为当前消息优先，避免历史风险词污染后续轮次，并修正交易与使用等重叠意图优先级。
- 回复会按意图选择文案；未接入文件处理时明确告知附件不可读取，非风险转人工拒绝不再显示医疗提示。
- 更新 README、API 和 architecture 文档，补充当前能力、请求链路、external integration 边界及
  production 分阶段接入路线、LLM 配置与一键演示流程，并修正过时的客服审计主体和 config 模板说明。
- 人工回复、动作完成、用户确认解决和重开改为独立 Ticket 事件，避免虚假完成。

### Fixed

- 修复消费者页面恢复普通 AI 会话后仍轮询人工 Ticket、持续产生 `404` 请求的问题。
- 修复消费者 workspace 请求失败时错误不可见、刷新后丢失对话、发送期间可重复提交，以及圆形发送
  按钮被长文本撑坏的问题；新增消费者会话 transcript 恢复接口。
- 打通消费者与人工客服 workspace 协作：消费者可轮询 Ticket、查看最新人工回复并确认解决或继续
  处理；客服队列自动刷新，且不再代替消费者确认结果。
- 修复人工交接依赖消费者二次点击的问题：AI/规则判定 `HANDOFF` 或 `BLOCK` 后自动幂等建单，客服
  交接视图同步完整对话、Case、确认事实、建议执行记录及转人工原因。
- 明确消费者人工选择优先级：对话中直接要求人工会立即建单；未选择人工时继续 AI 服务，仅在无法
  可靠回答或安全规则阻断时转交客服。

- 修复本地启动未加载根目录 `.env`、导致 LLM credential 和 endpoint 配置不生效的问题。
- 所有 `*.env` 均从 Git tracking 范围移除；无敏感配置模板改用 `config/*.example`，避免误上传
  runtime credential；本地 `.env` 模板精简为只包含 LLM 开关、地址、模型和 API key。
- 修复否定、假设、第三方主体和已恢复症状被简单关键词误判为高风险的问题。
- 修复通用知识因单个关键词命中而错误回答不良反应、功效承诺或订单问题的问题。
- 修复固定场景、固定推断和伪造 `demo_agent` 审计主体造成的误导。
- 修复搓泥 `GUIDE` 混入色号知识、导致一次展示多个排查方向的问题。

## [0.1.0] - 2026-09-09

### Added

- Initialized the project repository.
