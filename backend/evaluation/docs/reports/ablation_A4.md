# 消融实验 A4: 混合-偏 BM25

- 生成时间: 2026-07-26 18:53:26
- 评估条目: 15
- 总耗时: 92.4s (平均 6.16s/条)
- 配置: retriever=hybrid v_w=1.0 b_w=2.0 rerank=False

## 1. 总体指标

| 指标 | 平均分 | 最低 | 最高 | 成功数 | 失败数 |
|---|---|---|---|---|---|
| faithfulness | 0.6839 | 0.3871 | 1.0 | 15 | 0 |
| answer_relevancy | 0.7086 | 0.0 | 0.9278 | 15 | 0 |
| context_precision | 0.3267 | 0.0 | 1.0 | 15 | 0 |
| context_recall | 0.1556 | 0.0 | 1.0 | 15 | 0 |

## 2. 按场景分组

| 场景 | 数量 | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|---|---|
| aggregation | 2 | 0.7255 | 0.6483 | 0.0 | 0.0 |
| error_diagnosis | 2 | 0.6278 | 0.8509 | 0.5 | 0.25 |
| performance | 2 | 0.6279 | 0.4375 | 0.3778 | 0.25 |
| resource | 2 | 0.4877 | 0.6763 | 0.3333 | 0.0 |
| security | 2 | 0.7054 | 0.791 | 0.5 | 0.0 |
| service_health | 2 | 0.7395 | 0.8204 | 0.5 | 0.5 |
| time_analysis | 1 | 1.0 | 0.5256 | 0.0 | 0.0 |
| user_activity | 2 | 0.7157 | 0.8275 | 0.2389 | 0.1667 |

## 3. 性能指标

- 平均检索耗时: 0.195s
- 平均 LLM 耗时: 3.497s
- 平均 Token 数: 759
