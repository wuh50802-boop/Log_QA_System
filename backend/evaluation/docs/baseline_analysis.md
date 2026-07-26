# 任务 7.4 基线问题分析报告

- 报告日期: 2026-07-26
- 数据来源: baseline_report.json / baseline_raw.jsonl（60 条 QA 全量评估）
- 评估对象: 当前后端 QA 系统（hybrid 检索 + DeepSeek-v4-flash + evidence_chain 模板）

## 一、基线指标回顾

| 指标 | 平均分 | 解读 |
|---|---|---|
| Faithfulness | 0.5549 | 回答对检索日志的忠实度，中等偏低 |
| Answer Relevancy | 0.6911 | 回答切题度，尚可 |
| Context Precision | 0.2441 | 检索精度，明显偏低 |
| Context Recall | 0.1944 | 检索召回，明显偏低 |
| Retrieval Hit Rate | 0.2088 | ID 级检索命中率，偏低 |

## 二、低分指标分布

### 检索命中率（ID 级）

| 命中率区间 | 数量 | 占比 |
|---|---|---|
| 0.0 | 45 | 75.0% |
| 0.01–0.49 | 3 | 5.0% |
| 0.5–0.99 | 0 | 0% |
| 1.0 | 12 | 20.0% |

**75% 的样本 ID 级命中率为 0**，但其中 14 条 RAGAS context_recall ≥ 0.5 —— 系统检索到了语义相同的同类日志，只是 log_id 不同。

### Context Recall（语义级）

| 区间 | 数量 |
|---|---|
| 0.0 | 40 |
| 0.01–0.49 | 5 |
| 0.5–0.99 | 10 |
| 1.0 | 5 |

**40 条 context_recall=0** 中，12 条是聚合类问题（reference_log_ids 为空），其余 28 条是检索结果与参考答案语义距离较大。

### Context Precision

| 区间 | 数量 |
|---|---|
| 0.0 | 39 |
| 0.01–0.49 | 11 |
| 0.5–0.99 | 10 |
| 1.0 | 0 |

**39 条 precision=0** 表明 RAGAS 判定"检索到的日志多数对回答参考答案无直接帮助"，与召回问题强相关。

## 三、根因定位

### 根因 1：测试集"应引用日志"标注偏严，导致 ID 级命中率失真

**证据**：

- `qa_001` 问题"auth-service 出现过 ERROR 级别的 NullPointerException"，应引用 `[74, 315, 359, 407, 746]`，系统实际检索 `[1646, 6792, 6205, 1444, 875]` —— 内容全部是 `auth-service / ERROR / NullPointerException in UserService`，但 ID 完全不重合。
- 数据库中 `NullPointerException in UserService` 日志共 **748 条**，标注时按 `ORDER BY id LIMIT 5` 只取了前 5 条，系统按相似度检索返回的是其他 5 条，本质是同一种日志。
- 同类日志数量统计：`Rate limit exceeded` 783 条、`Connection timeout to database` 786 条、`User login successful` 642 条 等。
- RAGAS 通过语义判断，这些案例 context_recall 仍能拿到 0.5–1.0，但 hit_rate=0。

**结论**：ID 级 hit_rate=0.21 是测试集设计问题，不代表系统检索能力差。**真正反映检索质量的是 RAGAS 的 context_recall=0.19**。

### 根因 2：LLM 回答的引用格式与 System Prompt 不一致

**证据**：

- System Prompt 明确要求 `引用格式：[ID:xxx]`，Prompt 模板也以 `[log_id]` 形式呈现上下文。
- 但实际 60/60 条回答都使用 `[数字]` 格式，而非 `[ID:数字]`：
  - `qa_001` 回答用 log_id：`[1646] auth-service/ERROR ...`
  - `qa_002` 回答用 1-5 序号：`[3] payment-service/ERROR ...`
