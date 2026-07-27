"""
入库流水线编排服务。

完整 5 步流水线（针对 .log 文件）：
    格式转换 → LogParser.parse_csv → LogCleaner.clean_batch → bulk_insert_logs → batch_vectorize

CSV 文件会跳过"格式转换"步骤，直接进入解析。

两种触发模式：
    - upload:  上传 CSV 或 LOG 文件（真实数据）
    - generate: 模拟生成日志（测试辅助）

任务状态通过 core.tasks.task_store 跟踪，前后端通过 task_id 查询进度。
"""
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from core.tasks import task_store, STATUS_DONE, STATUS_FAILED
from services.log_parser import LogParser
from services.log_cleaner import LogCleaner

logger = logging.getLogger(__name__)

# 数据目录（上传文件、失败日志、生成的 CSV 都放这里）
DATA_DIR = Path(__file__).parent.parent / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 格式识别 + 适配器注册
# ============================================================

# 支持的文件后缀
SUPPORTED_EXTENSIONS = {".csv", ".log", ".txt"}

# 已注册的日志格式适配器（按格式名 → 转换函数）
# 每个适配器签名: (input_path: Path, output_path: Path, max_logs: Optional[int]) -> dict
_ADAPTERS = {}


def register_adapter(format_name: str, detector, converter):
    """
    注册一个日志格式适配器。

    Args:
        format_name: 格式名（如 "hdfs"）
        detector: 检测函数 (sample_lines: list[str]) -> bool，返回 True 表示匹配
        converter: 转换函数 (input_path, output_path, max_logs) -> dict
    """
    _ADAPTERS[format_name] = {"detector": detector, "converter": converter}


def _detect_encoding(file_path: Path) -> str:
    """
    通过 BOM 头自动识别文件编码。

    支持:
        - UTF-8 BOM (\xef\xbb\xbf)         -> utf-8-sig
        - UTF-16 LE BOM (\xff\xfe)         -> utf-16
        - UTF-16 BE BOM (\xfe\xff)         -> utf-16
        - 无 BOM                            -> utf-8（失败时调用方用 errors='ignore' 兜底）
    """
    try:
        with open(file_path, 'rb') as f:
            head = f.read(4)
        if head[:3] == b'\xef\xbb\xbf':
            return 'utf-8-sig'
        if head[:2] == b'\xff\xfe':
            return 'utf-16'
        if head[:2] == b'\xfe\xff':
            return 'utf-16'
    except Exception:
        pass
    return 'utf-8'


def detect_format(file_path: Path, sample_lines: int = 50) -> Optional[str]:
    """
    通过文件内容样本检测日志格式。

    自动识别 UTF-8 / UTF-16 编码（处理 Windows PowerShell 导出的文件）。

    Args:
        file_path: 文件路径
        sample_lines: 读取前 N 行作为样本

    Returns:
        格式名（如 "hdfs"），无法识别返回 None
    """
    encoding = _detect_encoding(file_path)
    try:
        with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
            lines = []
            for _ in range(sample_lines):
                line = f.readline()
                if not line:
                    break
                lines.append(line)
    except Exception as e:
        logger.warning(f"读取文件样本失败: {e}")
        return None

    for name, adapter in _ADAPTERS.items():
        try:
            if adapter["detector"](lines):
                logger.info(f"文件 {file_path.name} 识别为格式: {name} (encoding={encoding})")
                return name
        except Exception as e:
            logger.warning(f"格式 {name} 检测器异常: {e}")
    return None


def convert_log_to_csv(input_path: Path, output_path: Path,
                       max_logs: Optional[int] = None) -> Tuple[str, dict]:
    """
    将 .log 文件转换为 CSV。自动识别格式并调用对应适配器。

    Returns:
        (format_name, stats_dict)
    """
    fmt = detect_format(input_path)
    if not fmt:
        raise ValueError(
            f"无法识别日志格式: {input_path.name}。"
            f"当前已注册适配器: {list(_ADAPTERS.keys()) or '无'}"
        )

    adapter = _ADAPTERS[fmt]
    stats = adapter["converter"](input_path, output_path, max_logs)
    return fmt, stats


# ============================================================
# 内置适配器：HDFS（Loghub 数据集）
# ============================================================

import re

