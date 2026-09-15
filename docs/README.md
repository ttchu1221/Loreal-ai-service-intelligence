# 项目文档

详细项目文档统一放在此目录，并在新增文档时维护本索引。

## 使用与运行

- [开发环境](development.md)：config、data、sandbox 和 scripts 的使用方式。
- [Configuration](configuration.md)：environment variable、加载顺序与安全边界。
- [部署与恢复](deployment.md)：非 Docker 冷启动、启动检查、稳定版本、恢复和降级边界。
- [MongoDB](mongodb.md)：本地启动、collection、index 与 production 安全要求。

## 接口与架构

- [比赛 MVP API](api.md)：消费者、人工客服与品牌洞察 endpoint、状态语义和 error behavior。
- [比赛 MVP Backend Architecture](architecture.md)：请求链路、状态机、持久化、provider 边界和
  production 接入路线。
- [P0 系统架构与技术接口](system-architecture-and-interfaces.md)：4 号负责的数据库、状态机、API
  和可调用 AI Mock contract。

## 完成度与决策

- [4号 V2.2 完成度审计](role-4-v2.2-completion-audit.md)：逐项代码证据、缺口、依赖和发布阻断项。
- [ADR 001 Provider和决策边界](adr/001-provider-and-decision-boundaries.md)：AI contract 与安全优先
  注入决策；当前状态为 Proposed，尚待 1、3 号共同冻结。

当前可运行的是本地 P0 主链路、deterministic Mock 与可选 LLM intent/上下文回复 adapter。真实 RAG、外部售后、
认证授权、通知送达和 production 验收尚未完成，不能因 contract 或 Mock 存在而标记为已集成。

## 后续文档

在对应能力实际存在时，再建立 `integrations/` 或 `migrations/`，不要创建空 placeholder。
