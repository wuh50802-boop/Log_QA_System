# 消融实验 OPT: 优化后（偏 BM25 hybrid, v=1.0, b=2.0）

- 生成时间: 2026-07-26 19:52:45
- 评估条目: 60
- 总耗时: 225.9s (平均 3.76s/条)
- 配置: retriever=hybrid v_w=1.0 b_w=2.0 rerank=False

## 1. 总体指标

| 指标 | 平均分 | 最低 | 最高 | 成功数 | 失败数 |
|---|---|---|---|---|---|
| faithfulness | 0.6663 | 0.25 | 0.875 | 60 | 0 |
| answer_relevancy | 0.6534 | 0.0 | 0.9246 | 60 | 0 |
| context_precision | 0.3043 | 0.0 | 1.0 | 60 | 0 |
| context_recall | 0.1306 | 0.0 | 1.0 | 60 | 0 |

## 2. 按场景分组

| 场景 | 数量 | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|---|---|
| aggregation | 5 | 0.7332 | 0.7027 | 0.0 | 0.0 |
| error_diagnosis | 12 | 0.64 | 0.7709 | 0.5833 | 0.2639 |
| performance | 10 | 0.6172 | 0.6384 | 0.2806 | 0.1 |
| resource | 6 | 0.567 | 0.7622 | 0.2972 | 0.0 |
| security | 8 | 0.6399 | 0.6261 | 0.25 | 0.0625 |
| service_health | 8 | 0.7996 | 0.6576 | 0.4583 | 0.3125 |
| time_analysis | 3 | 0.7345 | 0.4519 | 0.0 | 0.0 |
| user_activity | 8 | 0.6674 | 0.4825 | 0.125 | 0.0833 |

## 3. 性能指标

- 平均检索耗时: 0.508s
- 平均 LLM 耗时: 3.918s
- 平均 Token 数: 762
