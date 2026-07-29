"""
清空所有日志数据：SQLite logs 表 + Qdrant Collection + BM25 索引 + checkpoints + 中间 CSV。

用法：
    cd backend
    venv/Scripts/python.exe scripts/clear_all_data.py
"""
import os
import sys
import glob

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 加载 .env（让真实 Qdrant Cloud 配置生效）
from dotenv import load_dotenv
load_dotenv()
# 兜底：如果 .env 没配置，至少能跑 SQLite 清理
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "fake")

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def clear_sqlite():
    """清空 logs 表 + 重置自增 ID + 回收磁盘空间

    策略：DROP TABLE + 重建（比 DELETE 550 万条快得多，且自动重置自增序列）
    保留 users / audit_logs / qa_history 等其他表
    """
    from core.database import SessionLocal, engine, Base
    from models.log import Log
    from sqlalchemy import text
    import time

    db = SessionLocal()
    try:
        count = db.query(Log).count()
        logger.info(f"清理前: SQLite logs 表有 {count:,} 条记录")
    finally:
        db.close()

    if count == 0:
        logger.info("logs 表已为空，跳过")
        return

    # 1. DROP TABLE logs（瞬间完成，比 DELETE 快几个数量级）
    logger.info("正在 DROP TABLE logs...")
    t0 = time.time()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS logs"))
    logger.info(f"DROP 完成，耗时 {time.time() - t0:.2f}s")

    # 2. 重建 logs 表（按 ORM 模型定义）
    logger.info("正在重建 logs 表...")
    Log.__table__.create(engine, checkfirst=True)
    logger.info("logs 表已重建，自增 ID 从 1 开始")

    # 3. VACUUM 回收磁盘空间（DROP 后 .db 文件大小不变，必须 VACUUM）
    logger.info("正在 VACUUM 回收磁盘空间（可能需要几十秒）...")
    t0 = time.time()
    # VACUUM 不能在事务里执行，用裸 connection
    with engine.connect() as conn:
        conn.execute(text("VACUUM"))
        conn.commit()
    logger.info(f"VACUUM 完成，耗时 {time.time() - t0:.2f}s")

    db = SessionLocal()
    try:
        count = db.query(Log).count()
        logger.info(f"清理后: SQLite logs 表有 {count} 条记录")
    finally:
        db.close()


def clear_qdrant():
    """删除 Qdrant Collection"""
    try:
        from services.qdrant_client import get_qdrant_client
        qdrant = get_qdrant_client()
        if qdrant.health_check():
            info = qdrant.get_collection_info()
            logger.info(f"清理前: Qdrant 有 {info.get('vectors_count', 0):,} 个向量")
            qdrant.delete_collection()
            logger.info("Qdrant Collection 已删除")
        else:
            logger.warning("Qdrant 连接失败，跳过（可能 .env 未配置或服务未启动）")
    except Exception as e:
        logger.warning(f"清理 Qdrant 失败（不影响其他清理）: {e}")


def clear_files():
    """删除 BM25 索引 + 向量化检查点 + ingest 检查点 + 中间 CSV"""
    targets = [
        "./bm25_index.pkl",
        "./vectorize_checkpoint.json",
    ]
    # ingest 流水线的 checkpoint_*.json
    targets += glob.glob("./data/checkpoint_*.json")
    # 中间 CSV（转换产生 / 生成产生）
    targets += glob.glob("./data/converted_*.csv")
    targets += glob.glob("./data/logs_ingest_*.csv")

    for path in targets:
        if os.path.exists(path):
            os.remove(path)
            logger.info(f"已删除: {path}")
        else:
            logger.debug(f"不存在: {path}")


def main():
    logger.info("=" * 60)
    logger.info("开始清理所有日志数据")
    logger.info("=" * 60)

    clear_sqlite()
    clear_qdrant()
    clear_files()

    logger.info("=" * 60)
    logger.info("清理完成。可重新上传日志文件。")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
