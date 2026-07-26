"""
RAGAS 环境验证脚本


本脚本用一条样例数据跑通 RAGAS 4 个核心指标，验证：
1. DeepSeek 可作为 RAGAS Evaluator LLM
2. BGE 可作为 RAGAS Evaluator Embeddings
3. 4 个指标（faithfulness / answer_relevancy / context_precision / context_recall）都能正常打分

运行：
    cd backend
    python -m evaluation.test_ragas
"""

import asyncio
import logging
import sys
import os

# 确保能 import services.*（脚本在 scripts/ 下，需上三级到 backend/）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from evaluation.ragas_config import (
    get_evaluator_llm,
    get_evaluator_embeddings,
    get_ragas_llm_wrapper,
    get_ragas_embeddings_wrapper,
    get_default_metrics,
)
from ragas.dataset_schema import SingleTurnSample

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ragas_test")


# ============================================================
# 样例数据：模拟日志问答场景
# ============================================================

SAMPLE = SingleTurnSample(
    # 用户问题
    user_input="数据库连接失败的可能原因是什么？",
    # 检索到的日志上下文（系统实际返回的 sources）
    retrieved_contexts=[
        "[ID:6789] order-service / ERROR / 2026-07-25 10:23:15 / "
        "Failed to get connection from pool: HikariPool-1 - Connection timeout after 30000ms",
        "[ID:6790] order-service / WARN / 2026-07-25 10:23:18 / "
        "HikariPool-1 - Pool stats: active=10, idle=0, waiting=5, total=10",
    ],
    # 系统生成的回答
    response=(
        "根据日志 [ID:6789] 显示，数据库连接失败的原因是连接池耗尽。"
        "HikariPool 在 30 秒内无法获取连接（timeout after 30000ms）。"
        "日志 [ID:6790] 进一步证实：连接池已满（active=10, idle=0, waiting=5），"
        "有 5 个请求在等待。建议增大连接池大小或排查慢查询。"
    ),
    # 标准答案（context_recall 需要）
    reference=(
        "数据库连接失败的原因是 HikariCP 连接池耗尽。"
        "ERROR 日志显示连接获取超时（30s），"
        "WARN 日志显示连接池已满（active=10, idle=0），有请求在等待。"
    ),
)


async def run_single_metric(metric, sample: SingleTurnSample):
    """跑单个指标，返回分数。metric 已在构造时注入 LLM/Embeddings。"""
    name = metric.name
    logger.info(f"  → 评估指标: {name}")
    try:
        # RAGAS 0.2 正确 API：single_turn_ascore
        score = await metric.single_turn_ascore(sample)
        logger.info(f"    ✓ {name} = {score}")
        return name, score, None
    except Exception as e:
        logger.error(f"    ✗ {name} 评估失败: {e}")
        return name, None, str(e)


async def main():
    logger.info("=" * 60)
    logger.info("RAGAS 环境验证")
    logger.info("=" * 60)

    # 1. 初始化 Evaluator LLM（DeepSeek）
    logger.info("[1/4] 初始化 Evaluator LLM (DeepSeek)...")
    try:
        llm = get_evaluator_llm()
        logger.info(f"    ✓ LLM 就绪: {llm.model_name}")
    except Exception as e:
        logger.error(f"    ✗ LLM 初始化失败: {e}")
        return False

    # 2. 初始化 Evaluator Embeddings（BGE）
    logger.info("[2/4] 初始化 Evaluator Embeddings (BGE)...")
    try:
        emb = get_evaluator_embeddings()
        # 快速测试
        vec = emb.embed_query("测试")
        logger.info(f"    ✓ Embeddings 就绪，维度={len(vec)}")
    except Exception as e:
        logger.error(f"    ✗ Embeddings 初始化失败: {e}")
        return False

    # 3. 组装 RAGAS Wrappers
    logger.info("[3/4] 组装 RAGAS Wrappers...")
    try:
        llm_wrapper = get_ragas_llm_wrapper()
        emb_wrapper = get_ragas_embeddings_wrapper()
        metrics = get_default_metrics()
        logger.info(f"    ✓ Wrappers 就绪，共 {len(metrics)} 个指标")
    except Exception as e:
        logger.error(f"    ✗ Wrappers 组装失败: {e}")
        return False

    # 4. 跑 4 个指标
    logger.info("[4/4] 跑 4 个核心指标（样例数据）...")
    results = []
    for metric in metrics:
        name, score, err = await run_single_metric(metric, SAMPLE)
        results.append((name, score, err))

    # 汇总
    logger.info("")
    logger.info("=" * 60)
    logger.info("评估结果汇总")
    logger.info("=" * 60)
    all_ok = True
    for name, score, err in results:
        if err:
            logger.info(f"  {name:25s}  ❌ 失败: {err}")
            all_ok = False
        else:
            logger.info(f"  {name:25s}  ✅ {score}")
    logger.info("=" * 60)

    if all_ok:
        logger.info("✅ RAGAS 环境验证通过，评估框架可运行")
    else:
        logger.info("❌ 部分指标失败，请检查日志")
    return all_ok


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
