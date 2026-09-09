# L'Oréal AI Service Intelligence

面向智能服务场景的 Python API 项目基础骨架。

## 环境要求

- Python 3.9+

## 本地开发

```bash
scripts/bootstrap.sh
scripts/dev.sh
```

服务启动后可访问：

- 健康检查：<http://127.0.0.1:8000/health>
- API 文档：<http://127.0.0.1:8000/docs>

## 质量检查

```bash
scripts/check.sh
```

## 项目结构

```text
src/loreal_ai_service_intelligence/  # 应用代码
tests/                               # 自动化测试
docs/                                # 详细项目文档
config/                              # environment 配置
data/                                # 本地数据分层
sandbox/                             # 本地实验区
scripts/                             # 开发与验证脚本
```

## 开发规范

仓库级开发要求见 [AGENTS.md](AGENTS.md)，版本变更记录见
[CHANGELOG.md](CHANGELOG.md)，详细文档索引见 [docs/README.md](docs/README.md)。

config、data、sandbox 和 scripts 的完整说明见
[开发环境文档](docs/development.md)。
