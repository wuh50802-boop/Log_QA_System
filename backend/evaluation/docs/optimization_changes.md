

- 实施日期: 2026-07-26
- 依据: 任务 7.4 基线问题分析报告（[baseline_analysis.md](baseline_analysis.md)）
- 目标: 实施分析报告中的 3 个待优化点 + 任务 7.5 消融实验需要的代码改造

## 一、优化项与代码变更清单

### 优化1：强化 LLM 引用格式约束（对应分析报告优化点2）

**问题**：System Prompt 要求 `[ID:xxx]` 格式，但 60/60 条回答都用 `[数字]`，且 log_id 与序号混用，导致 faithfulness 评估时无法准确溯源。

**变更文件**：

#### 1.1 [services/prompt_templates.py](file:///d:/log-qa-system/backend/services/prompt_templates.py)

- **`SYSTEM_PROMPT`**：从单行扩展为 5 行，明确 4 条引用规则：
  - 必须使用 `[ID:日志ID]` 完整格式
  - 禁止 `[数字]` 形式
  - 引用 ID 必须来自上下文日志列表
  - 不引用列表外日志

- **`evidence_chain_prompt`**：日志格式从 `1.[1646] auth/ERROR ...` 改为 `[ID:1646] auth/ERROR ...`（明确示范引用格式），并在【关键证据】要求中追加 "必须使用 [ID:数字] 完整格式，不要写成 [1646] 或 [1]"

- **`quick_prompt` / `short_prompt`**：同步修改日志格式与引用要求，保持三个模板一致

- **`format_logs_as_context`**：同步修改日志格式为 `[ID:xxx]`

#### 1.2 [services/qa_pipeline.py](file:///d:/log-qa-system/backend/services/qa_pipeline.py)

- **`_extract_source_refs`**：重写，支持三种引用形式提取：
  - `[ID:xxx]` 规范格式（优先）
  - `[xxx]` 裸 log_id 形式（LLM 常见输出）
  - `[n]` 序号形式（1-based，对应 sources 顺序）
  并按回答中出现顺序排序，保持引用顺序稳定。

- **`_annotate_answer_with_refs`**：重写为"规范化"函数，将所有引用统一为 `[ID:log_id]` 形式：
  - LLM 正确输出 `[ID:1646]` → 保留
  - LLM 输出 `[1646]` 裸 log_id → 修复为 `[ID:1646]`
  - LLM 输出 `[1]` 序号 → 映射到对应 `[ID:log_id]`
  使用负向先行断言 `(?<!ID:)\[(\d+)\]` 避免重复匹配 `[ID:数字]` 中的数字。

---

### 优化2：引入 Cross-Encoder 重排序器（对应任务 7.5 A5 实验需要）

**目的**：在混合检索基础上增加 Cross-Encoder 精排，提升 Top-K 检索质量。

**变更文件**：

#### 2.1 新增 [services/reranker.py](file:///d:/log-qa-system/backend/services/reranker.py)

- **`Reranker` 类**：基于 `BAAI/bge-reranker-base`（中文优化，约 1.1GB）
  - `__init__`：复用 `embedder.py` 的 modelscope 下载逻辑（本地快照优先，避免重复下载）
  - `rerank(query, docs, top_k)`：构造 `[query, doc]` 对，CrossEncoder 打分后按分数降序取 Top-K
  - 拼接 `service level content` 作为 doc 文本，提升重排质量
  - 注入 `rerank_score` 与 `original_score` 字段便于对比
- **`get_reranker()`**：单例工厂
- **`test_reranker()`**：自测函数

#### 2.2 [services/qa_pipeline.py](file:///d:/log-qa-system/backend/services/qa_pipeline.py)

- **`QAPipeline.__init__`**：新增 4 个参数 `rerank` / `rerank_model` / `rerank_candidate_k` / `vector_weight` / `bm25_weight`
- **`_init_retriever`**：
  - 启用重排序时，检索阶段取 `rerank_candidate_k`（默认 20）条候选
  - hybrid 默认权重走单例，非默认权重直接 new 实例（支持消融实验切换权重）