_HDFS_PATTERN = re.compile(
    r'^\d{6}\s+\d{6}\s+\d+\s+\w+\s+[\w\.\$]+:\s+.+$'
)


def _hdfs_detector(lines) -> bool:
    """
    检测是否为 HDFS 日志格式。

    策略：
        - 过滤掉空行后再计算匹配率（避免开头/中间空行影响）
        - 阈值 30%（HDFS 数据集可能混杂个别异常行）
        - 至少需要 2 条匹配（防止极小样本误判）
    """
    non_empty = [line.strip() for line in lines if line.strip()]
    if not non_empty:
        return False
    matches = sum(1 for line in non_empty if _HDFS_PATTERN.match(line))
    # 至少 2 条匹配，且非空行中匹配率 >= 30%
    return matches >= 2 and matches >= len(non_empty) * 0.3


def _hdfs_converter(input_path: Path, output_path: Path,
                    max_logs: Optional[int] = None) -> dict:
    """HDFS → CSV 转换（复用 scripts/import_hdfs.py 的逻辑）"""
    from scripts.import_hdfs import convert_hdfs_to_csv
    # 自动识别编码（PowerShell 导出的文件常为 UTF-16）
    encoding = _detect_encoding(input_path)
    return convert_hdfs_to_csv(input_path, output_path, max_logs=max_logs,
                               encoding=encoding)


# 注册 HDFS 适配器
register_adapter("hdfs", _hdfs_detector, _hdfs_converter)


# ============================================================
# 任务 ID 生成 + 文件保存
# ============================================================

