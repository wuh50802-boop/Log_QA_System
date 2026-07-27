import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import time
import json
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.embedder import get_embedder
from services.chunker import LogChunker
from services.qdrant_client import get_qdrant_client
from models import Log
from qdrant_client.http.models import PointStruct

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 数据库配置
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)

# 检查点文件
CHECKPOINT_FILE = "vectorize_checkpoint.json"


# ============ 检查点管理 ============
def save_checkpoint(processed_logs: int, total_logs: int, last_log_id: int, completed: bool = False):
    """
    保存进度检查点（基于最后处理完的日志 ID，避免 OFFSET 漂移）

    Args:
        processed_logs: 已处理日志数（仅用于进度展示）
        total_logs: 总日志数
        last_log_id: 最后一条已处理日志的 ID，下次从此 ID 之后继续读取
        completed: 本次任务是否已完成。
            True  → 保留检查点作为"已处理基线"，下次增量向量化时只处理 last_log_id 之后的新日志。
            False → 任务中断，下次 resume 时从 last_log_id 继续。
    """
    try:
        checkpoint = {
            'processed_logs': processed_logs,
            'total_logs': total_logs,
            'last_log_id': last_log_id,
            'completed': completed,
            'timestamp': datetime.now().isoformat()
        }
        with open(CHECKPOINT_FILE, 'w') as f:
            json.dump(checkpoint, f, indent=2)
        logger.debug(f"💾 检查点已保存: {processed_logs}/{total_logs} (last_log_id={last_log_id}, completed={completed})")
    except Exception as e:
        logger.warning(f"保存检查点失败: {e}")


def load_checkpoint() -> Optional[Dict]:
    """加载上次进度"""
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载检查点失败: {e}")
    return None


def clear_checkpoint():
    """清除检查点（任务完成后）"""
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        logger.info("🗑️ 检查点已清除")


# ============ 核心函数 ============
def fetch_logs_from_db(last_log_id: int, limit: int) -> List[Dict[str, Any]]:
    """
    从数据库获取日志数据（基于 ID 游标分页，避免 OFFSET 越来越慢）

    Args:
        last_log_id: 上一批最后一条日志的 ID；传 0 表示从头开始
        limit: 最多读取多少条
    """
    # 用 with 上下文管理器确保 session 在函数返回时被关闭，
    # 避免长时间循环里连接慢慢占满。
    with SessionLocal() as session:
        query = session.query(Log).order_by(Log.id)
        if last_log_id > 0:
            query = query.filter(Log.id > last_log_id)
        query = query.limit(limit)
        logs = query.all()

        result = []
        for log in logs:
            # ========== 修复 source 字段 ==========
            source = "unknown"
            # 优先使用已存在的 source
            if hasattr(log, "source") and log.source:
                source = log.source
            else:
                # 尝试从 service 字段提取
                if hasattr(log, "service") and log.service:
                    source = log.service
                # 尝试从 message 中提取（如 "payment-service: Connection timeout"）
                elif log.message and ":" in log.message:
                    parts = log.message.split(":", 1)
                    if len(parts) >= 2 and len(parts[0]) < 30:
                        source = parts[0].strip()

            result.append({
                "id": log.id,
                "timestamp": log.timestamp,
                "level": log.level,
                "service": log.service,
                "message": log.message,
                "source": source,
                "raw": log.raw if hasattr(log, "raw") else log.message,
            })
        return result


