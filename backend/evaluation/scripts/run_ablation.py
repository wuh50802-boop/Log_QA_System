"""
消融实验执行脚本

参数化执行 A0-A5 各组实验，复用 run_baseline.py 的评估框架。

运行：
    cd backend
    # 跑某一组（默认 60 条）
    venv/Scripts/python.exe -m evaluation.run_ablation --group A1
    # 跑小子集验证
    venv/Scripts/python.exe -m evaluation.run_ablation --group A1 --limit 10
    # 清空缓存重跑
    venv/Scripts/python.exe -m evaluation.run_ablation --group A1 --reset
    # 跑完所有组并生成汇总报告
    venv/Scripts/python.exe -m evaluation.run_ablation --group all
"""
import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

# 让 services.* / evaluation.* 可被 import（脚本在 scripts/ 下，需上三级到 backend/）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from evaluation.testset_loader import load_items
from evaluation.ragas_config import get_default_metrics
from evaluation.eval_core import (
    format_retrieved_contexts,
    call_qa_system,
    score_one,
    METRIC_NAMES,
    build_report,
)
from ragas.dataset_schema import SingleTurnSample


# ============================================================
# 路由版 QA 调用（OPT2 组用）：聚合类走 NL2SQL，其他走 RAG
# ============================================================

def call_qa_system_with_routing(pipeline, question: str) -> Dict[str, Any]:
    """带意图路由的 QA 调用：聚合类走 NL2SQL，其他走 RAG pipeline"""
    from services.nl2sql import detect_intent, ask as nl2sql_ask

    if detect_intent(question) == "nl2sql":
        logger.info(f"  路由 → NL2SQL: {question[:50]}...")
        result = nl2sql_ask(question)
        return {
            "answer": result.answer,
            "sources": result.sources,
            "retrieved_log_ids": [],
            "retrieved_contexts": [],  # NL2SQL 无检索上下文
            "retrieval_time": result.retrieval_time,
            "llm_time": result.llm_time,
            "total_time": result.total_time,
            "total_tokens": result.total_tokens,
            "confidence": result.confidence,
        }
    else:
        return call_qa_system(pipeline, question)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger("ablation")

# EVAL_DIR 指向 evaluation/ 根（脚本在 scripts/ 下，上两级）
EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(EVAL_DIR, "data")
DOCS_DIR = os.path.join(EVAL_DIR, "docs")
REPORTS_DIR = os.path.join(DOCS_DIR, "reports")


# ============================================================
# 实验组配置
# ============================================================

GROUP_CONFIGS = {
    "A0": {
        "name": "基线（hybrid 等权）",
        "retriever_type": "hybrid",
        "vector_weight": 1.0,
        "bm25_weight": 1.0,
        "rerank": False,
        "rerank_candidate_k": 20,
    },
    "A1": {
        "name": "纯向量",
        "retriever_type": "vector",
        "vector_weight": 1.0,
        "bm25_weight": 1.0,
        "rerank": False,
        "rerank_candidate_k": 20,
    },
    "A2": {
        "name": "纯 BM25",
        "retriever_type": "bm25",
        "vector_weight": 1.0,
        "bm25_weight": 1.0,
        "rerank": False,
        "rerank_candidate_k": 20,
    },
    "A3": {
        "name": "混合-偏向量",
        "retriever_type": "hybrid",
        "vector_weight": 2.0,
        "bm25_weight": 1.0,
        "rerank": False,
        "rerank_candidate_k": 20,
    },
    "A4": {
        "name": "混合-偏 BM25",
        "retriever_type": "hybrid",
        "vector_weight": 1.0,
        "bm25_weight": 2.0,
        "rerank": False,
        "rerank_candidate_k": 20,
    },
    "A5": {
        "name": "混合 + 重排序",
        "retriever_type": "hybrid",
        "vector_weight": 1.0,
        "bm25_weight": 1.0,
        "rerank": True,
        "rerank_candidate_k": 20,
    },
    "OPT": {
        "name": "优化后（偏 BM25 hybrid, v=1.0, b=2.0）",
        "retriever_type": "hybrid",
        "vector_weight": 1.0,
        "bm25_weight": 2.0,
        "rerank": False,
        "rerank_candidate_k": 20,
    },
    "OPT2": {
        "name": "优化后 v2（NL2SQL 路由 + 偏 BM25 hybrid）",
        "retriever_type": "hybrid",
        "vector_weight": 1.0,
        "bm25_weight": 2.0,
        "rerank": False,
        "rerank_candidate_k": 20,
        "use_routing": True,  # 启用 NL2SQL 路由（聚合类走 SQL，其他走 RAG）
    },
}


