

- 文档日期: 2026-07-26（v2 修订：移除废弃指标，补充设计性说明）
- 评估对象: 日志 QA 系统检索模块
- 评估数据: testset.json（60 条 QA）

## 一、实验目标

通过控制变量法，量化以下三个问题：

1. **单路检索对比**：纯向量 vs 纯 BM25，哪种更适合日志检索场景？
2. **混合检索收益**：RRF 融合相比单路检索是否有提升？最优权重比是多少？
3. **重排序收益**：在混合检索基础上加入 Cross-Encoder 重排序，是否进一步提升？

## 二、实验变量与控制条件

### 自变量（5 个实验组 + 1 个基线组）

| 组别 | 名称 | 检索器 | 配置 | 说明 |
|---|---|---|---|---|
| A0 | 基线（当前生产） | hybrid | vector_w=1.0, bm25_w=1.0, k=60, top_k=5 | 任务 7.3 跑出的基线 |
| A1 | 纯向量 | vector | top_k=5 | 关闭 BM25 |
| A2 | 纯 BM25 | bm25 | top_k=5 | 关闭向量 |
| A3 | 混合-偏向向量 | hybrid | vector_w=2.0, bm25_w=1.0, k=60, top_k=5 | 偏语义 |
| A4 | 混合-偏向 BM25 | hybrid | vector_w=1.0, bm25_w=2.0, k=60, top_k=5 | 偏关键词 |
| A5 | 混合 + 重排序 | hybrid + rerank | vector_w=1.0, bm25_w=1.0, k=60, top_k=20→rerank→5 | 取 Top-20 重排到 Top-5 |

### 控制变量（所有组保持一致）

| 控制项 | 值 | 理由 |
|---|---|---|
| LLM 模型 | DeepSeek-v4-flash | 与生产一致 |
| LLM temperature | 0.3 | 与生产一致 |
| Prompt 模板 | evidence_chain | 与生产一致（含【分析推断】【结论建议】输出） |
| top_k（最终返回） | 5 | 与生产一致 |
| 测试集 | testset.json (60 条) | 固定 |
| 评估指标 | RAGAS 4 指标 + 性能指标 | 固定 |
| 评估 LLM | DeepSeek-v4-flash (temp=0) | 固定 |
| 评估 Embeddings | BGE bge-base-zh-v1.5 | 固定 |
| history | [] | 单轮问答，不累积历史 |

### 因变量（评估指标）

| 指标 | 含义 | 期望方向 | 解读方式 |
|---|---|---|---|
| Faithfulness | 回答对检索日志的忠实度 | ↑ | **设计性偏低**（推论/建议无日志支撑），看组间相对变化 |
| Answer Relevancy | 回答切题度 | ↑ | 反映检索+回答质量 |
| Context Precision | 检索结果中相关日志比例 | ↑ | **主指标**：反映检索精度 |
| Context Recall | 检索结果覆盖参考答案的比例 | ↑ | **设计性偏低**（reference 含推论），看组间相对变化 |
| 平均检索耗时 | 检索阶段耗时（秒） | ↓ | 性能开销 |
| 平均总耗时 | 端到端耗时（秒） | ↓ | 性能开销 |

### 关于指标解读的重要说明

本项目 Prompt 模板按设计要求 LLM 输出 `【分析推断】` 和 `【结论建议】` 部分，这些内容来自 LLM 领域知识而非检索日志。因此：

- **faithfulness / context_recall 的绝对值会低于 1.0**，这是设计性必然，不是系统缺陷
- **组间对比看相对变化**：所有组使用相同 Prompt/LLM，推论部分相对稳定，指标变化主要由检索质量决定
- **context_precision / answer_relevancy 是主指标**：直接反映检索质量与回答质量
- 已移除 ID 级/模板级 Hit Rate（任务 7.4 发现标注失真，与 RAGAS context_recall 重复）

## 三、实验组详细配置

### A0: 基线（hybrid 等权重）

```python
pipeline = create_robust_pipeline(
    top_k=5,
    retriever_type="hybrid",
    template_type="evidence_chain",
)
# hybrid 内部默认: vector_weight=1.0, bm25_weight=1.0, k=60
```

### A1: 纯向量检索

```python
pipeline = create_robust_pipeline(
    top_k=5,
    retriever_type="vector",   # 仅用 BGE 向量检索
    template_type="evidence_chain",
)
```

**假设**：纯向量对语义相似但用词不同的查询（如 "认证失败" vs "Invalid token"）效果好；但对精确关键词（如 "OutOfMemoryError"）可能弱于 BM25。

### A2: 纯 BM25 检索

```python
pipeline = create_robust_pipeline(
    top_k=5,
    retriever_type="bm25",     # 仅用 BM25 关键词检索
    template_type="evidence_chain",
)
```

**假设**：日志查询高度依赖关键词匹配（错误码、服务名、级别），BM25 可能优于向量。但对同义改写查询较弱。

### A3: 混合-偏向向量

