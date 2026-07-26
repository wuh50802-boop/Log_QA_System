# 消融实验 A3: 混合-偏向量

- 生成时间: 2026-07-26 18:51:53
- 评估条目: 15
- 总耗时: 99.8s (平均 6.65s/条)
- 配置: retriever=hybrid v_w=2.0 b_w=1.0 rerank=False

## 1. 总体指标

| 指标 | 平均分 | 最低 | 最高 | 成功数 | 失败数 |
|---|---|---|---|---|---|
| faithfulness | 0.6821 | 0.4333 | 0.8333 | 15 | 0 |
| answer_relevancy | 0.6486 | 0.0 | 0.8647 | 15 | 0 |
| context_precision | 0.3689 | 0.0 | 1.0 | 15 | 0 |
| context_recall | 0.2 | 0.0 | 1.0 | 15 | 0 |

## 2. 按场景分组

| 场景 | 数量 | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|---|---|
| aggregation | 2 | 0.6402 | 0.6951 | 0.0 | 0.0 |
| error_diagnosis | 2 | 0.683 | 0.8404 | 0.5 | 0.25 |
| performance | 2 | 0.7118 | 0.4186 | 0.4333 | 0.25 |
| resource | 2 | 0.4859 | 0.6976 | 0.3333 | 0.0 |
| security | 2 | 0.6618 | 0.7538 | 0.5 | 0.25 |
| service_health | 2 | 0.775 | 0.7692 | 0.5 | 0.75 |
| time_analysis | 1 | 0.8333 | 0.5493 | 0.0 | 0.0 |
| user_activity | 2 | 0.7418 | 0.4154 | 0.5 | 0.0 |

## 3. 性能指标

- 平均检索耗时: 0.305s
- 平均 LLM 耗时: 3.685s
- 平均 Token 数: 755