def build_pipeline_for_group(group: str):
    """根据实验组配置构建 QA 流水线"""
    from services.error_handler import create_robust_pipeline

    cfg = GROUP_CONFIGS[group]
    logger.info(f"构建 Pipeline: 组={group} 配置={cfg}")
    return create_robust_pipeline(
        top_k=5,
        retriever_type=cfg["retriever_type"],
        template_type="evidence_chain",
        rerank=cfg["rerank"],
        rerank_model="BAAI/bge-reranker-base" if cfg["rerank"] else None,
        rerank_candidate_k=cfg["rerank_candidate_k"],
        vector_weight=cfg["vector_weight"],
        bm25_weight=cfg["bm25_weight"],
    )


# ============================================================
# 分层抽样（保证小样本也覆盖全部场景与难度）
# ============================================================

# 预设的 15 条分层抽样 ID：覆盖全部 8 个场景 + 3 档难度
# 分布：6 easy / 6 medium / 3 hard；每场景至少 1 条
STRATIFIED_15 = [
    "qa_001",  # error_diagnosis / easy
    "qa_007",  # error_diagnosis / medium
    "qa_013",  # service_health / easy
    "qa_017",  # service_health / medium
    "qa_021",  # user_activity / easy
    "qa_025",  # user_activity / medium
    "qa_029",  # performance / easy
    "qa_033",  # performance / medium
    "qa_039",  # security / easy
    "qa_042",  # security / medium
    "qa_047",  # resource / easy
    "qa_049",  # resource / medium
    "qa_053",  # aggregation / medium
    "qa_055",  # aggregation / hard
    "qa_060",  # time_analysis / hard
]


def stratified_subset(items: List[Dict[str, Any]], ids: List[str]) -> List[Dict[str, Any]]:
    """按指定 ID 列表抽取子集，保持原 items 顺序"""
    id_set = set(ids)
    return [it for it in items if it['id'] in id_set]


def group_paths(group: str) -> Dict[str, str]:
    """返回某组的输出文件路径（raw/json → data/，md → docs/reports/）"""
    return {
        "raw": os.path.join(DATA_DIR, f"ablation_{group}_raw.jsonl"),
        "json": os.path.join(DATA_DIR, f"ablation_{group}.json"),
        "md": os.path.join(REPORTS_DIR, f"ablation_{group}.md"),
    }


# ============================================================
# 性能优化配置
# ============================================================

# 受控并发数：DeepSeek API 限流友好，QA(IO 密集) + RAGAS(IO 密集) 都走同一个 API
# 经验值：3-5 比较安全，太高会触发 429
QA_CONCURRENCY = 3
# RAGAS 4 个指标并发跑（单条样本内部并发）
RAGAS_METRIC_CONCURRENCY = 4
# 内存攒批落盘：每 N 条写一次，平衡断点续跑与 IO 开销
FLUSH_BATCH_SIZE = 5


# ============================================================
# 并发版 RAGAS 打分（4 个指标并发，替代 run_baseline.score_one 的串行循环）
# ============================================================

async def score_one_concurrent(metrics, sample) -> Dict[str, float]:
    """4 个 RAGAS 指标并发打分，替代串行 score_one"""
    sem = asyncio.Semaphore(RAGAS_METRIC_CONCURRENCY)

    async def _score_one(m):
        async with sem:
            try:
                score = await m.single_turn_ascore(sample)
                return m.name, float(score)
            except Exception as e:
                logger.warning(f"  指标 {m.name} 评估失败: {e}")
                return m.name, None

    pairs = await asyncio.gather(*[_score_one(m) for m in metrics])
    return dict(pairs)


# ============================================================
# 单条 QA 评估（QA 调用 + RAGAS 打分，整体可并发）
# ============================================================

