# 消融实验 A2: 纯 BM25

- 生成时间: 2026-07-26 18:50:14
- 评估条目: 15
- 总耗时: 110.9s (平均 7.39s/条)
- 配置: retriever=bm25 v_w=1.0 b_w=1.0 rerank=False

## 1. 总体指标

| 指标 | 平均分 | 最低 | 最高 | 成功数 | 失败数 |
|---|---|---|---|---|---|
| faithfulness | 0.693 | 0.4667 | 0.8667 | 15 | 0 |
| answer_relevancy | 0.6626 | 0.0 | 0.8657 | 15 | 0 |
| context_precision | 0.3781 | 0.0 | 1.0 | 15 | 0 |
| context_recall | 0.1333 | 0.0 | 1.0 | 15 | 0 |

## 2. 按场景分组

| 场景 | 数量 | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|---|---|
| aggregation | 2 | 0.7417 | 0.7169 | 0.0 | 0.0 |
| error_diagnosis | 2 | 0.6039 | 0.8455 | 0.5 | 0.25 |
| performance | 2 | 0.7018 | 0.3955 | 0.625 | 0.25 |
| resource | 2 | 0.6083 | 0.8016 | 0.3333 | 0.0 |
| security | 2 | 0.7077 | 0.7683 | 0.5 | 0.0 |
| service_health | 2 | 0.7944 | 0.7572 | 0.4021 | 0.5 |
| time_analysis | 1 | 0.75 | 0.5497 | 0.0 | 0.0 |
| user_activity | 2 | 0.6648 | 0.4094 | 0.475 | 0.0 |

## 3. 性能指标

- 平均检索耗时: 0.025s
- 平均 LLM 耗时: 3.701s
- 平均 Token 数: 760
