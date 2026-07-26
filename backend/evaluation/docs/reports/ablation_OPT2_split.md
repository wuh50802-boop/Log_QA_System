# 任务 7.7 OPT2 分路径评估报告（RAG / NL2SQL 分开评估）

- 生成时间: 2026-07-26 21:35:09
- 评估对象: OPT2 组（NL2SQL 路由 + 偏 BM25 hybrid）
- 总条数: 60
  - RAG 路径: 44 条（用 RAGAS 4 指标评估）
  - NL2SQL 路径: 16 条（用 SQL 评估指标，不评估 RAGAS）

## 一、评估方法论说明

### 1.1 为什么要分开评估

OPT2 组启用 NL2SQL 路由后，聚合类问题走 SQL 路径直接查 `logs` 表，
本质是**真实数据计算**，不涉及检索或推理。RAGAS 框架的 faithfulness /
context_precision / context_recall 三个指标都依赖 `retrieved_contexts`，
NL2SQL 路径 `retrieved_contexts=[]` 时这三个指标会被自动判 0，
人为拉低 OPT2 组均值，不能反映系统真实质量。

### 1.2 分路径指标设计

| 路径 | 评估指标 | 说明 |
|---|---|---|
| RAG | faithfulness / answer_relevancy / context_precision / context_recall | RAGAS 4 指标，评估检索+生成质量 |
| NL2SQL | SQL 成功率 / 结果非空率 / answer_relevancy | SQL 路径专属指标，answer_relevancy 不依赖 context 可保留 |

## 二、RAG 路径评估（RAGAS 4 指标）

样本数: **44 条**

### 2.1 总体指标

| 指标 | 平均分 |
|---|---|
| faithfulness | 0.6521 |
| answer_relevancy | 0.6702 |
| context_precision | 0.4377 |
| context_recall | 0.1591 |

### 2.2 按场景分组

| 场景 | 数量 | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|---|---|
| error_diagnosis | 9 | 0.6772 | 0.7850 | 0.7778 | 0.2778 |
| performance | 9 | 0.6269 | 0.6626 | 0.3278 | 0.1111 |
| resource | 5 | 0.6298 | 0.6243 | 0.2500 | 0.0000 |
| security | 6 | 0.5844 | 0.6574 | 0.4778 | 0.0833 |
| service_health | 7 | 0.7517 | 0.6503 | 0.6506 | 0.3333 |
| time_analysis | 2 | 0.5810 | 0.3746 | 0.0000 | 0.0000 |
| user_activity | 6 | 0.6459 | 0.6825 | 0.1065 | 0.1111 |

### 2.3 按难度分组

| 难度 | 数量 | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|---|---|
| easy | 24 | 0.6756 | 0.7646 | 0.6391 | 0.2778 |
| hard | 5 | 0.5914 | 0.4953 | 0.0733 | 0.0000 |
| medium | 15 | 0.6346 | 0.5776 | 0.2370 | 0.0222 |

### 2.4 性能指标

- 平均总耗时: 3.77s
- 平均检索耗时: 0.44s
- 平均 LLM 耗时: 3.33s
- 平均 Token 数: 745

## 三、NL2SQL 路径评估（SQL 评估指标）

样本数: **16 条**

### 3.1 总体指标

| 指标 | 值 |
|---|---|
| SQL 成功率 | 16/16 = **100.00%** |
| SQL 失败数 | 0 |
| 结果非空率 | 16/16 = **100.00%** |
| answer_relevancy（参考） | 0.7081 |

> 注：NL2SQL 路径不评估 faithfulness / context_precision / context_recall，
> 因为这些指标依赖 `retrieved_contexts`，而 NL2SQL 是真实数据库计算，无检索过程。

### 3.2 按场景分组

| 场景 | 数量 | SQL 成功率 | 结果非空率 | answer_relevancy |
|---|---|---|---|---|
| aggregation | 5 | 100.00% | 100.00% | 0.7357 |
| error_diagnosis | 3 | 100.00% | 100.00% | 0.7056 |
| performance | 1 | 100.00% | 100.00% | 0.6456 |
| resource | 1 | 100.00% | 100.00% | 0.7223 |
| security | 2 | 100.00% | 100.00% | 0.7129 |
| service_health | 1 | 100.00% | 100.00% | 0.7222 |
| time_analysis | 1 | 100.00% | 100.00% | 0.4950 |
| user_activity | 2 | 100.00% | 100.00% | 0.7621 |

### 3.3 性能指标

- 平均总耗时: 2.20s
- 平均 LLM 耗时（SQL 生成）: 2.19s
- 平均 Token 数: 703

### 3.4 失败案例

无失败案例。

## 四、综合结论

### 4.1 分路径评估的合理性

OPT2 组启用 NL2SQL 路由后，将聚合类问题（16 条）从 RAG 路径剥离到 NL2SQL 路径，
两条路径本质不同，不应使用同一套指标评估：

- **RAG 路径**（44 条）：检索 + LLM 生成，用 RAGAS 4 指标评估检索精度与生成质量
- **NL2SQL 路径**（16 条）：LLM 生成 SQL + 数据库执行，用 SQL 成功率/结果非空率评估

### 4.2 与混合评估（v1 报告）的对比

| 评估方法 | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|---|
| 混合评估（v1，60 条全量） | 0.4782 | 0.6693 | 0.3210 | 0.1167 |
| 分路径评估（RAG 44 条） | **0.6521** | **0.6702** | **0.4377** | **0.1591** |

**结论**：剥离 NL2SQL 路径后，RAG 路径的 RAGAS 指标显著回升：

- faithfulness: 0.4782 → 0.6521（+0.1739）
- context_precision: 0.3210 → 0.4377（+0.1167）
- context_recall: 0.1167 → 0.1591（+0.0424）

这表明 v1 报告中 faithfulness 的下降是 RAGAS 评估方法局限，不是系统质量问题。

### 4.3 NL2SQL 路径的业务价值

- SQL 成功率: 100.00%（16/16）
- 结果非空率: 100.00%（16/16）
- 平均耗时: 2.20s/条（比 RAG 路径 3.77s/条 快约 42%）

NL2SQL 路径返回真实统计数字，避免 LLM 编造数据，业务价值显著。

## 五、交付物

| 交付物 | 路径 |
|---|---|
| 分路径评估脚本 | [evaluation/scripts/eval_split.py](file:///d:/log-qa-system/backend/evaluation/scripts/eval_split.py) |
| 分路径评估报告 | `docs/reports/ablation_OPT2_split.md`（本文件） |
| OPT2 原始数据 | `data/ablation_OPT2_raw.jsonl` |