async def eval_one_item(
    item: Dict[str, Any],
    pipeline,
    metrics,
    group: str,
    idx: int,
    total: int,
    qa_sem: asyncio.Semaphore,
    use_routing: bool = False,
) -> Dict[str, Any]:
    """评估单条 QA：并发受控地调 QA 系统 + RAGAS 打分"""
    # 1. 调 QA 系统（同步阻塞，用 to_thread 包装 + 信号量控制并发）
    t0 = time.time()
    async with qa_sem:
        try:
            if use_routing:
                qa_out = await asyncio.to_thread(call_qa_system_with_routing, pipeline, item['user_input'])
            else:
                qa_out = await asyncio.to_thread(call_qa_system, pipeline, item['user_input'])
        except Exception as e:
            logger.error(f"  [{idx}/{total}] {item['id']} QA 系统调用失败: {e}")
            qa_out = {
                "answer": f"[QA 系统错误: {e}]",
                "sources": [],
                "retrieved_log_ids": [],
                "retrieved_contexts": [],
                "retrieval_time": 0,
                "llm_time": 0,
                "total_time": time.time() - t0,
                "total_tokens": 0,
                "confidence": "低",
            }

    logger.info(f"  [{idx}/{total}] {item['id']} ({item['scenario']}/{item['difficulty']}) "
                f"检索 {len(qa_out['retrieved_log_ids'])} 条，耗时 {qa_out['total_time']:.2f}s")

    # 2. RAGAS 评分（4 个指标并发）
    sample = SingleTurnSample(
        user_input=item['user_input'],
        retrieved_contexts=qa_out['retrieved_contexts'],
        response=qa_out['answer'],
        reference=item['reference'],
    )
    ragas_scores = await score_one_concurrent(metrics, sample)
    for k, v in ragas_scores.items():
        logger.info(f"  [{idx}/{total}] {item['id']} {k}: {v}")

    # 3. 组装结果
    rec = {
        "id": item['id'],
        "scenario": item['scenario'],
        "difficulty": item['difficulty'],
        "user_input": item['user_input'],
        "reference": item['reference'],
        "system_answer": qa_out['answer'],
        "system_retrieved_log_ids": qa_out['retrieved_log_ids'],
        "system_retrieved_contexts": qa_out['retrieved_contexts'],
        "retrieval_time": qa_out['retrieval_time'],
        "llm_time": qa_out['llm_time'],
        "total_time": qa_out['total_time'],
        "total_tokens": qa_out['total_tokens'],
        "confidence": qa_out['confidence'],
        "ragas_scores": ragas_scores,
        "group": group,
    }
    return rec


# ============================================================
# 单组评估（并发版）
# ============================================================

