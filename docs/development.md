# 开发环境

## 初始化

```bash
scripts/bootstrap.sh
```

该脚本会创建 `.venv`、安装 application 与 dev dependency，并在 `.env` 不存在时从
`config/local.example` 创建只包含 LLM 接入项的本地文件。其他功能使用 `config.py` 默认值，不需要
重复写入 `.env`。脚本可以重复运行，不会覆盖已有 `.env`。所有 `*.env` 均被 Git 忽略；可提交的
无敏感配置模板统一使用 `*.example` 后缀。

如果默认的 `python3` 不合适，可以指定其他 executable：

```bash
PYTHON_BIN=python3.11 scripts/bootstrap.sh
```

## 启动服务

先启动本地 MongoDB：

```bash
scripts/mongo-dev.sh
```

再启动 API：

```bash
scripts/dev.sh
```

默认使用根目录 `.env`，便于本地注入不会被 Git 追踪的 credential。传入 config path 可以切换
environment；production credential 仍应由 runtime secret 注入：

```bash
scripts/dev.sh config/production.example
```

## 一键启动演示

完成一次 `scripts/bootstrap.sh` 后，可以用一个 command 启动本地 MongoDB 与 API：

```bash
scripts/demo-start.sh
```

脚本会等待服务就绪，并在 macOS 自动打开消费者端与客服端页面。按 `Ctrl+C` 后，脚本只会停止
由本次运行启动的进程；如果 MongoDB 在运行前已经存在，则会保留该进程。若不希望自动打开页面：

```bash
OPEN_BROWSER=false scripts/demo-start.sh
```

页面中的推荐演示顺序为：消费者开始咨询、继续排查、转人工，然后到客服端刷新队列、查看完整
接管包并处理 Ticket。

### 双端完整演示流程

1. 打开消费者端 <http://127.0.0.1:8000/workspace/consumer>，发送“我的底妆总是搓泥，怎么办？”。
   发送时输入框会立即清空；消息超过可视区域后，可将鼠标停在对话区并使用滚轮查看历史消息。
   点击右上角“清空会话”可清空当前页面并开始新会话；后端已产生的会话和审计记录不会被删除。
   页面发送后会清空输入框，但不会替消费者预填下一条消息；长文本会在消息气泡内自动换行。
2. 按 AI 的问题补充肤质、护肤步骤或产品类型，观察状态从 `ASK` 进入 `GUIDE`，并记录建议执行结果。
3. 验证两种转人工路径中的任意一种：
   - 直接发送“我要人工客服”，系统立即自动建单；
   - 提出当前知识无法回答的问题，由 AI 可回答性与安全规则自动判定并建单。
4. 打开人工客服端 <http://127.0.0.1:8000/workspace/agent>。队列每三秒自动刷新，首个新 Ticket 会
   自动打开；页面会显示最近同步时间，连接失败时直接显示错误。检查消费者原话、双方已沟通内容、
   确认事实、尝试记录和转人工原因。
5. 人工客服填写回复并提交处理动作。消费者端每两秒同步进度，无需重新创建会话。
   客服队列时间按服务端 UTC 正确转换为浏览器本地时间。人工回复会写入共享 transcript，并以
   “人工客服”消息气泡展示给消费者。客服回复框支持 `Enter` 发送、`Shift+Enter` 换行，空回复不会
   提交，提交期间按钮会显示进行中状态并阻止重复操作。
6. 回到消费者端读取人工回复并继续发送消息；转人工后的新消息会直接同步给客服，不再进入 AI
   决策。客服工作台每三秒刷新当前完整对话。处理完成后，由消费者选择“已解决”或“仍需处理”；
   后者会重新打开 Ticket。
7. 人工客服确认本次处理结束后点击“关闭会话”，会话会从待处理队列移除；消费者若选择“仍需处理”，
   同一 Ticket 会恢复为待处理状态并重新进入客服队列。

如果消费者明确说“不需要人工”，系统不会建单，而是继续追问具体问题；之后仍无法回答时才自动
转人工。浏览器会在本地保存消费者的 `conversation_id`，刷新页面后通过会话恢复接口重新展示完整
user/assistant transcript；若后端数据已清理，页面会清除失效 ID、显示可见错误并提示重新咨询。
页面只会在会话进入 `HANDOFF` 或 `BLOCK`、已实际创建人工 Ticket 后轮询客服进度；普通 AI
会话不会请求 Ticket endpoint。

### 启动故障排查

- 提示找不到 `mongod`：macOS 先运行
  `brew tap mongodb/brew && brew install mongodb-community`，再重新执行一键启动脚本。
- 提示端口 `8000` 被占用：停止已有 API，或运行
  `APP_PORT=8001 scripts/demo-start.sh`，并使用脚本输出的新地址。
- LLM 配置修改后没有生效：确认值保存在根目录 `.env`，停止当前脚本后重新启动；不要把 `.env`
  或真实 key 复制到 `config/*.example`。
- 不需要真实 LLM 时：将 `.env` 中 `LLM_ENABLED=false`，其余流程仍可使用 deterministic fallback
  完整演示。

## Test 与检查

```bash
scripts/test.sh
scripts/check.sh
```

演示前可使用纯虚构数据执行完整 smoke test；它使用内存 repository，不写入 MongoDB：

```bash
.venv/bin/python scripts/demo_smoke.py
```

输出最后一行为 `FULL_CHAIN_OK` 时，表示 Mock、ASK/GUIDE、Case、Attempt、feedback、人工建单、
客服动作、Ticket 结果、洞察和两个 workspace endpoint 已全部走通。
消费者 workspace 使用对话式布局并实时展示人工服务进度；客服 workspace 使用工单工作台布局，
在窄屏下会自动折叠为纵向区域。两个页面均为无 frontend dependency 的 Demo 客户端。

`scripts/test.sh` 会把额外 argument 透传给 pytest，例如：

```bash
scripts/test.sh tests/test_health.py -q
```

## Data

`data/raw`、`data/interim` 和 `data/processed` 分别用于原始、中间和处理完成的数据。Git 只追踪
目录结构，不追踪实际数据文件。详细规则见 [`data/README.md`](../data/README.md)。

## Sandbox

运行默认的本地实验：

```bash
scripts/sandbox.sh
```

也可以把实验脚本 path 作为第一个 argument。script 会使用项目 `.venv`，默认加载
根目录 `.env`，并把 `SANDBOX_OUTPUT_DIR` 指向 `sandbox/output/`。详细说明见
[`sandbox/README.md`](../sandbox/README.md)。