```python
pipeline = create_robust_pipeline(
    top_k=5,
    retriever_type="hybrid",
    template_type="evidence_chain",
    vector_weight=2.0,   # 向量权重 ×2
    bm25_weight=1.0,
)
```

**假设**：日志查询既有语义改写又有精确关键词，偏向量适合复杂自然语言问题。

### A4: 混合-偏向 BM25

```python
pipeline = create_robust_pipeline(
    top_k=5,
    retriever_type="hybrid",
    template_type="evidence_chain",
    vector_weight=1.0,
    bm25_weight=2.0,     # BM25 权重 ×2
)
```

**假设**：偏 BM25 适合直接含错误关键词的问题（"NullPointerException"、"SSL handshake failed"）。

### A5: 混合 + Cross-Encoder 重排序

```python
pipeline = create_robust_pipeline(
    top_k=5,
    retriever_type="hybrid",
    template_type="evidence_chain",
    rerank=True,                  # 启用重排序
    rerank_model="BAAI/bge-reranker-base",  # 中文 Cross-Encoder
    rerank_candidate_k=20,        # 先取 Top-20
)
# 流程: hybrid 取 Top-20 → Cross-Encoder 重排 → 取 Top-5
```

**假设**：Cross-Encoder（query-doc 联合编码）比双塔向量更精准，能进一步提升 Top-5 质量；但耗时增加。

## 四、实验执行方案

### 4.1 执行顺序

1. **A0 基线** — 重跑（当前 raw 文件被覆盖）
2. **A1 纯向量** — 单路，最简单
3. **A2 纯 BM25** — 单路，与 A1 对比
4. **A3 偏向量混合** — 与 A0 对比权重影响
5. **A4 偏 BM25 混合** — 与 A0 对比权重影响
6. **A5 混合 + 重排序** — 需先实现 Reranker

### 4.2 每组执行步骤

1. 通过 `run_ablation.py --group X --stratified` 参数化执行
2. 跑 **15 条分层抽样** QA 评估（覆盖全部 8 场景 + 3 难度）
3. 输出 `ablation_<group>.json` + `ablation_<group>.md`
4. 落盘原始结果 `ablation_<group>_raw.jsonl`（断点续跑）
5. 汇总到对比表

### 4.3 评估脚本

新增 `run_ablation.py`（复用 `run_baseline.py` 框架）：

```bash
# 各组执行命令（分层抽样 15 条，推荐）
venv/Scripts/python.exe -m evaluation.run_ablation --group A0 --stratified --reset
venv/Scripts/python.exe -m evaluation.run_ablation --group A1 --stratified --reset
venv/Scripts/python.exe -m evaluation.run_ablation --group A2 --stratified --reset
venv/Scripts/python.exe -m evaluation.run_ablation --group A3 --stratified --reset
venv/Scripts/python.exe -m evaluation.run_ablation --group A4 --stratified --reset
venv/Scripts/python.exe -m evaluation.run_ablation --group A5 --stratified --reset

# 或一次性跑全部 6 组
venv/Scripts/python.exe -m evaluation.run_ablation --group all --stratified --reset
```

每组生成独立的报告文件，避免覆盖基线。

### 4.4 样本量选择说明

**采用 15 条分层抽样而非全量 60 条**，理由：

1. **时间成本**：60 条 × 6 组 × 70s/条 ≈ 7 小时；15 条 × 6 组 ≈ 1.75 小时
2. **统计可靠性**：RAGAS LLM-as-Judge 噪声约 ±0.05，15 条足够检测 >0.1 的显著差异
3. **场景覆盖**：分层抽样保证全部 8 个场景和 3 档难度都有代表，避免 `--limit 15` 取前 15 条导致全是 error_diagnosis 的偏斜
4. **抽样分布**：6 easy / 6 medium / 3 hard，每场景至少 1 条

预设的 15 条样本 ID（在 `run_ablation.py` 的 `STRATIFIED_15` 中定义）：

| ID | 场景 | 难度 |
|---|---|---|
| qa_001 | error_diagnosis | easy |
| qa_007 | error_diagnosis | medium |
| qa_013 | service_health | easy |
| qa_017 | service_health | medium |
| qa_021 | user_activity | easy |
| qa_025 | user_activity | medium |
| qa_029 | performance | easy |
| qa_033 | performance | medium |
| qa_039 | security | easy |
| qa_042 | security | medium |
| qa_047 | resource | easy |
| qa_049 | resource | medium |
| qa_053 | aggregation | medium |
| qa_055 | aggregation | hard |
| qa_060 | time_analysis | hard |

## 五、结果对比表（模板）

实验跑完后填充此表：

| 组别 | 配置 | Faith. | AnsRel. | CtxPrec | CtxRecall | 检索耗时 | 总耗时 |
|---|---|---|---|---|---|---|---|
| A0 基线 | hybrid 等权 | TBD | TBD | TBD | TBD | TBD | TBD |
| A1 纯向量 | vector | TBD | TBD | TBD | TBD | TBD | TBD |
| A2 纯 BM25 | bm25 | TBD | TBD | TBD | TBD | TBD | TBD |
| A3 偏向量 | v=2.0,b=1.0 | TBD | TBD | TBD | TBD | TBD | TBD |
| A4 偏 BM25 | v=1.0,b=2.0 | TBD | TBD | TBD | TBD | TBD | TBD |
| A5 混合+重排 | hybrid+rerank | TBD | TBD | TBD | TBD | TBD | TBD |