async def run_group(
    group: str,
    items: List[Dict[str, Any]],
    limit: Optional[int] = None,
    reset: bool = False,
) -> Dict[str, Any]:
    """跑单组实验（并发版）"""
    paths = group_paths(group)
    cfg = GROUP_CONFIGS[group]

    # 过滤
    filtered = items
    if limit:
        filtered = filtered[:limit]

    logger.info("=" * 60)
    logger.info(f"消融实验 {group}: {cfg['name']}")
    logger.info("=" * 60)
    logger.info(f"待评估条目: {len(filtered)}")
    logger.info(f"并发配置: QA_CONCURRENCY={QA_CONCURRENCY}, "
                f"RAGAS_METRIC_CONCURRENCY={RAGAS_METRIC_CONCURRENCY}, "
                f"FLUSH_BATCH_SIZE={FLUSH_BATCH_SIZE}")

    # 缓存
    done_ids = set()
    if reset and os.path.exists(paths["raw"]):
        os.remove(paths["raw"])
        logger.info(f"已清空缓存: {paths['raw']}")

    cached_results = []
    if os.path.exists(paths["raw"]):
        with open(paths["raw"], 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    done_ids.add(rec['id'])
                    cached_results.append(rec)
                except Exception:
                    pass
    if done_ids:
        logger.info(f"发现 {len(done_ids)} 条已完成缓存，将跳过")

    # 待跑条目（排除已缓存）
    todo = [it for it in filtered if it['id'] not in done_ids]
    logger.info(f"需新跑条目: {len(todo)}（跳过 {len(filtered) - len(todo)} 条缓存）")

    # 初始化
    logger.info("初始化 QA Pipeline...")
    pipeline = build_pipeline_for_group(group)
    logger.info("初始化 RAGAS 指标...")
    metrics = get_default_metrics()
    logger.info(f"RAGAS 指标: {[m.name for m in metrics]}")

    # 并发跑所有待评估条目
    qa_sem = asyncio.Semaphore(QA_CONCURRENCY)
    start_ts = time.time()

    # 是否启用 NL2SQL 路由（OPT2 组）
    use_routing = GROUP_CONFIGS[group].get("use_routing", False)
    if use_routing:
        logger.info(f"组 {group} 启用 NL2SQL 路由：聚合类走 SQL，其他走 RAG")

    # 用 asyncio.as_completed 实现流式进度 + 攒批落盘
    tasks = [
        eval_one_item(item, pipeline, metrics, group, idx, len(todo), qa_sem, use_routing)
        for idx, item in enumerate(todo, 1)
    ]

    new_results = []
    pending_flush = []  # 攒批缓冲区

    async def _flush_buffer():
        """把缓冲区里的结果批量写入磁盘"""
        if not pending_flush:
            return
        with open(paths["raw"], 'a', encoding='utf-8') as f:
            for rec in pending_flush:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        pending_flush.clear()

    # as_completed：先完成的先处理，便于实时看进度
    completed = 0
    for coro in asyncio.as_completed(tasks):
        rec = await coro
        new_results.append(rec)
        pending_flush.append(rec)
        completed += 1

        # 攒批落盘
        if len(pending_flush) >= FLUSH_BATCH_SIZE:
            await _flush_buffer()

        # 进度
        elapsed = time.time() - start_ts
        avg = elapsed / completed
        remaining = (len(todo) - completed) * avg
        logger.info(f"  进度 {completed}/{len(todo)}，累计 {elapsed:.0f}s，"
                    f"预计剩余 {remaining:.0f}s（avg {avg:.1f}s/条）")

    # 收尾：把缓冲区剩余的写盘
    await _flush_buffer()

    total_time = time.time() - start_ts
    logger.info("=" * 60)
    logger.info(f"组 {group} 评估完成，新增 {len(new_results)} 条，总耗时 {total_time:.0f}s "
                f"(平均 {total_time/max(1,len(new_results)):.1f}s/条)")
    logger.info("=" * 60)

    # 合并缓存 + 新结果，按原 items 顺序排序
    results = list(cached_results) + new_results
    id_order = {it['id']: i for i, it in enumerate(filtered)}
    results.sort(key=lambda r: id_order.get(r['id'], 9999))

    report = build_report(results, total_time)
    report["group"] = group
    report["group_name"] = cfg["name"]
    report["group_config"] = cfg
    return report


def save_group_report(group: str, report: Dict[str, Any]):
    """保存单组报告"""
    paths = group_paths(group)
    with open(paths["json"], 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"JSON 报告: {paths['json']}")

    md = render_group_markdown(group, report)
    with open(paths["md"], 'w', encoding='utf-8') as f:
        f.write(md)
    logger.info(f"Markdown 报告: {paths['md']}")


def render_group_markdown(group: str, report: Dict[str, Any]) -> str:
    """渲染单组 Markdown 报告"""
    cfg = GROUP_CONFIGS[group]
    lines = []
    lines.append(f"# 消融实验 {group}: {cfg['name']}\n")
    lines.append(f"- 生成时间: {report['generated_at']}")
    lines.append(f"- 评估条目: {report['total_items']}")
    lines.append(f"- 总耗时: {report['performance']['total_time_sec']}s "
                 f"(平均 {report['performance']['avg_per_item_sec']}s/条)")
    lines.append(f"- 配置: retriever={cfg['retriever_type']} "
                 f"v_w={cfg['vector_weight']} b_w={cfg['bm25_weight']} "
                 f"rerank={cfg['rerank']}\n")

    # 1. 总体指标
    lines.append("## 1. 总体指标\n")
    lines.append("| 指标 | 平均分 | 最低 | 最高 | 成功数 | 失败数 |")
    lines.append("|---|---|---|---|---|---|")
    for name in METRIC_NAMES:
        s = report['ragas_metrics'].get(name, {})
        if s.get('mean') is not None:
            lines.append(f"| {name} | {s['mean']} | {s['min']} | {s['max']} | {s['count']} | {s['failed']} |")
        else:
            lines.append(f"| {name} | N/A | - | - | 0 | {s.get('failed', 0)} |")
    lines.append("")

    # 2. 按场景
    lines.append("## 2. 按场景分组\n")
    lines.append("| 场景 | 数量 | faithfulness | answer_relevancy | context_precision | context_recall |")
    lines.append("|---|---|---|---|---|---|")
    for s, st in sorted(report['by_scenario'].items()):
        m = st['metrics']
        lines.append(
            f"| {s} | {st['count']} | "
            f"{m.get('faithfulness', 'N/A')} | {m.get('answer_relevancy', 'N/A')} | "
            f"{m.get('context_precision', 'N/A')} | {m.get('context_recall', 'N/A')} |"
        )
    lines.append("")

    # 3. 性能
    lines.append("## 3. 性能指标\n")
    p = report['performance']
    lines.append(f"- 平均检索耗时: {p['avg_retrieval_time_sec']}s")
    lines.append(f"- 平均 LLM 耗时: {p['avg_llm_time_sec']}s")
    lines.append(f"- 平均 Token 数: {p['avg_total_tokens']}")
    lines.append("")

    return "\n".join(lines)


# ============================================================
# 汇总报告
# ============================================================

def build_summary(groups: List[str]) -> Dict[str, Any]:
    """汇总各组结果，输出对比表"""
    summary = {
        "version": "1.0",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "groups": {},
    }

    for g in groups:
        paths = group_paths(g)
        json_path = paths["json"]
        if not os.path.exists(json_path):
            logger.warning(f"组 {g} 报告不存在: {json_path}")
            continue
        with open(json_path, 'r', encoding='utf-8') as f:
            report = json.load(f)
        cfg = GROUP_CONFIGS[g]
        summary["groups"][g] = {
            "name": cfg["name"],
            "config": cfg,
            "metrics": {k: v.get("mean") for k, v in report.get("ragas_metrics", {}).items()},
            "performance": report.get("performance", {}),
            "total_items": report.get("total_items", 0),
        }

    return summary


def save_summary(summary: Dict[str, Any]):
    """保存汇总报告（JSON → data/，Markdown → docs/）"""
    json_path = os.path.join(DATA_DIR, "ablation_summary.json")
    md_path = os.path.join(DOCS_DIR, "ablation_summary.md")

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    logger.info(f"汇总 JSON: {json_path}")

    md = render_summary_markdown(summary)
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md)
    logger.info(f"汇总 Markdown: {md_path}")


