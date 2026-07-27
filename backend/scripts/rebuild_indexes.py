"""
索引补建脚本 —— 给"入库但未向量化"的日志补建 Qdrant 向量索引和 BM25 索引。

适用场景：
    上传日志时未勾选「入库后向量化」，事后想补建索引让日志可被检索。

执行逻辑：
    1. 增量向量化：读取 batch_vectorize 的检查点，只处理 last_log_id 之后的新日志，
       不会重复处理已向量化的旧日志。
    2. 重建 BM25 索引：从 DB 全量加载日志重建（BM25 索引文件不会自动同步新数据）。

用法：
    cd backend
    venv/Scripts/python.exe scripts/rebuild_indexes.py

可选参数：
    --rebuild-vector   重建 Qdrant Collection（清空旧向量后全量重做，慎用）
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def rebuild_vector_index(rebuild: bool = False):
    """增量向量化（或全量重建）"""
    from scripts.batch_vectorize import batch_vectorize

    logger.info("=" * 60)
    logger.info("🚀 Step 1: 向量索引补建")
    logger.info("=" * 60)

    t0 = time.time()
    batch_vectorize(
        batch_size=100,
        vector_batch_size=20,
        resume=not rebuild,   # rebuild=True 时忽略检查点全量重做
        rebuild=rebuild,
    )
    logger.info(f"✅ 向量索引补建完成，耗时 {time.time() - t0:.1f}s")


def rebuild_bm25_index():
    """从 DB 全量重建 BM25 索引"""
    from core.database import SessionLocal
    from models.log import Log
    import services.bm25_retriever as bm25_module
    from services.bm25_retriever import get_bm25_retriever

    logger.info("=" * 60)
    logger.info("🔨 Step 2: BM25 索引重建")
    logger.info("=" * 60)

    t0 = time.time()
    # 清除全局单例，强制从最新 DB 数据重建
    # （get_bm25_retriever 在单例已存在时会直接返回旧实例，不会重建）
    bm25_module._bm25_retriever = None

    with SessionLocal() as sess:
        all_logs = sess.query(Log).order_by(Log.id).all()

    corpus = [{
        "log_id": lg.id,
        "level": lg.level,
        "service": lg.service,
        "timestamp": lg.timestamp,
        "message": lg.message,
        "chunk_text": lg.message,
        "source": lg.service,
    } for lg in all_logs]

    get_bm25_retriever(corpus=corpus, cache_path="./bm25_index.pkl")
    logger.info(f"✅ BM25 索引重建完成: {len(corpus)} 条文档，耗时 {time.time() - t0:.1f}s")


def main():
    parser = argparse.ArgumentParser(description="补建向量索引和 BM25 索引")
    parser.add_argument(
        "--rebuild-vector", action="store_true",
        help="重建 Qdrant Collection（清空旧向量后全量重做，慎用）"
    )
    parser.add_argument(
        "--skip-vector", action="store_true",
        help="跳过向量索引补建，只重建 BM25"
    )
    args = parser.parse_args()

    if not args.skip_vector:
        rebuild_vector_index(rebuild=args.rebuild_vector)
    else:
        logger.info("⏭️ 已跳过向量索引补建")

    rebuild_bm25_index()

    logger.info("=" * 60)
    logger.info("🎉 索引补建全部完成")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