- 同一问题在不同条目中混用 log_id 与序号，**LLM 输出格式不稳定**。
- `qa_004` 因输出格式异常导致 RAGAS faithfulness NLI 解析失败（返回 None）。
- `qa_002`、`qa_023`、`qa_028` 的 faithfulness < 0.3，与引用编号错乱直接相关。

**结论**：引用格式不稳定影响 faithfulness 评分（0.55），并削弱了溯源可用性。

### 根因 3：聚合/统计类问题不适合 RAG 检索路径

**证据**：

- 12 条聚合类问题（`aggregation` 5 条 + `time_analysis` 3 条 + `error_diagnosis/hard` 4 条）的 `reference_log_ids` 为空。
- 这些问题如 "统计 INFO/WARNING/ERROR/DEBUG 各多少条"、"按服务×级别交叉统计" 本质需要 **SQL 聚合**，而非向量检索。
- 系统仍走 RAG：检索到 5 条无关样本日志 → LLM 基于不完整证据生成数字 → context_precision=0, context_recall=0, faithfulness 偏低。
- 按场景分组数据印证：`aggregation` 的 context_precision=0.0、context_recall=0.0；`time_analysis` 同样为 0。

**结论**：聚合类问题（20% 占比）走 RAG 路径是结构性错配，单独拉低了 precision/recall 均值。

## 四、待优化点（优先级排序）

### 优化点 1：重构测试集"应引用日志"标注（高优先级）

**问题**：当前按 `ORDER BY id LIMIT 5` 取前 5 条作为应引用日志，但数据库中同类日志有 200–780 条，ID 级 hit_rate 无法反映真实检索质量。

**优化方案**：
- 将 `reference_log_ids` 改为 **"日志模板"标识**（如 `NullPointerException in UserService` 这一消息类型），评估时判断"检索到的日志是否属于该模板"。
- 或扩大标注范围：对所有同类日志都算命中，hit_rate = hit_count / min(5, retrieved_count)。
- 同时保留 ID 级指标作为"严格召回"参考。

**预期收益**：hit_rate 从 0.21 提升至 0.7+，context_recall 评估更准确。

### 优化点 2：强化 LLM 引用格式约束（中优先级）

**问题**：System Prompt 要求 `[ID:xxx]` 但 LLM 实际产出 `[数字]`，且 log_id 与序号混用。

**优化方案**：
- 修改 Prompt 模板，明确示范："回答中引用第 N 条日志时，使用 `[ID:log_id]` 格式，例如 `[ID:1646]`"。
- 在 `qa_pipeline.py` 后处理环节加入正则校验/修复：将 `[数字]` 重新映射为对应的 `[ID:log_id]`。
- 提高 LLM temperature=0（当前 0.3）以增强格式稳定性。

**预期收益**：faithfulness 从 0.55 提升至 0.70+，同时提升溯源可用性。

### 优化点 3：聚合类问题路由到 NL2SQL 路径（低优先级）

**问题**：12 条聚合类问题走 RAG 路径必然 precision/recall=0。

**优化方案**：
- 在 QA 入口增加意图识别：问题包含"统计/数量/分布/排名/Top N"等关键词时，路由到 NL2SQL 模块。
- NL2SQL 将自然语言转换为 SQL 查询 `logs` 表，直接返回聚合结果。
- 测试集中将聚合类问题单独分组评估，不参与 RAGAS 4 指标统计。

**预期收益**：聚合类问题回答正确率显著提升；RAGAS 指标更纯粹反映 RAG 路径质量。

## 五、优化优先级与下一步

| 优化点 | 优先级 | 实施难度 | 预期收益 |
|---|---|---|---|
| 1. 重构测试集标注 | 高 | 低 | 命中率指标恢复真实 |
| 2. 强化引用格式 | 中 | 中 | faithfulness 提升 |
| 3. 聚合类路由 NL2SQL | 低 | 高 | 聚合类问题正确率提升 |

建议下一步（任务 7.5 优化迭代）先做优化点 1+2，复跑基线评估对比指标变化；优化点 3 作为长期改进项。