### 期望观察到的对比维度

1. **A1 vs A2**：判断日志检索场景下，向量与 BM25 谁更占优。
2. **A0 vs (A1, A2)**：RRF 融合是否优于任一单路。
3. **A3 vs A4 vs A0**：权重偏向哪个方向效果更好。
4. **A5 vs A0**：重排序是否带来显著提升，与额外耗时是否划算。

## 六、注意事项与风险

### 6.1 评估耗时（已优化）

**优化前**：每组 15 条 × 70s/条 ≈ 17 分钟，6 组共 ~1.75 小时（串行）。

**优化后**（四层并发优化，详见 6.5）：
- 每组 15 条预计 ~6-8 分钟，6 组共 ~40-50 分钟
- 提速比 ~2.5-3x

**应对**：
- 受控并发（QA_CONCURRENCY=3），避免 DeepSeek API 限流。
- 利用 `--limit N` 先跑小子集验证脚本正确性。
- 利用断点续跑（`ablation_<group>_raw.jsonl` 同样机制）。

### 6.2 RAGAS 评估波动

RAGAS 用 LLM-as-Judge，同一输入不同时间跑可能分数有 ±0.05 波动。

**应对**：
- 评估 LLM temperature=0（已配置）。
- 关注组间**显著差异**（>0.1），小幅差异不轻易下结论。

### 6.3 重排序模型加载（已优化）

`bge-reranker-base` 约 1.1GB，首次下载耗时。

**优化**：`qa_pipeline.py` 已改用 `get_reranker()` 全局单例，A5 组内只加载一次，跨组复用。

**应对**：
- 提前用 modelscope 下载到 `models_cache/`。
- 全局单例复用，避免重复加载。

### 6.4 faithfulness/context_recall 设计性偏低

本项目 Prompt 设计要求 LLM 输出推论与建议，这些内容来自 LLM 领域知识而非检索日志，必然导致 faithfulness/context_recall < 1.0。

**应对**：
- 不追求绝对值接近 1.0
- 看组间相对变化（检索质量差异）
- context_precision / answer_relevancy 作为主指标

### 6.5 性能优化方案（四层并发优化）

针对原始串行实现的性能瓶颈，采用四层叠加优化：

| 层级 | 原始问题 | 优化方案 | 配置 |
|---|---|---|---|
| 1. QA 调用 | 串行逐条跑，每条 70s | `asyncio.Semaphore` 受控并发 + `asyncio.to_thread` 包装同步 `pipeline.ask` | `QA_CONCURRENCY=3` |
| 2. RAGAS 打分 | 4 个指标串行 `for m in metrics` | `asyncio.gather` 并发跑 4 个指标 | `RAGAS_METRIC_CONCURRENCY=4` |
| 3. Reranker 加载 | 每次建 pipeline 重新加载 1.1GB CrossEncoder | `qa_pipeline.py` 改用 `get_reranker()` 全局单例 | 单例复用 |
| 4. 落盘 IO | 每条结果立刻 `f.write()` | 内存攒批，每 5 条批量写盘 | `FLUSH_BATCH_SIZE=5` |

**并发安全性**：
- `pipeline.ask(question, history=[])` 显式传 `history=[]`，避免修改内部 `conversation_history` 状态
- `DeepSeekClient` 和检索器均为无状态读取，线程安全
- `asyncio.as_completed` 流式处理先完成的结果，便于实时看进度

**限流应对**：
- `QA_CONCURRENCY=3` 保守取值，避免 DeepSeek API 429
- 如遇限流，降至 2 即可

## 七、预期结论与决策路径

根据实验结果，按以下决策树选择最终生产配置：

```
A1 vs A2 谁明显占优？
├─ 一方明显占优（差异 > 0.1）
│   └─ A0 是否优于该单路？
│       ├─ 是 → 采用 A0（hybrid 等权）
│       └─ 否 → 采用该单路
└─ 两者相近
    └─ A3 vs A4 谁更优？
        ├─ 一方占优 → 采用该权重配置
        └─ 相近 → 用 A0 等权
            └─ A5 是否显著优于 A0？
                ├─ 是，且耗时可接受 → 采用 A5
                └─ 否或耗时不可接受 → 采用 A0
```

## 八、交付清单

| 交付物 | 路径 | 状态 |
|---|---|---|
| 实验方案文档 | `evaluation/ablation_design.md`（本文件） | 完成 |
| 消融实验脚本 | `evaluation/run_ablation.py` | 待实现 |
| Reranker 模块 | `services/reranker.py` | 已实现（任务 7.6） |
| 各组实验报告 | `evaluation/ablation_<group>.md` | 待跑 |
| 对比汇总表 | `evaluation/ablation_summary.md` | 待生成 |
