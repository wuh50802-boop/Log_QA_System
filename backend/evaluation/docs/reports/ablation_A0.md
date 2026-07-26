# 消融实验 A0: 基线（hybrid 等权）

- 生成时间: 2026-07-26 18:46:43
- 评估条目: 15
- 总耗时: 141.4s (平均 9.43s/条)
- 配置: retriever=hybrid v_w=1.0 b_w=1.0 rerank=False

## 1. 总体指标

| 指标 | 平均分 | 最低 | 最高 | 成功数 | 失败数 |
|---|---|---|---|---|---|
| faithfulness | 0.7059 | 0.5 | 0.8667 | 15 | 0 |
| answer_relevancy | 0.6573 | 0.0 | 0.8654 | 15 | 0 |
| context_precision | 0.3615 | 0.0 | 1.0 | 15 | 0 |
| context_recall | 0.1333 | 0.0 | 1.0 | 15 | 0 |

## 2. 按场景分组

| 场景 | 数量 | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|---|---|
| aggregation | 2 | 0.7411 | 0.6546 | 0.0 | 0.0 |
| error_diagnosis | 2 | 0.619 | 0.8466 | 0.5 | 0.25 |
| performance | 2 | 0.6793 | 0.414 | 0.5 | 0.25 |
| resource | 2 | 0.7324 | 0.7539 | 0.3333 | 0.0 |
| security | 2 | 0.7083 | 0.7955 | 0.5 | 0.0 |
| service_health | 2 | 0.8179 | 0.7373 | 0.5 | 0.5 |
| time_analysis | 1 | 0.8 | 0.6554 | 0.0 | 0.0 |
| user_activity | 2 | 0.5962 | 0.4002 | 0.3778 | 0.0 |

## 3. 性能指标

- 平均检索耗时: 7.087s
- 平均 LLM 耗时: 3.606s
- 平均 Token 数: 765
