# 消融实验 A1: 纯向量

- 生成时间: 2026-07-26 18:57:27
- 评估条目: 15
- 总耗时: 130.3s (平均 8.69s/条)
- 配置: retriever=vector v_w=1.0 b_w=1.0 rerank=False

## 1. 总体指标

| 指标 | 平均分 | 最低 | 最高 | 成功数 | 失败数 |
|---|---|---|---|---|---|
| faithfulness | 0.6597 | 0.4348 | 0.9091 | 15 | 0 |
| answer_relevancy | 0.6608 | 0.0 | 0.8686 | 15 | 0 |
| context_precision | 0.2022 | 0.0 | 1.0 | 15 | 0 |
| context_recall | 0.1222 | 0.0 | 1.0 | 15 | 0 |

## 2. 按场景分组

| 场景 | 数量 | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|---|---|
| aggregation | 2 | 0.7083 | 0.7284 | 0.0 | 0.0 |
| error_diagnosis | 2 | 0.6577 | 0.4183 | 0.35 | 0.25 |
| performance | 2 | 0.6167 | 0.4005 | 0.0 | 0.0 |
| resource | 2 | 0.5507 | 0.7712 | 0.75 | 0.0 |
| security | 2 | 0.6333 | 0.7667 | 0.0 | 0.0 |
| service_health | 2 | 0.6935 | 0.7521 | 0.4167 | 0.5 |
| time_analysis | 1 | 0.9091 | 0.5389 | 0.0 | 0.0 |
| user_activity | 2 | 0.6333 | 0.8494 | 0.0 | 0.1667 |

## 3. 性能指标

- 平均检索耗时: 0.411s
- 平均 LLM 耗时: 4.005s
- 平均 Token 数: 756
