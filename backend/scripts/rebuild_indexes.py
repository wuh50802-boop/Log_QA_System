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
    from services.batch_vectorize import batch_vectorize

    logger.info("=" * 60)
    logger.info("🚀 Step 1: 向量索引补建")
    logger.info("=" * 60)

    t0 = time.time()
    batch_vectorize(
        batch_size=1024,      # DB 读取批次（与本地/云端无关，看 DB IO）
        vector_batch_size=512,  # 本地部署无网络瓶颈，加大减少 upsert 请求次数
        resume=not rebuild,   # rebuild=True 时忽略检查点全量重做
        rebuild=rebuild,
    )
    logger.info(f"✅ 向量索引补建完成，耗时 {time.time() - t0:.1f}s")


def rebuild_bm25_index():
    """从 DB 全量重建 BM25 索引（流式加载，避免一次性加载千万级 ORM 对象）"""
    from sqlalchemy import select, text
    from core.database import SessionLocal, engine
    import services.bm25_retriever as bm25_module
    from services.bm25_retriever import get_bm25_retriever

    logger.info("=" * 60)
    logger.info("🔨 Step 2: BM25 索引重建")
    logger.info("=" * 60)

    t0 = time.time()
    # 清除全局单例，强制从最新 DB 数据重建
    # （get_bm25_retriever 在单例已存在时会直接返回旧实例，不会重建）
    bm25_module._bm25_retriever = None

    # 先统计总数用于进度显示
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM logs")).scalar()
    logger.info(f"📊 待索引日志数: {total}")

    # 流式加载：用 Core select 只取必要字段，yield_per 避免 ORM 一次性物化全部对象
    # 直接用 raw connection 的 fetchmany 拿 dict，比 ORM 快 5-10 倍
    corpus = []
    processed = 0
    batch_size = 50000
    with engine.connect() as conn:
        # SQLite 下 ORDER BY id 保证顺序稳定；只取 BM25 需要的 5 个字段
        result = conn.execution_options(stream_results=True).execute(
            text("SELECT id, level, service, timestamp, message FROM logs ORDER BY id")
        )
        while True:
            rows = result.fetchmany(batch_size)
            if not rows:
                break
            for row in rows:
                corpus.append({
                    "log_id": row[0],
                    "level": row[1],
                    "service": row[2],
                    "timestamp": str(row[3]),
                    "message": row[4],
                    "chunk_text": row[4],
                    "source": row[2],
                })
            processed += len(rows)
            elapsed = time.time() - t0
            speed = processed / elapsed if elapsed > 0 else 0
            logger.info(
                f"📥 加载进度: {processed}/{total} ({processed/total*100:.1f}%) | "
                f"速度: {speed:.0f} rows/s"
            )

    logger.info(f"📦 加载完成：{len(corpus)} 条原始日志")

    # ---- 模板去重：相同结构的日志只保留一条，避免 BM25Okapi 内存爆炸 ----
    # rank_bm25 是纯 Python 实现，对 1033 万文档会 MemoryError（需 8GB+ 内存）
    # HDFS 日志高度重复，模板去重后通常只剩几万条独立模板
    from services.batch_vectorize import normalize_template

    logger.info("🔧 开始模板去重...")
    dedup_start = time.time()
    seen_templates = {}  # template -> corpus item
    for doc in corpus:
        msg = doc.get('message', '') or doc.get('chunk_text', '')
        template = normalize_template(msg)
        if template not in seen_templates:
            seen_templates[template] = doc
    dedup_corpus = list(seen_templates.values())
    dedup_ratio = (1 - len(dedup_corpus) / len(corpus)) * 100
    logger.info(
        f"✅ 模板去重完成: {len(corpus)} → {len(dedup_corpus)} 条 "
        f"(去重率 {dedup_ratio:.1f}%)，耗时 {time.time() - dedup_start:.1f}s"
    )

    # 释放原始语料库内存
    del corpus, seen_templates

    logger.info(f"📦 开始构建 BM25 索引（{len(dedup_corpus)} 条模板文档）...")
    original_count = total  # 原始日志数，从外部变量保留
    get_bm25_retriever(corpus=dedup_corpus, cache_path="./bm25_index.pkl")
    logger.info(
        f"✅ BM25 索引重建完成: 原始 {original_count} 条 → "
        f"模板 {len(dedup_corpus)} 条，总耗时 {time.time() - t0:.1f}s"
    )


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
