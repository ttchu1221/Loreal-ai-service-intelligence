# Data

此目录用于本地数据流转，实际数据默认不会被 Git 跟踪。

- `raw/`：未经修改的原始输入，只读保存。
- `interim/`：清洗、解析或转换过程中的中间结果，可重新生成。
- `processed/`：可供 application 或 evaluation 使用的最终数据。

不要在此保存 credential、customer data、个人敏感信息或未经授权的 model input/output。新增
data pipeline 时，应记录数据来源、schema、处理步骤、retention policy 和可复现方式。

三产品知识与语义规则工作簿可通过 `scripts/convert_product_knowledge.py` 转换，生成物放入
`data/processed/`；完整 schema 和知识门禁见
[`docs/product-knowledge-conversion.md`](../docs/product-knowledge-conversion.md)。