def process_batch(logs: List[Dict[str, Any]], chunker: LogChunker, embedder) -> List[PointStruct]:
    """
    处理一批日志：分块 → 向量化 → 构造 PointStruct

    point_id 用 "log_{log_id}_chunk_{chunk_idx}" 的确定性格式，
    确保同一日志重复向量化时 Qdrant upsert 会覆盖旧向量而非追加新向量。
    """
    if not logs:
        return []

    points = []
    all_texts = []
    all_metadatas = []

    for log in logs:
        chunks = chunker.chunk_text(
            text=log["message"],
            metadata={
                "log_id": log["id"],
                "level": log["level"],
                "service": log["service"],
                "timestamp": str(log["timestamp"]),
                "source": log.get("source", "unknown"),
            }
        )

        # 同一条日志的多个 chunk 用独立的 chunk_idx 编号
        for chunk_idx, chunk in enumerate(chunks):
            all_texts.append(chunk.text)
            all_metadatas.append({
                "log_id": log["id"],
                "chunk_idx": chunk_idx,
                "chunk_text": chunk.text,
                "level": log["level"],
                "service": log["service"],
                "timestamp": str(log["timestamp"]),
                "source": log.get("source", "unknown"),
            })

    if not all_texts:
        return []

    # 批量向量化
    vectors = embedder.encode(all_texts)

    # 构造 PointStruct：确定性 point_id = log_{log_id}_chunk_{chunk_idx}
    for vector, metadata in zip(vectors, all_metadatas):
        log_id = metadata["log_id"]
        chunk_idx = metadata["chunk_idx"]
        point_id = f"log_{log_id}_chunk_{chunk_idx}"
        points.append(PointStruct(
            id=point_id,
            vector=vector.tolist(),
            payload=metadata
        ))

    return points


