# 消融实验 A5: 混合 + 重排序

- 生成时间: 2026-07-26 19:06:20
- 评估条目: 15
- 总耗时: 198.9s (平均 13.26s/条)
- 配置: retriever=hybrid v_w=1.0 b_w=1.0 rerank=True

## 1. 总体指标

| 指标 | 平均分 | 最低 | 最高 | 成功数 | 失败数 |
|---|---|---|---|---|---|
| faithfulness | 0.6988 | 0.4091 | 0.8571 | 15 | 0 |
| answer_relevancy | 0.6484 | 0.0 | 0.876 | 15 | 0 |
| context_precision | 0.3356 | 0.0 | 1.0 | 15 | 0 |
| context_recall | 0.1333 | 0.0 | 1.0 | 15 | 0 |

## 2. 按场景分组

| 场景 | 数量 | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|---|---|
| aggregation | 2 | 0.8286 | 0.6668 | 0.0 | 0.0 |
| error_diagnosis | 2 | 0.7083 | 0.8368 | 0.5 | 0.25 |
| performance | 2 | 0.5633 | 0.4253 | 0.5 | 0.25 |
| resource | 2 | 0.6045 | 0.777 | 0.1 | 0.0 |
| security | 2 | 0.6667 | 0.7096 | 0.5 | 0.0 |
| service_health | 2 | 0.8175 | 0.7453 | 0.5 | 0.5 |
| time_analysis | 1 | 0.8077 | 0.5916 | 0.0 | 0.0 |
| user_activity | 2 | 0.6479 | 0.4063 | 0.4167 | 0.0 |

## 3. 性能指标

- 平均检索耗时: 0.351s
- 平均 LLM 耗时: 3.954s
- 平均 Token 数: 768
