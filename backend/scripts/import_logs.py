"""
日志批量入库脚本
将清洗后的 logs_cleaned.csv 批量导入 SQLite 数据库
"""

import sys
import os
from pathlib import Path
from typing import Dict, List

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from datetime import datetime
import logging
from tqdm import tqdm
from sqlalchemy import func  # 添加这行

from core.database import SessionLocal
from models.log import Log

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============ 配置 ============
CSV_PATH = Path(__file__).parent.parent / "data" / "logs_cleaned.csv"
BATCH_SIZE = 500


# ============ 数据清洗函数 ============
def parse_timestamp(ts_str) -> datetime:
    """解析时间戳字符串为 datetime 对象"""
    if pd.isna(ts_str) or ts_str == "":
        return datetime.now()
    
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S%z",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(str(ts_str).strip(), fmt)
        except ValueError:
            continue
    
    logger.warning(f"无法解析时间戳: {ts_str}，使用当前时间代替")
    return datetime.now()


def clean_message(msg) -> str:
    """清洗 message 字段"""
    if pd.isna(msg) or msg is None:
        return ""
    return str(msg).strip()


# ============ 获取 Log 模型字段 ============
def get_log_fields():
    """获取 Log 模型的所有字段名（排除自动生成字段）"""
    all_fields = [c.name for c in Log.__table__.columns]
    # id 和 created_at 是自动生成的，不需要从 CSV 导入
    excluded = ['id', 'created_at']
    return [f for f in all_fields if f not in excluded]


# ============ 主导入函数 ============
def import_logs(csv_path: Path = CSV_PATH, batch_size: int = BATCH_SIZE):
    """从 CSV 文件批量导入日志到数据库（保留原命令行入口用）"""

    logger.info(f"开始导入日志: {csv_path}")

    # 1. 检查文件是否存在
    if not csv_path.exists():
        logger.error(f"CSV 文件不存在: {csv_path}")
        return False

    # 2. 读取 CSV
    try:
        df = pd.read_csv(csv_path, encoding="utf-8")
        logger.info(f"成功读取 {len(df)} 条日志")
        logger.info(f"CSV 列: {df.columns.tolist()}")
    except Exception as e:
        logger.error(f"读取 CSV 失败: {e}")
        return False

    # 3. 数据清洗（简化版，仅做基本规范化；严格校验请走 LogParser + LogCleaner）
    logger.info("开始清洗数据...")
    df['timestamp'] = df['timestamp'].apply(parse_timestamp)
    df['level'] = df['level'].astype(str).str.strip().str.upper()
    df['message'] = df['message'].apply(clean_message)

    # 处理 service 字段
    if 'service' in df.columns:
        df['service'] = df['service'].astype(str).str.strip().fillna('default')
    else:
        df['service'] = 'default'

    # 处理 ip 字段
    if 'ip' in df.columns:
        df['ip'] = df['ip'].fillna('0.0.0.0')
    else:
        df['ip'] = '0.0.0.0'

    # 处理 trace_id 字段
    if 'trace_id' in df.columns:
        df['trace_id'] = df['trace_id'].fillna('')
    else:
        df['trace_id'] = ''

    # 填充空值
    df['level'] = df['level'].fillna('INFO')
    df['service'] = df['service'].fillna('default')

    # 4. 转成 dict 列表，交给统一入库函数
    records = df.to_dict(orient='records')
    inserted, skipped = bulk_insert_logs(records, batch_size=batch_size)

    show_stats()
    return True