def render_summary_markdown(summary: Dict[str, Any]) -> str:
    """渲染汇总 Markdown"""
    lines = []
    lines.append("# 任务 7.5 消融实验汇总报告\n")
    lines.append(f"- 生成时间: {summary['generated_at']}")
    lines.append(f"- 实验组数: {len(summary['groups'])}\n")

    # 主对比表
    lines.append("## 1. 各组指标对比\n")
    lines.append("| 组别 | 名称 | 配置 | Faith. | AnsRel. | CtxPrec | CtxRecall | 检索耗时 | 总耗时 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")

    for g, info in summary["groups"].items():
        m = info["metrics"]
        p = info["performance"]
        cfg = info["config"]
        cfg_str = f"{cfg['retriever_type']}"
        if cfg["retriever_type"] == "hybrid":
            cfg_str += f" v={cfg['vector_weight']} b={cfg['bm25_weight']}"
        if cfg["rerank"]:
            cfg_str += "+rerank"

        faith = m.get("faithfulness")
        ans_rel = m.get("answer_relevancy")
        ctx_prec = m.get("context_precision")
        ctx_rec = m.get("context_recall")
        ret_t = p.get("avg_retrieval_time_sec")
        total_t = p.get("avg_per_item_sec")

        lines.append(
            f"| {g} | {info['name']} | {cfg_str} | "
            f"{faith if faith is not None else 'N/A'} | "
            f"{ans_rel if ans_rel is not None else 'N/A'} | "
            f"{ctx_prec if ctx_prec is not None else 'N/A'} | "
            f"{ctx_rec if ctx_rec is not None else 'N/A'} | "
            f"{ret_t if ret_t is not None else 'N/A'}s | "
            f"{total_t if total_t is not None else 'N/A'}s |"
        )
    lines.append("")

    # 关键对比
    lines.append("## 2. 关键对比维度\n")
    groups = summary["groups"]

    def get_metric(g, name):
        return groups.get(g, {}).get("metrics", {}).get(name)

    def diff(g1, g2, name):
        v1 = get_metric(g1, name)
        v2 = get_metric(g2, name)
        if v1 is None or v2 is None:
            return None
        return round(v1 - v2, 4)

    # A1 vs A2
    if "A1" in groups and "A2" in groups:
        lines.append("### A1 (纯向量) vs A2 (纯 BM25)\n")
        lines.append("| 指标 | A1 | A2 | 差值(A1-A2) | 谁优 |")
        lines.append("|---|---|---|---|---|")
        for name in METRIC_NAMES:
            v1 = get_metric("A1", name)
            v2 = get_metric("A2", name)
            d = diff("A1", "A2", name)
            if d is not None:
                winner = "A1" if d > 0.01 else ("A2" if d < -0.01 else "持平")
                lines.append(f"| {name} | {v1} | {v2} | {d:+.4f} | {winner} |")
            else:
                lines.append(f"| {name} | {v1} | {v2} | N/A | N/A |")
        lines.append("")

    # A0 vs A1, A2
    if "A0" in groups and "A1" in groups and "A2" in groups:
        lines.append("### A0 (混合等权) vs 单路 (A1/A2)\n")
        lines.append("| 指标 | A0 | A1 | A2 | A0-A1 | A0-A2 |")
        lines.append("|---|---|---|---|---|---|")
        for name in METRIC_NAMES:
            v0 = get_metric("A0", name)
            v1 = get_metric("A1", name)
            v2 = get_metric("A2", name)
            d1 = diff("A0", "A1", name)
            d2 = diff("A0", "A2", name)
            d1_str = f"{d1:+.4f}" if d1 is not None else "N/A"
            d2_str = f"{d2:+.4f}" if d2 is not None else "N/A"
            lines.append(f"| {name} | {v0} | {v1} | {v2} | {d1_str} | {d2_str} |")
        lines.append("")

    # A3 vs A4 vs A0
    if "A3" in groups and "A4" in groups and "A0" in groups:
        lines.append("### A3 (偏向量) vs A4 (偏 BM25) vs A0 (等权)\n")
        lines.append("| 指标 | A0 | A3 | A4 |")
        lines.append("|---|---|---|---|")
        for name in METRIC_NAMES:
            v0 = get_metric("A0", name)
            v3 = get_metric("A3", name)
            v4 = get_metric("A4", name)
            lines.append(f"| {name} | {v0} | {v3} | {v4} |")
        lines.append("")

    # A5 vs A0
    if "A5" in groups and "A0" in groups:
        lines.append("### A5 (混合+重排序) vs A0 (基线)\n")
        lines.append("| 指标 | A0 | A5 | 差值(A5-A0) | 提升? |")
        lines.append("|---|---|---|---|---|")
        for name in METRIC_NAMES:
            v0 = get_metric("A0", name)
            v5 = get_metric("A5", name)
            d = diff("A5", "A0", name)
            if d is not None:
                better = "✓ 提升" if d > 0.01 else ("✗ 下降" if d < -0.01 else "持平")
                lines.append(f"| {name} | {v0} | {v5} | {d:+.4f} | {better} |")
            else:
                lines.append(f"| {name} | {v0} | {v5} | N/A | N/A |")
        # 耗时对比
        t0 = groups["A0"]["performance"].get("avg_retrieval_time_sec")
        t5 = groups["A5"]["performance"].get("avg_retrieval_time_sec")
        if t0 is not None and t5 is not None:
            lines.append(f"| 检索耗时 | {t0}s | {t5}s | {t5-t0:+.3f}s | "
                         f"{'✗ 变慢' if t5 > t0 else '✓ 变快'} |")
        lines.append("")

    # 性能对比
    lines.append("## 3. 性能对比\n")
    lines.append("| 组别 | 检索耗时 | LLM 耗时 | 单条总耗时 | Token 数 |")
    lines.append("|---|---|---|---|---|")
    for g, info in summary["groups"].items():
        p = info["performance"]
        lines.append(
            f"| {g} | {p.get('avg_retrieval_time_sec', 'N/A')}s | "
            f"{p.get('avg_llm_time_sec', 'N/A')}s | "
            f"{p.get('avg_per_item_sec', 'N/A')}s | "
            f"{p.get('avg_total_tokens', 'N/A')} |"
        )
    lines.append("")

    # 结论建议
    lines.append("## 4. 自动结论\n")
    lines.append("```")
    # 简单决策：找 context_precision 最高的组
    best_g = None
    best_cp = -1
    for g, info in summary["groups"].items():
        cp = info["metrics"].get("context_precision")
        if cp is not None and cp > best_cp:
            best_cp = cp
            best_g = g
    if best_g:
        lines.append(f"主指标 context_precision 最高: 组 {best_g} ({GROUP_CONFIGS[best_g]['name']}) = {best_cp}")
        lines.append(f"推荐生产配置: {GROUP_CONFIGS[best_g]}")
    lines.append("```\n")

    # 决策路径分析（按 ablation_design.md 的决策树）
    lines.append("## 5. 决策路径分析\n")
    a0 = groups.get("A0", {}).get("metrics", {})
    a1 = groups.get("A1", {}).get("metrics", {})
    a2 = groups.get("A2", {}).get("metrics", {})
    a3 = groups.get("A3", {}).get("metrics", {})
    a4 = groups.get("A4", {}).get("metrics", {})
    a5 = groups.get("A5", {}).get("metrics", {})

    lines.append("### 5.1 单路对比（A1 vs A2）：判断日志检索场景偏好\n")
    if a1 and a2:
        cp_diff = (a1.get("context_precision", 0) or 0) - (a2.get("context_precision", 0) or 0)
        if cp_diff < -0.1:
            lines.append(f"- **BM25 明显占优**（ctx_prec 差 {cp_diff:+.4f}）：日志查询高度依赖关键词匹配（错误码、服务名、级别），向量检索对精确关键词不敏感")
        elif cp_diff > 0.1:
            lines.append(f"- **向量明显占优**（ctx_prec 差 {cp_diff:+.4f}）：日志查询存在大量语义改写，向量检索捕获同义表达")
        else:
            lines.append(f"- **两者相近**（ctx_prec 差 {cp_diff:+.4f}，<0.1）：日志查询兼有语义与关键词需求")
    lines.append("")

    lines.append("### 5.2 混合 vs 单路（A0 vs A1/A2）：判断 RRF 融合收益\n")
    if a0 and a1 and a2:
        cp_a0 = a0.get("context_precision", 0) or 0
        cp_a1 = a1.get("context_precision", 0) or 0
        cp_a2 = a2.get("context_precision", 0) or 0
        best_single = max(cp_a1, cp_a2)
        if cp_a0 - best_single > 0.05:
            lines.append(f"- **RRF 融合明显优于单路**（A0 ctx_prec={cp_a0:.4f} > 单路最优 {best_single:.4f}，+{cp_a0-best_single:.4f}）")
        elif cp_a0 < best_single - 0.05:
            lines.append(f"- **RRF 融合反而弱于单路**（A0 ctx_prec={cp_a0:.4f} < 单路最优 {best_single:.4f}，{cp_a0-best_single:.4f}），弱路拖累融合结果")
        else:
            lines.append(f"- **RRF 融合与单路持平**（A0 ctx_prec={cp_a0:.4f} ≈ 单路最优 {best_single:.4f}）")
    lines.append("")

    lines.append("### 5.3 权重偏向（A3 vs A4 vs A0）：判断最优权重\n")
    if a0 and a3 and a4:
        cp_a0 = a0.get("context_precision", 0) or 0
        cp_a3 = a3.get("context_precision", 0) or 0
        cp_a4 = a4.get("context_precision", 0) or 0
        ar_a0 = a0.get("answer_relevancy", 0) or 0
        ar_a3 = a3.get("answer_relevancy", 0) or 0
        ar_a4 = a4.get("answer_relevancy", 0) or 0
        lines.append(f"- A0(等权): ctx_prec={cp_a0:.4f}, ans_rel={ar_a0:.4f}")
        lines.append(f"- A3(偏向量 v=2.0): ctx_prec={cp_a3:.4f}, ans_rel={ar_a3:.4f}")
        lines.append(f"- A4(偏BM25 v=1.0,b=2.0): ctx_prec={cp_a4:.4f}, ans_rel={ar_a4:.4f}")
        # 综合判断
        if cp_a3 > cp_a0 and cp_a3 > cp_a4:
            lines.append("- **偏向量(A3) ctx_prec 最优**：适合语义改写多的查询场景")
        elif cp_a4 > cp_a0 and cp_a4 > cp_a3:
            lines.append("- **偏 BM25(A4) ctx_prec 最优**：适合精确关键词多的查询场景")
        else:
            lines.append("- **等权(A0) ctx_prec 最优或持平**：两路贡献均衡，无需偏向")
    lines.append("")

    lines.append("### 5.4 重排序收益（A5 vs A0）：判断 Cross-Encoder 价值\n")
    if a0 and a5:
        cp_a0 = a0.get("context_precision", 0) or 0
        cp_a5 = a5.get("context_precision", 0) or 0
        t0 = groups["A0"]["performance"].get("avg_per_item_sec", 0) or 0
        t5 = groups["A5"]["performance"].get("avg_per_item_sec", 0) or 0
        cp_diff = cp_a5 - cp_a0
        time_ratio = t5 / t0 if t0 > 0 else 0
        if cp_diff > 0.05:
            lines.append(f"- **重排序带来显著提升**（ctx_prec +{cp_diff:.4f}），耗时 {time_ratio:.1f}x，"
                         f"{'可接受' if time_ratio < 2 else '代价较高'}")
        elif cp_diff < -0.05:
            lines.append(f"- **重排序反而下降**（ctx_prec {cp_diff:+.4f}）：Cross-Encoder 可能将相关日志排到 Top-5 之外，"
                         f"且耗时 {time_ratio:.1f}x，**不推荐**")
        else:
            lines.append(f"- **重排序无明显提升**（ctx_prec {cp_diff:+.4f} < 0.05），耗时 {time_ratio:.1f}x，"
                         f"**性价比低，不推荐**")
    lines.append("")

    lines.append("## 6. 指标解读说明\n")
    lines.append("- **context_precision / answer_relevancy 为主指标**：直接反映检索与回答质量")
    lines.append("- **faithfulness / context_recall 设计性偏低**：本项目 Prompt 要求 LLM 输出推论与建议，")
    lines.append("  这些内容来自 LLM 领域知识而非检索日志，故绝对值低于 1.0 是设计必然，看组间相对变化")
    lines.append("- 显著差异阈值: >0.1（RAGAS 波动约 ±0.05）")

    return "\n".join(lines)


