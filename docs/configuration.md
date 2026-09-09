# Configuration

应用通过 `pydantic-settings` 读取 environment variable。

## 加载方式

默认读取项目根目录的 `.env`。如果设置了 `APP_CONFIG_FILE`，则读取该文件作为默认配置；process
environment 中的同名变量始终拥有更高优先级。

```bash
APP_CONFIG_FILE=config/test.env python -m loreal_ai_service_intelligence.cli
```

`scripts/dev.sh` 默认选择 `config/development.env`，也可以传入其他文件：

```bash
scripts/dev.sh config/production.env
```

## 可用设置

| Key | 类型 | 默认值 | 用途 |
| --- | --- | --- | --- |
| `APP_NAME` | string | `L'Oreal AI Service Intelligence` | API 显示名称 |
| `APP_ENV` | enum | `development` | 当前 environment |
| `LOG_LEVEL` | string | `INFO` | application log level |
| `APP_HOST` | string | `127.0.0.1` | bind address |
| `APP_PORT` | integer | `8000` | bind port |
| `APP_RELOAD` | boolean | `false` | 是否启用 hot reload |
| `DATA_DIR` | path | `data` | data root directory |

## 安全边界

`config/` 中只能放非敏感默认值。API key、credential 和 private endpoint 必须存放在不被 Git
追踪的 `.env` 中，或由 deployment platform 注入。production 不应启用 `APP_RELOAD`。
