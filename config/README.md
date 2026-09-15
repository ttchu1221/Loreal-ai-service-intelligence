# Config

此目录保存各 environment 的非敏感默认配置。

- `local.example`：`scripts/bootstrap.sh` 创建本地根目录 `.env` 的模板，只包含 LLM 接入项。
- `development.example`：本地开发和 hot reload 的非敏感模板。
- `test.example`：automated test 使用的隔离配置模板。
- `production.example`：production 的安全默认值模板，不包含 secret，也不代替 secret manager。

优先级从高到低为 process environment、由 `APP_CONFIG_FILE` 选择的配置文件、代码默认值。
`scripts/dev.sh` 默认选择根目录 `.env`；未出现在其中的 application、MongoDB、Schema 和 Mock 设置
使用 `config.py` 的默认值。也可以把其他 runtime config path 作为第一个参数。

API key、credential 和 private endpoint 等 secret 只能写入本地 `.env` 或由 deployment
platform 注入，禁止加入本目录或 commit 到 Git。所有 `*.env` 都被 `.gitignore` 忽略，提交前的
`scripts/check.sh` 也会拒绝已被 Git tracking 的 runtime env 文件。
