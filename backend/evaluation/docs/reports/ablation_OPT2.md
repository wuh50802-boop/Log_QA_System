# 消融实验 OPT2: 优化后 v2（NL2SQL 路由 + 偏 BM25 hybrid）

- 生成时间: 2026-07-26 20:44:24
- 评估条目: 60
- 总耗时: 163.6s (平均 2.73s/条)
- 配置: retriever=hybrid v_w=1.0 b_w=2.0 rerank=False

## 1. 总体指标

| 指标 | 平均分 | 最低 | 最高 | 成功数 | 失败数 |
|---|---|---|---|---|---|
| faithfulness | 0.4782 | 0.0 | 0.875 | 60 | 0 |
| answer_relevancy | 0.6693 | 0.0 | 0.9633 | 60 | 0 |
| context_precision | 0.321 | 0.0 | 1.0 | 60 | 0 |
| context_recall | 0.1167 | 0.0 | 1.0 | 60 | 0 |

## 2. 按场景分组

| 场景 | 数量 | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|---|---|
| aggregation | 5 | 0.0 | 0.7357 | 0.0 | 0.0 |
| error_diagnosis | 12 | 0.5079 | 0.71 | 0.5833 | 0.2083 |
| performance | 10 | 0.5642 | 0.6609 | 0.295 | 0.1 |
| resource | 6 | 0.5248 | 0.6406 | 0.2083 | 0.0 |
| security | 8 | 0.4383 | 0.6713 | 0.3583 | 0.0625 |
| service_health | 8 | 0.6577 | 0.6593 | 0.5693 | 0.2917 |
| time_analysis | 3 | 0.3873 | 0.4147 | 0.0 | 0.0 |
| user_activity | 8 | 0.4844 | 0.7024 | 0.0799 | 0.0833 |

## 3. 性能指标

- 平均检索耗时: 0.324s
- 平均 LLM 耗时: 3.1s
- 平均 Token 数: 741