def batch_vectorize(
    batch_size: int = 100,
    vector_batch_size: int = 100,
    max_logs: int = None,
    resume: bool = True,
    rebuild: bool = False,
    progress_callback: Optional[Callable[[int, int], None]] = None,
):
    """
    批量向量化主函数（支持断点续传和重建索引）

    Args:
        progress_callback: 可选回调，签名 (processed, total)。
            每处理完一批日志后调用一次，用于上报进度。
    """
    logger.info("=" * 60)
    logger.info("🚀 启动批量向量化")
    logger.info(f"批次大小: {batch_size}, 向量批次: {vector_batch_size}")
    if rebuild:
        logger.info("⚠️  将重建 Collection（删除旧数据并创建新索引）")
    logger.info("=" * 60)
    
    # 初始化组件
    chunker = LogChunker(chunk_size=256, overlap=50, strategy="sentence")
    embedder = get_embedder()
    qdrant = get_qdrant_client()
    
    # 检查 Qdrant 连接
    if not qdrant.health_check():
        logger.error("❌ Qdrant 连接失败，请检查配置")
        return
    
    # 创建或重建 Collection（含索引配置）
    try:
        qdrant.create_collection(recreate=rebuild)
    except Exception as e:
        logger.error(f"❌ Collection 创建失败: {e}")
        return

    # 统计 DB 中日志总数
    with SessionLocal() as session:
        db_total_logs = session.query(Log).count()
        max_db_log_id = session.query(Log.id).order_by(Log.id.desc()).first()
        max_db_log_id = max_db_log_id[0] if max_db_log_id else 0

    # 限制处理数（max_logs 用于测试时限制总量）
    total_logs = db_total_logs if not max_logs else min(max_logs, db_total_logs)

    # 加载检查点（如果 rebuild 则忽略检查点）
    # 检查点用 last_log_id 作为游标，避免 OFFSET 在日志被删/新增时漂移导致重复或漏处理。
    # 增量模式：上次任务完成（completed=True）时保留检查点，下次只处理 last_log_id 之后的新日志。
    last_log_id = 0
    processed_logs = 0
    checkpoint = load_checkpoint() if resume and not rebuild else None

    if checkpoint:
        last_log_id = checkpoint.get('last_log_id', 0)
        completed = checkpoint.get('completed', False)

        if completed:
            # 上次任务已完成 → 增量模式：只处理 last_log_id 之后的新日志
            new_count = 0
            if max_db_log_id > last_log_id:
                with SessionLocal() as session:
                    new_count = session.query(Log).filter(Log.id > last_log_id).count()
            if new_count == 0:
                logger.info(f"✅ 无新增日志（DB 最大 id={max_db_log_id}，已处理到 last_log_id={last_log_id}），跳过向量化")
                return
            logger.info(f"📌 增量模式：上次已完成到 log_id={last_log_id}，本次新增 {new_count} 条待处理")
            # processed_logs 从 0 开始计数（只算本次新增的）
            processed_logs = 0
            total_logs = new_count
        else:
            # 上次任务中断 → 续传模式：从 last_log_id 继续
            logger.info(f"📌 续传模式：上次中断于 log_id={last_log_id}，从该 ID 之后继续")
            # processed_logs 从检查点继续（用于进度展示）
            processed_logs = checkpoint.get('processed_logs', 0)
    else:
        logger.info(f"🆕 首次运行或未找到检查点，从 log_id=0 开始全量向量化")

    logger.info(f"📊 本次待处理日志数: {total_logs}")

    if total_logs == 0 or processed_logs >= total_logs:
        logger.info("✅ 无需处理")
        return
    
    start_time = time.time()
    total_points = 0

    # ===== 批量导入优化：临时关闭后台索引构建 =====
    # 设一个极大的 indexing_threshold，让 Qdrant 在导入阶段不构建 HNSW 索引，
    # 避免每写一批就触发一次后台优化拖慢写入速度；导入完成后再恢复阈值触发一次性索引构建。
    logger.info("🔧 批量导入模式：临时关闭后台索引构建（indexing_threshold=10^9）")
    qdrant.update_indexing_threshold(10**9)

    try:
        while True:
            if processed_logs >= total_logs:
                break

            # 计算本次批次大小
            remaining = total_logs - processed_logs
            current_batch_size = min(batch_size, remaining)

            # 获取日志（基于 ID 游标，避免 OFFSET 越来越慢）
            logs = fetch_logs_from_db(last_log_id, current_batch_size)
            if not logs:
                # 读到空批：可能是数据被删导致游标之后没有数据，正常退出
                logger.info("📭 未读取到新日志（游标之后无数据），结束导入")
                break

            # 处理批次：分片 + 向量化
            points = process_batch(logs, chunker, embedder)

            # 入库（批次级重试 + wait=False 异步写入以提升吞吐）
            if points:
                max_retries = 3
                upsert_ok = False
                for attempt in range(max_retries):
                    try:
                        # wait=False：不等服务端逐批确认，整体吞吐更高
                        qdrant.upsert_vectors(points, batch_size=vector_batch_size, wait=False)
                        upsert_ok = True
                        break
                    except Exception as upsert_err:
                        if attempt == max_retries - 1:
                            logger.error(f"❌ 入库失败，重试 {max_retries} 次仍失败: {upsert_err}")
                            # 保存当前进度后中止，避免丢失已完成的批次
                            save_checkpoint(processed_logs, total_logs, last_log_id)
                            raise
                        wait_time = 2 ** attempt
                        logger.warning(
                            f"⚠️ 入库失败，{wait_time}s 后重试 ({attempt+1}/{max_retries}): {upsert_err}"
                        )
                        time.sleep(wait_time)
                if upsert_ok:
                    total_points += len(points)

            processed_logs += len(logs)
            # 用最后一条日志的 ID 作为下一批的游标（不再用 offset）
            last_log_id = logs[-1]["id"]

            # 每批都保存检查点：程序崩溃最多丢掉当前这一批，不会丢已完成的批次
            save_checkpoint(processed_logs, total_logs, last_log_id)

            # 进度显示
            elapsed = time.time() - start_time
            speed = processed_logs / elapsed if elapsed > 0 else 0
            progress = (processed_logs / total_logs) * 100 if total_logs > 0 else 0

            # 估算剩余时间
            eta_str = "未知"
            if speed > 0:
                remaining_sec = (total_logs - processed_logs) / speed
                if remaining_sec < 60:
                    eta_str = f"{remaining_sec:.0f}s"
                elif remaining_sec < 3600:
                    eta_str = f"{remaining_sec/60:.1f}m"
                else:
                    eta_str = f"{remaining_sec/3600:.1f}h"

            logger.info(
                f"📈 进度: {processed_logs}/{total_logs} ({progress:.1f}%) | "
                f"向量: {total_points} | "
                f"速度: {speed:.1f} logs/s | "
                f"预计剩余: {eta_str}"
            )

            # 上报进度给调用方
            if progress_callback is not None:
                try:
                    progress_callback(processed_logs, total_logs)
                except Exception as cb_err:
                    logger.warning(f"progress_callback 调用失败: {cb_err}")

    except KeyboardInterrupt:
        logger.warning("⏹️ 用户中断")
        save_checkpoint(processed_logs, total_logs, last_log_id)
        logger.info("💾 进度已保存，下次运行将自动从 last_log_id 继续")
        return

    # ===== 导入完成：恢复 indexing_threshold，触发后台索引构建并等待完成 =====
    logger.info("🔧 导入完成，恢复 indexing_threshold=10000，触发后台索引构建...")
    qdrant.update_indexing_threshold(10000)
    logger.info("⏳ 等待后台索引构建完成（最多等待 10 分钟）...")
    qdrant.wait_for_indexing(timeout=600)

    # 最终统计
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("🎉 向量化完成!")
    logger.info(f"📊 处理日志: {processed_logs} 条")
    logger.info(f"📦 生成向量: {total_points} 个")
    logger.info(f"⏱️ 总耗时: {elapsed:.2f} 秒")
    logger.info(f"📈 平均速度: {processed_logs/elapsed:.1f} logs/s")

    # 验证入库结果（count 会等待 pending 写入落盘）
    final_count = qdrant.count()
    logger.info(f"📦 Qdrant 向量总数: {final_count}")

    # 显示索引状态
    info = qdrant.get_collection_info()
    if info:
        logger.info(f"📊 索引状态: {info.get('indexed_vectors_count', 0)}/{info.get('vectors_count', 0)} 已索引")
    logger.info("=" * 60)

    # 保存"已完成"检查点（不清除），作为下次增量向量化的基线
    # 下次运行时检测到 completed=True，只处理 last_log_id 之后的新增日志
    save_checkpoint(
        processed_logs=processed_logs,
        total_logs=total_logs,
        last_log_id=last_log_id,
        completed=True,
    )
    logger.info(f"💾 已保存增量基线: last_log_id={last_log_id}（下次只处理新增日志）")


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="批量向量化日志到 Qdrant")
    parser.add_argument(
        "--batch-size", type=int, default=100,
        help="每批从数据库读取的日志数"
    )
    parser.add_argument(
        "--vector-batch", type=int, default=20,
        help="每批入库的向量数"
    )
    parser.add_argument(
        "--max-logs", type=int, default=None,
        help="最大处理日志数（默认全部）"
    )
    parser.add_argument(
        "--resume", action="store_true", default=True,
        help="从上次中断处继续"
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="忽略检查点，重新开始"
    )
    parser.add_argument(
        "--rebuild", action="store_true",
        help="删除旧 Collection 并重建（含所有字段索引）"
    )
    parser.add_argument(
        "--clear-checkpoint", action="store_true",
        help="清除检查点文件"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="干跑模式（只统计不插入）"
    )
    
    args = parser.parse_args()
    
    if args.clear_checkpoint:
        clear_checkpoint()
        logger.info("✅ 检查点已清除")
        return
    
    if args.dry_run:
        logger.info("🔍 DRY RUN MODE - 不会插入任何数据")
        session = SessionLocal()
        total = session.query(Log).count()
        session.close()
        logger.info(f"📊 将处理 {args.max_logs or total} 条日志")
        return
    
    batch_vectorize(
        batch_size=args.batch_size,
        vector_batch_size=args.vector_batch,
        max_logs=args.max_logs,
        resume=not args.no_resume,
        rebuild=args.rebuild,
    )


if __name__ == "__main__":
    main()