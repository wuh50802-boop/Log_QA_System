import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import time
import uuid
import json
from typing import List, Dict, Any, Optional
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
def save_checkpoint(processed_logs: int, total_logs: int, offset: int, last_log_id: Optional[int] = None):
    """保存进度检查点"""
    try:
        checkpoint = {
            'processed_logs': processed_logs,
            'total_logs': total_logs,
            'offset': offset,
            'last_log_id': last_log_id,
            'timestamp': datetime.now().isoformat()
        }
        with open(CHECKPOINT_FILE, 'w') as f:
            json.dump(checkpoint, f, indent=2)
        logger.debug(f"💾 检查点已保存: {processed_logs}/{total_logs}")
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
def fetch_logs_from_db(offset: int, limit: int) -> List[Dict[str, Any]]:
    """从数据库获取日志数据"""
    session = SessionLocal()
    try:
        query = session.query(Log).order_by(Log.id).limit(limit).offset(offset)
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
    except Exception as e:
        logger.error(f"从数据库获取日志失败: {e}")
        raise
    finally:
        session.close()


def process_batch(logs: List[Dict[str, Any]], chunker: LogChunker, embedder) -> List[PointStruct]:
    """
    处理一批日志：分块 → 向量化 → 构造 PointStruct
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
        
        for chunk in chunks:
            all_texts.append(chunk.text)
            all_metadatas.append({
                "log_id": log["id"],
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
    
    # 构造 PointStruct
    for i, (vector, metadata) in enumerate(zip(vectors, all_metadatas)):
        point_id = str(uuid.uuid4())
        points.append(PointStruct(
            id=point_id,
            vector=vector.tolist(),
            payload=metadata
        ))
    
    return points


def batch_vectorize(
    batch_size: int = 100,
    vector_batch_size: int = 20,
    max_logs: int = None,
    resume: bool = True,
    rebuild: bool = False,
):
    """
    批量向量化主函数（支持断点续传和重建索引）
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
    
    # 统计总日志数
    session = SessionLocal()
    try:
        total_logs = session.query(Log).count()
    finally:
        session.close()
    
    if max_logs and max_logs < total_logs:
        total_logs = max_logs
    
    # 加载检查点（如果 rebuild 则忽略检查点）
    start_offset = 0
    processed_logs = 0
    checkpoint = load_checkpoint() if resume and not rebuild else None
    
    if checkpoint:
        logger.info(f"📌 发现上次进度: {checkpoint['processed_logs']}/{checkpoint['total_logs']}")
        start_offset = checkpoint.get('offset', 0)
        processed_logs = checkpoint.get('processed_logs', 0)
        logger.info(f"🔄 从 offset {start_offset} 继续...")
    
    logger.info(f"📊 总日志数: {total_logs}")
    
    if processed_logs >= total_logs:
        logger.info("✅ 所有日志已处理完成")
        clear_checkpoint()
        return
    
    offset = start_offset
    start_time = time.time()
    last_checkpoint_time = time.time()
    total_points = 0
    
    try:
        while True:
            if processed_logs >= total_logs:
                break
            
            # 计算本次批次大小
            remaining = total_logs - processed_logs
            current_batch_size = min(batch_size, remaining)
            
            # 获取日志
            logs = fetch_logs_from_db(offset, current_batch_size)
            if not logs:
                break
            
            # 处理批次
            points = process_batch(logs, chunker, embedder)
            
            # 入库
            if points:
                success = qdrant.upsert_vectors(points, batch_size=vector_batch_size)
                if not success:
                    logger.error(f"❌ 入库失败 at offset {offset}")
                    save_checkpoint(processed_logs, total_logs, offset)
                    break
                total_points += len(points)
            
            processed_logs += len(logs)
            offset += len(logs)
            
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
            
            # 每 30 秒保存一次检查点
            if time.time() - last_checkpoint_time > 30:
                last_log_id = logs[-1]["id"] if logs else None
                save_checkpoint(processed_logs, total_logs, offset, last_log_id)
                last_checkpoint_time = time.time()
    
    except KeyboardInterrupt:
        logger.warning("⏹️ 用户中断")
        save_checkpoint(processed_logs, total_logs, offset)
        logger.info("💾 进度已保存，下次运行将自动继续")
        return
    
    # 最终统计
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("🎉 向量化完成!")
    logger.info(f"📊 处理日志: {processed_logs} 条")
    logger.info(f"📦 生成向量: {total_points} 个")
    logger.info(f"⏱️ 总耗时: {elapsed:.2f} 秒")
    logger.info(f"📈 平均速度: {processed_logs/elapsed:.1f} logs/s")
    
    # 验证入库结果
    final_count = qdrant.count()
    logger.info(f"📦 Qdrant 向量总数: {final_count}")
    
    # 显示索引状态
    info = qdrant.get_collection_info()
    if info:
        logger.info(f"📊 索引状态: {info.get('indexed_vectors_count', 0)}/{info.get('vectors_count', 0)} 已索引")
    logger.info("=" * 60)
    
    # 清除检查点
    clear_checkpoint()


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