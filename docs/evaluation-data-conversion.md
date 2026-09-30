# Eval 案例数据转换

`scripts/convert_eval_cases.py` 将产品或业务人员导出的 TSV 文本转换成结构化 JSON。TSV 单元格可以
包含多行聊天，文件可使用 UTF-8 或带 BOM 的 UTF-8。

## 使用方式

```bash
.venv/bin/python scripts/convert_eval_cases.py \
  /absolute/path/to/source.txt \
  data/processed/ai_eval_cases_v2.json
```

成功后 command 会输出生成路径、案例数量和三种服务模式的分布。添加 `--compact` 可生成无缩进的
JSON。输出文件使用临时文件替换，校验失败时不会覆盖已有的完整结果。

## 数据边界

每条案例严格分为以下区域：

- `input`：模型允许看到的聊天、cutoff 和关联记录编号；
- `expected`：仅供 Eval 使用的正确意图、服务模式、回复/交接要求、依据与禁止行为；
- `revision_notes`：标注修订记录，仅供数据治理和追溯。

调用模型时只能传入 `input`，不得把 `expected` 或 `revision_notes` 放进 prompt。转换器会检查必要
表头、重复 `case_id`、服务模式以及 cutoff 是否等于最后一条可见消息序号。

原始表格只有时分秒时，转换器保留 `time_local`，不会虚构日期；只有关联编号时，也不会伪造完整
订单、工单状态或知识正文。因此生成物可直接作为 Eval 标注集使用，但在发送给
`POST /v1/competition/sessions/analyze` 前，仍须由正式数据 provider 补齐完整 snapshot、时间戳、
订单、工单和知识 evidence。

## 数据存储

原始输入应放在 `data/raw/`，转换结果放在 `data/processed/`。两个目录中的实际数据默认由
`.gitignore` 排除，不应提交真实客服会话、客户信息或其他敏感内容。

## 运行 Eval

```bash
.venv/bin/python scripts/run_eval.py \
  data/processed/ai_eval_cases_v2.json \
  data/processed/ai_eval_report.json \
  --reference-date 2026-09-30
```

`--reference-date` 仅用于把原始材料的时分秒转换为 API 所需时间戳，不参与业务判断，也不表示真实
聊天日期。runner 使用隔离的 Memory repository 和关闭 LLM 的 deterministic baseline，不依赖
MongoDB，也不会读取本地 `.env` 或发起外部请求。

报告自动计算服务模式准确率、`HUMAN_REQUIRED` recall、`AUTO_REPLY` precision、输入完整率和三模式
分布，并保留逐案例结果。以下内容不会伪装成自动得分：

- 自然语言用户目标与系统 taxonomy intent 的对应关系；
- 回复/交接质量；
- evidence 完整度；
- 自然语言禁止项是否违规。

这些指标需要产品方补充稳定 taxonomy、完整订单/工单/知识 snapshot，以及人工或独立 LLM judge
rubric。报告的 `manual_review` 仅在系统完成决策后附加，绝不会传入模型或业务服务。