def generate_task_id(task_type: str) -> str:
    """生成形如 ingest_20260727_153000_a1b2c3 的任务 ID"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"ingest_{task_type}_{ts}_{short}"


def save_upload_file(file_bytes: bytes, original_name: str) -> Path:
    """保存上传的文件到 data/uploads/，返回保存路径"""
    safe_name = Path(original_name).name  # 防路径穿越
    unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    target = UPLOAD_DIR / unique_name
    target.write_bytes(file_bytes)
    return target


# ============================================================
# 流水线：上传模式（真实数据，支持 CSV 和 LOG）
# ============================================================

def run_upload_pipeline(
    task_id: str,
    file_path: Path,
    vectorize: bool = True,
    rebuild_vector: bool = False,
    max_logs_for_convert: Optional[int] = None,
):
    """上传文件 → （可选）格式转换 → 解析 → 清洗 → 入库 → 向量化"""
    _run_pipeline(task_id, task_type="upload",
                  file_path=file_path, vectorize=vectorize,
                  rebuild_vector=rebuild_vector,
                  max_logs_for_convert=max_logs_for_convert)


# ============================================================
# 流水线：生成模式（模拟数据）
# ============================================================

def run_generate_pipeline(
    task_id: str,
    count: int = 10000,
    vectorize: bool = True,
    rebuild_vector: bool = False,
):
    """生成模拟日志 → 解析 → 清洗 → 入库 → 向量化"""
    _run_pipeline(task_id, task_type="generate",
                  generate_count=count, vectorize=vectorize,
                  rebuild_vector=rebuild_vector)


# ============================================================
# 流水线核心
# ============================================================

def _run_pipeline(
    task_id: str,
    task_type: str,
    file_path: Optional[Path] = None,
    generate_count: Optional[int] = None,
    vectorize: bool = True,
    rebuild_vector: bool = False,
    max_logs_for_convert: Optional[int] = None,
):
    """
    统一流水线入口。

    入参二选一：
        - file_path: 已存在的文件路径（upload 模式，可以是 .csv 或 .log）
        - generate_count: 生成 N 条模拟日志（generate 模式）
    """
    # 1. 占用运行锁
    if not task_store.try_start(task_id):
        task_store.update(task_id, error="已有入库任务在运行，请等待完成")
        task_store.finish(task_id, success=False, error="任务未启动：另一任务正在运行")
        logger.warning(f"任务 {task_id} 未启动：已有任务在运行")
        return

    logger.info(f"入库任务开始: {task_id} (type={task_type})")
    start_total = time.time()

    try:
        # ---------- Step 0: 准备输入文件 ----------
        # generate 模式下先生成 CSV
        if generate_count is not None:
            task_store.update_step(task_id, "convert", status="running",
                                   detail={"sub_step": "generating"})
            from scripts.generate_logs import generate_logs, save_to_csv
            logs = generate_logs(generate_count)
            csv_path = DATA_DIR / f"logs_{task_id}.csv"
            save_to_csv(logs, str(csv_path))
            task_store.update_step(task_id, "convert", status="done",
                                   detail={"generated": len(logs)},
                                   duration_sec=0)
            task_store.update(task_id, artifacts={
                **(task_store.get(task_id).artifacts if task_store.get(task_id) else {}),
                "source_file": str(csv_path),
            })
        elif file_path is not None:
            # upload 模式：判断是否需要格式转换
            suffix = file_path.suffix.lower()
            if suffix == ".csv":
                # CSV 直接进入解析，convert 步骤标记为 skipped
                csv_path = file_path
                task_store.update_step(task_id, "convert", status="skipped",
                                       detail={"reason": "CSV 文件无需转换"})
            else:
                # .log / .txt 等需要先转换
                t0 = time.time()
                task_store.update_step(task_id, "convert", status="running",
                                       detail={"sub_step": "detecting"})
                csv_path = DATA_DIR / f"converted_{task_id}.csv"

                try:
                    fmt, conv_stats = convert_log_to_csv(
                        file_path, csv_path, max_logs=max_logs_for_convert
                    )
                except Exception as e:
                    task_store.update_step(task_id, "convert", status="failed",
                                           detail={"error": str(e)})
                    raise

                convert_duration = time.time() - t0
                task_store.update_step(task_id, "convert", status="done",
                                       detail={
                                           "format": fmt,
                                           "total": conv_stats.get("total", 0),
                                           "valid": conv_stats.get("valid", 0),
                                           "failed": conv_stats.get("failed", 0),
                                       },
                                       duration_sec=round(convert_duration, 2))
                task_store.update(task_id, artifacts={
                    **(task_store.get(task_id).artifacts if task_store.get(task_id) else {}),
                    "source_file": str(file_path),
                    "converted_csv": str(csv_path),
                    "detected_format": fmt,
                })
        else:
            raise ValueError("必须提供 file_path 或 generate_count 之一")

        # ---------- Step 1: 解析 ----------
        t0 = time.time()
        task_store.update_step(task_id, "parse", status="running",
                               detail={"sub_step": "parsing"})
        valid_logs, failed_logs = LogParser.parse_csv(str(csv_path))

        # 失败日志落盘
        failed_path = DATA_DIR / f"failed_{task_id}.log"
        if failed_logs:
            LogParser.save_failed_logs(failed_logs, str(failed_path))

        parse_duration = time.time() - t0
        task_store.update_step(task_id, "parse", status="done",
                               detail={
                                   "valid": len(valid_logs),
                                   "failed": len(failed_logs),
                                   "failed_log_path": str(failed_path) if failed_logs else None,
                               },
                               duration_sec=round(parse_duration, 2))

        if not valid_logs:
            raise ValueError(f"CSV 解析后无有效日志，失败 {len(failed_logs)} 条")

        # ---------- Step 2: 清洗 ----------
        t0 = time.time()
        task_store.update_step(task_id, "clean", status="running")
        clean_result = LogCleaner.clean_batch(valid_logs)
        cleaned_logs = clean_result["cleaned"]
        clean_duration = time.time() - t0

        task_store.update_step(task_id, "clean", status="done",
                               detail={
                                   "input": len(valid_logs),
                                   "output": len(cleaned_logs),
                                   "removed_empty": clean_result["removed_empty"],
                                   "removed_duplicate": clean_result["removed_duplicate"],
                               },
                               duration_sec=round(clean_duration, 2))

        if not cleaned_logs:
            raise ValueError("清洗后无有效日志可入库")

        # ---------- Step 3: 入库 ----------
        t0 = time.time()
        task_store.update_step(task_id, "import", status="running")
        # 延迟导入避免循环依赖
        from scripts.import_logs import bulk_insert_logs
        inserted, skipped = bulk_insert_logs(cleaned_logs, batch_size=500)
        import_duration = time.time() - t0

        task_store.update_step(task_id, "import", status="done",
                               detail={
                                   "inserted": inserted,
                                   "skipped_duplicate": skipped,
                               },
                               duration_sec=round(import_duration, 2))

        # ---------- Step 4: 向量化（可选） ----------
        if vectorize:
            t0 = time.time()
            task_store.update_step(task_id, "vectorize", status="running",
                                   detail={"processed": 0, "total": 0})

            from scripts.batch_vectorize import batch_vectorize

            def _on_progress(processed: int, total: int):
                task_store.update_step(task_id, "vectorize",
                                       detail={"processed": processed, "total": total})

            batch_vectorize(
                batch_size=100,
                vector_batch_size=20,
                resume=not rebuild_vector,
                rebuild=rebuild_vector,
                progress_callback=_on_progress,
            )
            vec_duration = time.time() - t0
            task_store.update_step(task_id, "vectorize", status="done",
                                   detail={"processed": "done"},
                                   duration_sec=round(vec_duration, 2))

            # ---------- Step 4.5: 重建 BM25 索引 ----------
            # BM25 索引独立缓存于 bm25_index.pkl，与 SQLite/Qdrant 不会自动同步。
            # 每次入库后必须重建，否则检索会返回旧数据（模拟数据残留就是这么来的）。
            # rebuild_vector=True 时已经清空了 Qdrant，这里同样要重建 BM25。
            try:
                t0 = time.time()
                logger.info("🔨 开始重建 BM25 索引...")
                # 清除全局单例，强制从最新 DB 数据重建
                import services.bm25_retriever as bm25_module
                bm25_module._bm25_retriever = None

                # 从 DB 加载全部日志作为 corpus
                from core.database import SessionLocal
                from models.log import Log
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

                from services.bm25_retriever import get_bm25_retriever
                bm25 = get_bm25_retriever(corpus=corpus, cache_path="./bm25_index.pkl")
                bm25_duration = time.time() - t0
                logger.info(f"✅ BM25 索引重建完成: {len(corpus)} 条文档, "
                            f"耗时 {bm25_duration:.2f}s")
            except Exception as bm25_err:
                # BM25 重建失败不阻断入库主流程，但记录错误
                logger.error(f"⚠️ BM25 索引重建失败（不影响向量检索）: {bm25_err}", exc_info=True)
        else:
            task_store.update_step(task_id, "vectorize", status="skipped")

        # ---------- 完成 ----------
        total_duration = time.time() - start_total
        task_store.update(task_id, artifacts={
            **(task_store.get(task_id).artifacts if task_store.get(task_id) else {}),
            "total_duration_sec": round(total_duration, 2),
        })
        task_store.finish(task_id, success=True)
        logger.info(f"入库任务完成: {task_id}, 总耗时 {total_duration:.1f}s")

    except Exception as e:
        logger.exception(f"入库任务失败: {task_id}")
        # 把异常记到当前步骤
        current = task_store.get(task_id)
        current_step = current.current_step if current else None
        if current_step:
            task_store.update_step(task_id, current_step, status="failed",
                                   detail={"error": str(e)})
        task_store.finish(task_id, success=False, error=str(e))


# ============================================================
# 查询辅助
# ============================================================

def get_db_stats() -> dict:
    """获取数据库 + 向量库的统计信息"""
    from sqlalchemy import func
    from core.database import SessionLocal
    from models.log import Log

    db = SessionLocal()
    try:
        total = db.query(Log).count()
        levels = db.query(Log.level, func.count()).group_by(Log.level).all()
        services = db.query(Log.service, func.count()).group_by(Log.service).all()
        # 最后入库时间
        last = db.query(Log.created_at).order_by(Log.created_at.desc()).first()
        return {
            "db_total": total,
            "by_level": {lvl: cnt for lvl, cnt in levels},
            "by_service": {svc: cnt for svc, cnt in services},
            "last_ingest_at": last[0].isoformat(timespec="seconds") if last else None,
        }
    finally:
        db.close()


def get_qdrant_count() -> int:
    """获取 Qdrant 向量总数（失败返回 -1）"""
    try:
        from services.qdrant_client import get_qdrant_client
        client = get_qdrant_client()
        return client.count()
    except Exception as e:
        logger.warning(f"获取 Qdrant 计数失败: {e}")
        return -1


def list_supported_formats() -> list:
    """返回当前支持的日志格式列表（供前端展示）"""
    return [
        {"name": "csv", "extensions": [".csv"], "description": "标准 CSV（项目原生格式）"},
        {"name": "hdfs", "extensions": [".log", ".txt"], "description": "HDFS 日志（Loghub 数据集）"},
    ]