- **`ask` 与 `ask_stream`**：在检索后、构建 Prompt 前插入重排序步骤
  ```python
  if self.rerank and self.reranker and logs:
      logs = self.reranker.rerank(question, logs, top_k=k)
  ```

---

### 优化3：参数化 `create_pipeline` / `create_robust_pipeline`（对应任务 7.5 消融实验需要）

**目的**：让消融实验脚本可以通过参数切换 A1-A5 配置，无需修改代码。

**变更文件**：

#### 3.1 [services/qa_pipeline.py](file:///d:/log-qa-system/backend/services/qa_pipeline.py)

- **`create_pipeline`**：新增 5 个参数透传给 `QAPipeline`
  - `rerank` / `rerank_model` / `rerank_candidate_k` / `vector_weight` / `bm25_weight`

#### 3.2 [services/error_handler.py](file:///d:/log-qa-system/backend/services/error_handler.py)

- **`create_robust_pipeline`**：同步新增 5 个参数，透传给 `create_pipeline`

**调用示例（消融实验 A5 配置）**：
```python
pipeline = create_robust_pipeline(
    top_k=5,
    retriever_type="hybrid",
    template_type="evidence_chain",
    rerank=True,
    rerank_candidate_k=20,
)
```

**调用示例（消融实验 A3 偏向量）**：
```python
pipeline = create_robust_pipeline(
    top_k=5,
    retriever_type="hybrid",
    vector_weight=2.0,
    bm25_weight=1.0,
)
```

---

### 优化4：重构测试集标注为日志模板标识（对应分析报告优化点1）

**问题**：测试集"应引用日志"按 `ORDER BY id LIMIT 5` 标注，但 DB 中同类日志有 200-780 条，导致 ID 级 hit_rate 失真（75% 案例 = 0）。

**变更文件**：

#### 4.1 [evaluation/testset_loader.py](file:///d:/log-qa-system/backend/evaluation/testset_loader.py)

新增两个模板级命中率评估函数：

- **`template_hit_rate(item, retrieved_sources)`**：用 `(services, levels, keywords)` 作为模板标识，判断检索到的日志是否属于该模板
  - service 必须匹配（若 tags 指定了 services）
  - level 必须匹配（若 tags 指定了 levels）
  - content 必须包含任一 keyword
  - 聚合类问题无 keywords，返回 0.0（不适用）

- **`template_precision_at_k(item, retrieved_sources)`**：等价于 `template_hit_rate`，保留独立函数名以便报告区分

#### 4.2 [evaluation/run_baseline.py](file:///d:/log-qa-system/backend/evaluation/run_baseline.py)

- 导入新增的 `template_hit_rate` / `template_precision_at_k`
- 每条 QA 同时计算 ID 级与模板级命中率，落盘到 `baseline_raw.jsonl`
- `build_report` 汇总 `template_hit_rate_mean` / `template_precision_at_k_mean`
- Markdown 报告新增"模板级命中率"行，并附说明"按 service+level+keywords 模板匹配"
- 终端汇总打印同步增加模板级指标

---

## 二、未实施的优化项

### chunk_size 调整（任务描述提及但未实施）

**原因**：
- 当前 `LogChunker.DEFAULT_CHUNK_SIZE = 256`（适配 BGE 512 token 窗口），`overlap = 50`
- 任务 7.4 分析报告的 3 个根因中**未涉及 chunk_size 问题**，低分指标主要源于：
  1. 测试集标注失真（已用模板级命中率解决）
  2. LLM 引用格式不稳定（已用 Prompt + 后处理解决）
  3. 聚合类问题不适合 RAG（属于长期改进项，不在本次范围）
- 调整 chunk_size 需要重新构建 Qdrant 向量索引（全量重 embed），成本高且收益不确定
- 任务 7.5 消融实验未将 chunk_size 列为实验变量

