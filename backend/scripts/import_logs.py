"""
日志批量入库脚本
将清洗后的 logs_cleaned.csv 批量导入 SQLite 数据库
"""

import sys
import os
from pathlib import Path

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
    """从 CSV 文件批量导入日志到数据库"""
    
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
    
    # 3. 获取 Log 模型的有效字段
    log_fields = get_log_fields()
    logger.info(f"Log 模型可导入字段: {log_fields}")
    
    # 4. 检查必要字段
    required_fields = ['timestamp', 'level', 'message']
    missing = [f for f in required_fields if f not in df.columns]
    if missing:
        logger.error(f"CSV 缺少必要字段: {missing}")
        return False
    
    # 5. 数据清洗
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
    
    # 6. 过滤重复数据
    logger.info("检查数据库中已有日志...")
    db = SessionLocal()
    try:
        existing = db.query(Log.message, Log.service).all()
        existing_set = {(msg, svc) for msg, svc in existing}
        logger.info(f"数据库中已有 {len(existing_set)} 条日志记录")
    finally:
        db.close()
    
    # 去重
    df['_key'] = df.apply(lambda row: (row['message'], row['service']), axis=1)
    df_new = df[~df['_key'].isin(existing_set)]
    df_new = df_new.drop(columns=['_key'])
    
    duplicate_count = len(df) - len(df_new)
    if duplicate_count > 0:
        logger.info(f"发现 {duplicate_count} 条重复日志，已过滤")
    
    if len(df_new) == 0:
        logger.info("所有日志已存在，无需导入")
        return True
    
    # 7. 只保留 Log 模型存在的字段
    csv_columns = df_new.columns.tolist()
    usable_columns = [col for col in csv_columns if col in log_fields]
    
    # 确保所有必要字段都存在
    for field in ['timestamp', 'level', 'service', 'message']:
        if field not in usable_columns:
            usable_columns.append(field)
    
    logger.info(f"将导入字段: {usable_columns}")
    df_filtered = df_new[usable_columns].copy()
    
    # 8. 批量入库
    logger.info(f"开始批量导入 {len(df_filtered)} 条新日志...")
    
    records = df_filtered.to_dict(orient='records')
    inserted_count = 0
    
    with tqdm(total=len(records), desc="导入进度", unit="条") as pbar:
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            
            logs_to_insert = []
            for row in batch:
                try:
                    log = Log(**row)
                    logs_to_insert.append(log)
                except Exception as e:
                    logger.error(f"创建 Log 对象失败: {e}, 数据: {row}")
                    continue
            
            if not logs_to_insert:
                continue
            
            db = SessionLocal()
            try:
                db.bulk_save_objects(logs_to_insert)
                db.commit()
                inserted_count += len(logs_to_insert)
                pbar.update(len(logs_to_insert))
            except Exception as e:
                db.rollback()
                logger.error(f"批量插入失败: {e}")
                logger.info("切换到逐条插入模式...")
                for log_obj in logs_to_insert:
                    try:
                        db.add(log_obj)
                        db.commit()
                        inserted_count += 1
                        pbar.update(1)
                    except Exception as e2:
                        db.rollback()
                        logger.error(f"单条插入失败: {e2}")
            finally:
                db.close()
    
    # 9. 输出统计
    logger.info(f"✅ 导入完成: 成功导入 {inserted_count} 条日志")
    logger.info(f"   总日志数: {len(df)} 条")
    logger.info(f"   已存在: {duplicate_count} 条")
    logger.info(f"   新增: {inserted_count} 条")
    
    show_stats()
    return True


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