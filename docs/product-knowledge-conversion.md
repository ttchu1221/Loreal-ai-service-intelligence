# 三产品知识与三情景语义库转换

`scripts/convert_product_knowledge.py` 将“欧莱雅三产品知识库与三情景语义库” XLSX 转换为稳定、
可审计的 JSON bundle。脚本只使用 Python standard library，不要求安装 Excel dependency，也不会修改
源工作簿。

## 使用方式

```bash
.venv/bin/python scripts/convert_product_knowledge.py \
  /absolute/path/to/三产品知识库与三情景语义库.xlsx \
  data/processed/three_product_knowledge_routing_v1.json
```

添加 `--compact` 可生成无缩进 JSON。脚本先完成全部读取与校验，再通过临时文件替换输出，转换失败时
不会留下半成品。

`data/processed/` 中的生成结果由 `.gitignore` 排除，不应 commit。源工作簿也应保存在仓库外或
`data/raw/`，避免把未审核数据误当作 application code 发布。

## 输出内容

JSON bundle 包含：

- `products`：与 `P0ProductSnapshot` 字段兼容的三款商品快照；
- `knowledge_evidence`：与 `P0KnowledgeEvidence` 字段兼容、通过严格门禁的知识；
- `evidence_constraints`：每条知识的属性、来源等级、引用限制、fallback 和 Excel 行号；
- `excluded_knowledge`：未进入自动回复证据的知识及排除原因；
- `semantic_rules`：三模式语义规则；
- `keyword_rules`：关键词扁平规则；
- `question_examples`：问题、预期模式、应答要求和禁止项；
- `conflict_rules`、`review_items`、`prohibited_knowledge`：冲突规则、待核验/红线和负面知识；
- `audit`：商品、知识、规则、关键词和样例数量，以及三模式分布。

## AUTO_REPLY 知识门禁

只有同时满足以下条件的产品知识才会写入 `knowledge_evidence`：

1. `核验状态` 必须严格等于 `已登记`；
2. `是否允许 AUTO_REPLY 引用` 必须以 `是` 开头；
3. 该权限不能只是“仅限禁止项”；
4. 知识正文不能为空；
5. 来源不能为空或 `—`。

因此，“待核验但允许原样播报”的备案号仍会进入 `excluded_knowledge`，不会被转换为
`valid=true`。`部分待核`、`存在冲突`、`缺失` 和红线内容同样不会成为有效知识。

每条有效知识都带有稳定 `evidence_id`、`product_id`、`scope`、工作簿版本、来源日期和
`valid=true`。`valid_until` 保留为 `null`，因为源表没有提供到期日期；正式接入前应由数据治理方
补充复核周期或失效策略。

## 校验与失败条件

转换器会拒绝以下输入：

- 缺少八个必要工作表之一；
- 找不到必要表头或无法解析版本日期；
- 商品缺少已登记且可引用的官方产品名；
- 语义规则编号重复或模式不是三种正式枚举；
- 关键词引用不存在的语义规则；
- 关键词模式与来源语义规则不一致；
- `AUTO_REPLY` 规则没有覆盖 W01 至 W04。

## 当前集成边界

转换完成不等于 runtime 已自动加载。当前 application 尚未配置 JSON-backed
`CompetitionRetrievalProvider` 和 routing rule loader；生成物是后续 provider 接入的正式输入。
W03/W04 仍需上游订单、物流快照，不能只靠本知识 bundle 自动回复。