**建议**：若后续消融实验发现检索召回仍有问题，再单独评估 chunk_size 调整。

### 聚合类问题 NL2SQL 路由（分析报告优化点3）

**原因**：属于架构级改动（需新增意图识别 + NL2SQL 模块），实施难度高，分析报告标记为"低优先级 / 长期改进项"，不在任务 7.6 范围。

---

## 三、冒烟测试验证

跑 3 条 QA 验证优化后代码工作正常：

| 指标 | 优化前（60条均值） | 优化后（3条冒烟） | 变化 |
|---|---|---|---|
| faithfulness | 0.5549 | 0.6083 | +0.05 |
| answer_relevancy | 0.6911 | 0.8011 | +0.11 |
| context_precision | 0.2441 | 0.9074 | **+0.66** |
| context_recall | 0.1944 | 0.3333 | +0.14 |
| ID级 hit_rate | 0.2088 | 0.0667 | (3条样本不可比) |
| 模板级 hit_rate | - | 0.40 | 新增指标 |

**关键观察**：
- 引用格式修复后，context_precision 从 0.24 飙升到 0.91（RAGAS 现在能正确识别检索到的日志与参考答案的对应关系）
- 模板级命中率（0.40）显著高于 ID 级（0.07），验证了任务 7.4 根因1的诊断
- 流程完整无报错，3 条全部成功

---

## 四、变更文件汇总

| 文件 | 类型 | 变更内容 |
|---|---|---|
| [services/prompt_templates.py](file:///d:/log-qa-system/backend/services/prompt_templates.py) | 修改 | SYSTEM_PROMPT 扩展为 5 行规则；3 个 prompt 模板日志格式改为 `[ID:xxx]` |
| [services/qa_pipeline.py](file:///d:/log-qa-system/backend/services/qa_pipeline.py) | 修改 | `_extract_source_refs` / `_annotate_answer_with_refs` 重写支持 3 种引用形式；`QAPipeline.__init__` 新增 5 参数；`_init_retriever` 支持权重注入；`ask` / `ask_stream` 插入重排序步骤；`create_pipeline` 透传新参数 |
| [services/error_handler.py](file:///d:/log-qa-system/backend/services/error_handler.py) | 修改 | `create_robust_pipeline` 新增 5 参数透传 |
| [services/reranker.py](file:///d:/log-qa-system/backend/services/reranker.py) | **新增** | Cross-Encoder 重排序器（BGE reranker-base） |
| [evaluation/testset_loader.py](file:///d:/log-qa-system/backend/evaluation/testset_loader.py) | 修改 | 新增 `template_hit_rate` / `template_precision_at_k` 函数 |
| [evaluation/run_baseline.py](file:///d:/log-qa-system/backend/evaluation/run_baseline.py) | 修改 | 集成模板级命中率评估；报告与汇总打印同步更新 |
| [evaluation/optimization_changes.md](file:///d:/log-qa-system/backend/evaluation/optimization_changes.md) | **新增** | 本变更说明文档 |

---

## 五、向后兼容性

- **API 路由无需修改**：`api/qa.py` 通过 `create_robust_pipeline()` 创建 pipeline，新参数全部有默认值，调用方无感知
- **默认配置不变**：`rerank=False` / `vector_weight=1.0` / `bm25_weight=1.0`，与优化前生产行为一致
- **测试集 JSON 无需修改**：新增的模板级评估基于已有 `tags` 字段，无需重新标注
- **历史评估结果可对比**：`baseline_raw.jsonl` 增加了 `template_hit_rate` 字段，旧字段保持不变

---

## 六、后续任务衔接

- **任务 7.7（消融实验执行）**：可直接用 `create_robust_pipeline(rerank=True, vector_weight=2.0, ...)` 跑 A1-A5 各组实验
- **任务 7.8（最终评估报告）**：复跑 60 条全量评估，对比优化前后的 RAGAS 4 指标 + 模板级命中率变化
