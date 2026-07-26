"""
评估核心模块 - 基线与消融实验共享的工具函数

包含：
- METRIC_NAMES: RAGAS 4 指标名
- format_retrieved_contexts: 格式化检索结果为 RAGAS 用字符串
- call_qa_system: 调用 QA pipeline 获取回答
- score_one: 串行版 RAGAS 打分（单条 4 指标）
- build_report: 汇总评估结果为报告 dict
"""
import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

from ragas.dataset_schema import SingleTurnSample

logger = logging.getLogger("eval_core")

# RAGAS 4 指标名（固定顺序）
METRIC_NAMES = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]


# ============================================================
# QA Pipeline 调用
# ============================================================

def build_pipeline():
    """构建 QA 流水线（与生产 API 保持一致：hybrid 检索 + evidence_chain 模板）"""
    from services.error_handler import create_robust_pipeline
    return create_robust_pipeline(
        top_k=5,
        retriever_type="hybrid",
        template_type="evidence_chain",
    )


def format_retrieved_contexts(sources: List[Dict[str, Any]]) -> List[str]:
    """
    把 QA 系统返回的 sources 格式化为 RAGAS 用 retrieved_contexts 字符串列表。
    格式与 reference_contexts 对齐，便于公平比较：
        [ID:xxx] service / level / timestamp / content
    """
    formatted = []
    for s in sources:
        log_id = s.get('log_id', '?')
        service = s.get('service', 'unknown')
        level = s.get('level', 'INFO')
        timestamp = s.get('timestamp', '')
        content = s.get('content', '') or ''
        # 截断过长内容，避免 LLM 评估上下文超长
        if len(content) > 300:
            content = content[:300] + "..."
        formatted.append(
            f"[ID:{log_id}] {service} / {level} / {timestamp} / {content}"
        )
    return formatted


def call_qa_system(pipeline, question: str) -> Dict[str, Any]:
    """调用 QA 系统获取回答与检索结果"""
    # 显式传 history=[] 避免内部累积对话历史污染每条独立评估
    result = pipeline.ask(question, history=[])
    return {
        "answer": result.answer,
        "sources": result.sources,
        "retrieved_log_ids": [s.get('log_id') for s in result.sources if s.get('log_id') is not None],
        "retrieved_contexts": format_retrieved_contexts(result.sources),
        "retrieval_time": result.retrieval_time,
        "llm_time": result.llm_time,
        "total_time": result.total_time,
        "total_tokens": result.total_tokens,
        "confidence": result.confidence,
    }


# ============================================================
# RAGAS 评估
# ============================================================

async def score_one(metrics, sample: SingleTurnSample) -> Dict[str, float]:
    """对单条样本跑 4 个指标（串行版），返回 {metric_name: score}"""
    out = {}
    for m in metrics:
        name = m.name
        try:
            score = await m.single_turn_ascore(sample)
            out[name] = float(score)
        except Exception as e:
            logger.warning(f"  指标 {name} 评估失败: {e}")
            out[name] = None
    return out


# ============================================================
# 报告生成
# ============================================================

def build_report(results: List[Dict[str, Any]], total_time: float) -> Dict[str, Any]:
    """汇总评估结果为报告 dict"""
    n = len(results)

    # 各指标统计
    metric_stats = {}
    for name in METRIC_NAMES:
        scores = [r['ragas_scores'].get(name) for r in results
                  if r['ragas_scores'].get(name) is not None]
        if scores:
            metric_stats[name] = {
                "mean": round(sum(scores) / len(scores), 4),
                "min": round(min(scores), 4),
                "max": round(max(scores), 4),
                "count": len(scores),
                "failed": n - len(scores),
            }
        else:
            metric_stats[name] = {"mean": None, "count": 0, "failed": n}

    # 按场景分组
    by_scenario = {}
    for r in results:
        s = r['scenario']
        by_scenario.setdefault(s, []).append(r)
    scenario_stats = {}
    for s, rs in by_scenario.items():
        scenario_stats[s] = {
            "count": len(rs),
            "metrics": {
                name: round(sum(
                    r['ragas_scores'][name] for r in rs
                    if r['ragas_scores'].get(name) is not None
                ) / max(1, sum(
                    1 for r in rs if r['ragas_scores'].get(name) is not None
                )), 4)
                for name in METRIC_NAMES
            },
        }

    # 按难度分组
    by_diff = {}
    for r in results:
        d = r['difficulty']
        by_diff.setdefault(d, []).append(r)
    difficulty_stats = {}
    for d, rs in by_diff.items():
        difficulty_stats[d] = {
            "count": len(rs),
            "metrics": {
                name: round(sum(
                    r['ragas_scores'][name] for r in rs
                    if r['ragas_scores'].get(name) is not None
                ) / max(1, sum(
                    1 for r in rs if r['ragas_scores'].get(name) is not None
                )), 4)
                for name in METRIC_NAMES
            },
        }

    # 性能指标
    perf_stats = {
        "total_time_sec": round(total_time, 1),
        "avg_per_item_sec": round(total_time / n, 2) if n else 0,
        "avg_retrieval_time_sec": round(
            sum(r['retrieval_time'] for r in results) / n, 3
        ) if n else 0,
        "avg_llm_time_sec": round(
            sum(r['llm_time'] for r in results) / n, 3
        ) if n else 0,
        "avg_total_tokens": round(
            sum(r['total_tokens'] for r in results) / n
        ) if n else 0,
    }

    return {
        "version": "1.0",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_items": n,
        "ragas_metrics": metric_stats,
        "by_scenario": scenario_stats,
        "by_difficulty": difficulty_stats,
        "performance": perf_stats,
        "results": results,
    }
