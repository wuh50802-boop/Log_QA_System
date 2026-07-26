"""

流程：
1. 加载测试集 60 条 QA
2. 对每条 QA：
   a. 把 user_input 喂给 QA 系统（RobustQAPipeline）
   b. 系统返回 retrieved_contexts + response
   c. 用 RAGAS 4 指标打分
3. 汇总成基线报告（每个指标的平均值）
4. 输出 baseline_report.json + baseline_report.md

运行：
    cd backend
    # 全量跑（约 15-25 分钟）
    venv/Scripts/python.exe -m evaluation.run_baseline
    # 只跑前 N 条（调试用）
    venv/Scripts/python.exe -m evaluation.run_baseline --limit 5
    # 只跑某个场景
    venv/Scripts/python.exe -m evaluation.run_baseline --scenario error_diagnosis
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

# 让 services.* 可被 import（脚本在 scripts/ 下，需上三级到 backend/）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from evaluation.testset_loader import load_items
from evaluation.ragas_config import get_default_metrics
from evaluation.eval_core import (
    build_pipeline,
    format_retrieved_contexts,
    call_qa_system,
    score_one,
    METRIC_NAMES,
    build_report,
)
from ragas.dataset_schema import SingleTurnSample

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
# 抑制过多噪声
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger("baseline")

# EVAL_DIR 指向 evaluation/ 根（脚本在 scripts/ 下，上两级）
EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(EVAL_DIR, "data")
DOCS_DIR = os.path.join(EVAL_DIR, "docs")
REPORT_JSON = os.path.join(DATA_DIR, "baseline_report.json")
REPORT_MD = os.path.join(DOCS_DIR, "baseline_report.md")
RAW_CACHE = os.path.join(DATA_DIR, "baseline_raw.jsonl")  # 每条结果逐行落盘，防中断丢失


# ============================================================
# 主流程
# ============================================================

async def run_evaluation(
    items: List[Dict[str, Any]],
    limit: Optional[int] = None,
    scenario: Optional[str] = None,
) -> Dict[str, Any]:
    """跑完整评估"""
    # 过滤
    filtered = items
    if scenario:
        filtered = [i for i in filtered if i['scenario'] == scenario]
    if limit:
        filtered = filtered[:limit]

    logger.info(f"=" * 60)
    logger.info(f"基线评估开始")
    logger.info(f"=" * 60)
    logger.info(f"待评估条目: {len(filtered)}")
    logger.info(f"场景过滤: {scenario or '全部'}")

    # 加载已完成的缓存（断点续跑）
    done_ids = set()
    if os.path.exists(RAW_CACHE):
        with open(RAW_CACHE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    done_ids.add(rec['id'])
                except Exception:
                    pass
    if done_ids:
        logger.info(f"发现 {len(done_ids)} 条已完成缓存，将跳过")

    # 初始化 pipeline 和 metrics
    logger.info("初始化 QA Pipeline...")
    pipeline = build_pipeline()
    logger.info("初始化 RAGAS 指标...")
    metrics = get_default_metrics()
    logger.info(f"RAGAS 指标: {[m.name for m in metrics]}")

    # 跑每条
    results = []
    start_ts = time.time()

    for idx, item in enumerate(filtered, 1):
        if item['id'] in done_ids:
            logger.info(f"[{idx}/{len(filtered)}] {item['id']} 跳过（已缓存）")
            # 从缓存读回
            with open(RAW_CACHE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if rec['id'] == item['id']:
                            results.append(rec)
                            break
                    except Exception:
                        pass
            continue

        logger.info(f"[{idx}/{len(filtered)}] {item['id']} ({item['scenario']}/{item['difficulty']})")
        logger.info(f"  问题: {item['user_input'][:60]}...")

        # 1. 调 QA 系统
        t0 = time.time()
        try:
            qa_out = call_qa_system(pipeline, item['user_input'])
        except Exception as e:
            logger.error(f"  QA 系统调用失败: {e}")
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

        logger.info(f"  检索 {len(qa_out['retrieved_log_ids'])} 条日志，"
                    f"耗时 {qa_out['total_time']:.2f}s")

        # 2. RAGAS 评分（4 指标，覆盖召回/精度/忠实/切题）
        sample = SingleTurnSample(
            user_input=item['user_input'],
            retrieved_contexts=qa_out['retrieved_contexts'],
            response=qa_out['answer'],
            reference=item['reference'],
        )
        ragas_scores = await score_one(metrics, sample)
        for k, v in ragas_scores.items():
            logger.info(f"  {k}: {v}")

        # 3. 组装结果（仅保留 RAGAS 4 指标 + 性能指标，移除冗余的 ID 级/模板级 hit_rate）
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
        }
        results.append(rec)

        # 5. 落盘缓存（每条立刻写，防中断）
        with open(RAW_CACHE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # 6. 估算剩余时间
        elapsed = time.time() - start_ts
        avg_per_item = elapsed / idx
        remaining = (len(filtered) - idx) * avg_per_item
        logger.info(f"  累计耗时 {elapsed:.0f}s，预计剩余 {remaining:.0f}s")

    total_time = time.time() - start_ts
    logger.info(f"=" * 60)
    logger.info(f"评估完成，总耗时 {total_time:.0f}s")
    logger.info(f"=" * 60)

    # 汇总报告
    report = build_report(results, total_time)
    return report


# ============================================================
# 报告生成（METRIC_NAMES / build_report 已移至 eval_core.py）
# ============================================================

def save_report(report: Dict[str, Any]):
    """保存报告（JSON + Markdown）"""
    # JSON
    with open(REPORT_JSON, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"JSON 报告: {REPORT_JSON}")

    # Markdown
    md = render_markdown(report)
    with open(REPORT_MD, 'w', encoding='utf-8') as f:
        f.write(md)
    logger.info(f"Markdown 报告: {REPORT_MD}")


def render_markdown(report: Dict[str, Any]) -> str:
    """渲染 Markdown 报告"""
    lines = []
    lines.append("# RAGAS 基线评估报告\n")
    lines.append(f"- 生成时间: {report['generated_at']}")
    lines.append(f"- 评估条目: {report['total_items']}")
    lines.append(f"- 总耗时: {report['performance']['total_time_sec']}s "
                 f"(平均 {report['performance']['avg_per_item_sec']}s/条)\n")

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

    # 检索召回与精度已由 RAGAS context_recall / context_precision 覆盖，不再单列
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

    # 3. 按难度
    lines.append("## 3. 按难度分组\n")
    lines.append("| 难度 | 数量 | faithfulness | answer_relevancy | context_precision | context_recall |")
    lines.append("|---|---|---|---|---|---|")
    for d in ["easy", "medium", "hard"]:
        st = report['by_difficulty'].get(d, {})
        m = st.get('metrics', {})
        lines.append(
            f"| {d} | {st.get('count', 0)} | "
            f"{m.get('faithfulness', 'N/A')} | {m.get('answer_relevancy', 'N/A')} | "
            f"{m.get('context_precision', 'N/A')} | {m.get('context_recall', 'N/A')} |"
        )
    lines.append("")

    # 4. 性能
    lines.append("## 4. 性能指标\n")
    p = report['performance']
    lines.append(f"- 平均检索耗时: {p['avg_retrieval_time_sec']}s")
    lines.append(f"- 平均 LLM 耗时: {p['avg_llm_time_sec']}s")
    lines.append(f"- 平均 Token 数: {p['avg_total_tokens']}")
    lines.append("")

    # 5. 结论
    lines.append("## 5. 基线结论\n")
    lines.append("```")
    fm = report['ragas_metrics'].get('faithfulness', {}).get('mean', 'N/A')
    ar = report['ragas_metrics'].get('answer_relevancy', {}).get('mean', 'N/A')
    cp = report['ragas_metrics'].get('context_precision', {}).get('mean', 'N/A')
    cr = report['ragas_metrics'].get('context_recall', {}).get('mean', 'N/A')
    lines.append(f"Faithfulness       = {fm}")
    lines.append(f"Answer Relevancy   = {ar}")
    lines.append(f"Context Precision  = {cp}")
    lines.append(f"Context Recall     = {cr}")
    lines.append("```\n")

    return "\n".join(lines)


# ============================================================
# 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="只跑前 N 条（调试用）")
    parser.add_argument("--scenario", type=str, default=None,
                        help="只跑某个场景")
    parser.add_argument("--reset", action="store_true",
                        help="清空缓存重新跑")
    args = parser.parse_args()

    if args.reset and os.path.exists(RAW_CACHE):
        os.remove(RAW_CACHE)
        logger.info(f"已清空缓存: {RAW_CACHE}")

    items = load_items()
    report = asyncio.run(run_evaluation(
        items,
        limit=args.limit,
        scenario=args.scenario,
    ))
    save_report(report)

    # 打印汇总（仅 RAGAS 4 指标）
    print("\n" + "=" * 60)
    print("基线评估汇总")
    print("=" * 60)
    for name in METRIC_NAMES:
        s = report['ragas_metrics'].get(name, {})
        print(f"  {name:25s} = {s.get('mean', 'N/A')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