# ============================================================
# 入口
# ============================================================

async def run_one_group(group: str, items, limit, reset):
    """跑单组并保存报告"""
    report = await run_group(group, items, limit=limit, reset=reset)
    save_group_report(group, report)

    # 打印汇总
    print(f"\n{'=' * 60}")
    print(f"组 {group} ({GROUP_CONFIGS[group]['name']}) 评估汇总")
    print("=" * 60)
    for name in METRIC_NAMES:
        s = report['ragas_metrics'].get(name, {})
        print(f"  {name:25s} = {s.get('mean', 'N/A')}")
    print("=" * 60)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", type=str, required=True,
                        choices=["A0", "A1", "A2", "A3", "A4", "A5", "OPT", "OPT2", "all"],
                        help="实验组别（OPT2=NL2SQL 路由 + 偏 BM25 hybrid）")
    parser.add_argument("--limit", type=int, default=None,
                        help="只跑前 N 条（调试用，会偏斜场景分布）")
    parser.add_argument("--stratified", action="store_true",
                        help="使用预设的 15 条分层抽样（覆盖全部 8 场景 + 3 难度，推荐）")
    parser.add_argument("--reset", action="store_true",
                        help="清空该组缓存重新跑")
    args = parser.parse_args()

    all_items = load_items()

    # 选择样本子集
    if args.stratified:
        items = stratified_subset(all_items, STRATIFIED_15)
        logger.info(f"使用分层抽样: {len(items)} 条（覆盖全部场景与难度）")
        logger.info(f"样本 ID: {[it['id'] for it in items]}")
        # 分层抽样时强制 limit=None（已预先抽样）
        effective_limit = None
    else:
        items = all_items
        effective_limit = args.limit

    if args.group == "all":
        # 跑所有组
        for g in ["A0", "A1", "A2", "A3", "A4", "A5"]:
            asyncio.run(run_one_group(g, items, effective_limit, args.reset))
        # 生成汇总
        summary = build_summary(["A0", "A1", "A2", "A3", "A4", "A5"])
        save_summary(summary)
        print("\n汇总报告已生成: evaluation/ablation_summary.md")
    else:
        asyncio.run(run_one_group(args.group, items, effective_limit, args.reset))
        # 单组跑完后也更新汇总（包含已有报告的组）
        existing = [g for g in ["A0", "A1", "A2", "A3", "A4", "A5"]
                    if os.path.exists(group_paths(g)["json"])]
        if len(existing) > 1:
            summary = build_summary(existing)
            save_summary(summary)
            print(f"\n已更新汇总报告（含 {len(existing)} 组）: evaluation/ablation_summary.md")


if __name__ == "__main__":
    main()