def bulk_insert_logs(logs: List[Dict], batch_size: int = 500) -> tuple:
    """
    将清洗后的日志 dict 列表批量插入数据库（供 ingest_service 调用）。

    输入要求：
    - logs: 已经过 LogParser + LogCleaner 处理的 dict 列表
    - 每个 dict 应包含: timestamp(datetime 或 str), level, service, message
    - 可选字段: ip, trace_id

    返回:
        (inserted_count, skipped_count)
    """
    if not logs:
        logger.info("无日志可导入")
        return 0, 0

    logger.info(f"开始批量导入 {len(logs)} 条日志...")

    # 1. 统一字段类型 + 处理 timestamp
    normalized = []
    for row in logs:
        item = dict(row)
        # timestamp 转 datetime
        ts = item.get('timestamp')
        if isinstance(ts, str):
            item['timestamp'] = parse_timestamp(ts)
        elif ts is None:
            item['timestamp'] = datetime.now()
        # 字符串字段兜底
        item['level'] = str(item.get('level', 'INFO')).upper()
        item['service'] = str(item.get('service', 'default')) or 'default'
        item['message'] = clean_message(item.get('message', ''))
        item['ip'] = str(item.get('ip', '0.0.0.0')) or '0.0.0.0'
        item['trace_id'] = str(item.get('trace_id', '')) or ''
        normalized.append(item)

    # 2. 数据库去重（基于 message + service）
    logger.info("检查数据库中已有日志...")
    db = SessionLocal()
    try:
        existing = db.query(Log.message, Log.service).all()
        existing_set = {(msg, svc) for msg, svc in existing}
        logger.info(f"数据库中已有 {len(existing_set)} 条日志记录")
    finally:
        db.close()

    new_records = []
    skipped = 0
    for row in normalized:
        key = (row['message'], row['service'])
        if key in existing_set:
            skipped += 1
            continue
        new_records.append(row)
        existing_set.add(key)  # 防止本批内重复

    if not new_records:
        logger.info("所有日志已存在，无需导入")
        return 0, skipped

    # 3. 批量入库
    log_fields = get_log_fields()
    inserted = 0

    with tqdm(total=len(new_records), desc="导入进度", unit="条") as pbar:
        for i in range(0, len(new_records), batch_size):
            batch = new_records[i:i + batch_size]

            logs_to_insert = []
            for row in batch:
                # 只保留 Log 模型存在的字段
                filtered = {k: v for k, v in row.items() if k in log_fields}
                try:
                    logs_to_insert.append(Log(**filtered))
                except Exception as e:
                    logger.error(f"创建 Log 对象失败: {e}, 数据: {filtered}")
                    continue

            if not logs_to_insert:
                continue

            db = SessionLocal()
            try:
                db.bulk_save_objects(logs_to_insert)
                db.commit()
                inserted += len(logs_to_insert)
                pbar.update(len(logs_to_insert))
            except Exception as e:
                db.rollback()
                logger.error(f"批量插入失败: {e}")
                logger.info("切换到逐条插入模式...")
                for log_obj in logs_to_insert:
                    try:
                        db.add(log_obj)
                        db.commit()
                        inserted += 1
                        pbar.update(1)
                    except Exception as e2:
                        db.rollback()
                        logger.error(f"单条插入失败: {e2}")
            finally:
                db.close()

    logger.info(f"导入完成: 成功 {inserted} 条, 跳过重复 {skipped} 条")
    return inserted, skipped


# ============ 统计信息函数（修复版） ============
def show_stats():
    """显示当前数据库中的日志统计信息"""
    db = SessionLocal()
    try:
        total = db.query(Log).count()
        # 使用 sqlalchemy.func 而不是 db.func
        levels = db.query(Log.level, func.count()).group_by(Log.level).all()
        services = db.query(Log.service, func.count()).group_by(Log.service).limit(10).all()
        
        logger.info("=" * 50)
        logger.info(f"📊 数据库日志统计")
        logger.info(f"   总日志数: {total}")
        logger.info(f"   日志级别分布:")
        for level, count in levels:
            logger.info(f"     {level}: {count}")
        logger.info(f"   服务分布 (Top 10):")
        for service, count in services:
            logger.info(f"     {service}: {count}")
        logger.info("=" * 50)
    except Exception as e:
        logger.error(f"统计查询失败: {e}")
    finally:
        db.close()


# ============ 清空日志表 ============
def clear_logs(confirm: bool = False):
    """清空 logs 表"""
    if not confirm:
        logger.warning("⚠️ 需要确认: clear_logs(confirm=True) 才会执行")
        return False
    
    db = SessionLocal()
    try:
        count = db.query(Log).count()
        db.query(Log).delete()
        db.commit()
        logger.info(f"已清空 logs 表，删除了 {count} 条记录")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"清空失败: {e}")
        return False
    finally:
        db.close()


# ============ 命令行入口 ============
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="日志批量入库工具")
    parser.add_argument(
        "--csv", 
        type=str, 
        default=str(CSV_PATH),
        help=f"CSV 文件路径 (默认: {CSV_PATH})"
    )
    parser.add_argument(
        "--batch-size", 
        type=int, 
        default=500,
        help="每批插入数量 (默认: 500)"
    )
    parser.add_argument(
        "--stats", 
        action="store_true",
        help="仅显示数据库统计信息，不执行导入"
    )
    parser.add_argument(
        "--clear", 
        action="store_true",
        help="清空 logs 表（危险操作，需要二次确认）"
    )
    
    args = parser.parse_args()
    
    if args.stats:
        show_stats()
        sys.exit(0)
    
    if args.clear:
        print("⚠️ 即将清空 logs 表，请输入 y 确认: ", end="")
        confirm = input().strip().lower()
        if confirm == "y":
            clear_logs(confirm=True)
        else:
            print("操作已取消")
        sys.exit(0)
    
    success = import_logs(
        csv_path=Path(args.csv),
        batch_size=args.batch_size
    )
    
    sys.exit(0 if success else 1)
    """
    使用方法
    1. 基础导入
    bash
        cd backend
        python scripts/import_logs.py
    2. 指定 CSV 文件
    bash
        python scripts/import_logs.py --csv /path/to/logs_cleaned.csv
    3. 调整批次大小
    bash
        python scripts/import_logs.py --batch-size 1000
    4. 查看统计信息
    bash
        python scripts/import_logs.py --stats
    5. 清空日志表（危险操作）
    bash
        python scripts/import_logs.py --clear
        # 会提示输入 y 确认
    """