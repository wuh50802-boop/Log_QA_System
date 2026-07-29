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
import gc
import json
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


def _cleanup_intermediate_files(csv_path: Path, owns_csv: bool) -> dict:
    """
    入库成功后清理中间产物：断点续传检查点 + （可选）中间 CSV。

    仅在流水线成功跑完后调用。失败时必须保留这两类文件以便重试：
        - 检查点记录了已完成的批次，重试时跳过；
        - 中间 CSV 是检查点里 csv_path 指向的文件，删除后检查点失效。

    Args:
        csv_path: 流水线使用的 CSV 路径
        owns_csv: 是否由本流水线生成（generate/convert=True，用户上传 CSV=False）

    Returns:
        清理结果 dict（用于记入 artifacts）
    """
    result = {"checkpoint_removed": False, "csv_removed": False,
              "csv_path": str(csv_path), "owns_csv": owns_csv}

    # 1. 删除断点续传检查点文件（无论 owns_csv 与否都应清理）
    checkpoint_file = DATA_DIR / f"checkpoint_{csv_path.name}.json"
    try:
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            logger.info(f"🧹 已删除检查点文件: {checkpoint_file.name}")
            result["checkpoint_removed"] = True
    except Exception as e:
        logger.warning(f"⚠️ 删除检查点文件失败（不影响入库结果）: {e}")

    # 2. 删除中间 CSV（仅限流水线自己生成的文件）
    #    用户直接上传的 .csv 绝不删除。
    if owns_csv:
        try:
            if csv_path.exists():
                csv_path.unlink()
                logger.info(f"🧹 已删除中间 CSV: {csv_path.name}")
                result["csv_removed"] = True
        except Exception as e:
            logger.warning(f"⚠️ 删除中间 CSV 失败（不影响入库结果）: {e}")

    return result


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

    # 标记当前流水线是否"拥有" csv_path（即流水线自己生成的中间文件）。
    # - generate 模式生成的 logs_{task_id}.csv     → 自己生成，成功后可清理
    # - .log/.txt 转换得到的 converted_{task_id}.csv → 自己生成，成功后可清理
    # - 用户直接上传的 .csv                         → 用户文件，绝不能删
    owns_csv = False

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
            owns_csv = True  # 自己生成的中间 CSV
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
                # 用户上传的 CSV：owns_csv 保持 False，禁止清理
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

                owns_csv = True  # 转换产生的中间 CSV
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

        # ---------- Step 1-3: 分块 解析→清洗→入库（流式，内存友好） ----------
        import hashlib as _hashlib
        from scripts.import_logs import bulk_insert_logs

        CHUNK_SIZE = 50000  # 每批处理 5 万条

        # --- 断点续传：加载检查点 ---
        checkpoint_file = DATA_DIR / f"checkpoint_{csv_path.name}.json"
        resume_chunk = 0
        if checkpoint_file.exists():
            try:
                with open(checkpoint_file, "r", encoding="utf-8") as f:
                    ckpt = json.load(f)
                if ckpt.get("csv_path") == str(csv_path):
                    resume_chunk = ckpt.get("chunk_idx", 0)
                    logger.info(f"📌 检测到断点: 跳过前 {resume_chunk} 批，从第 {resume_chunk + 1} 批继续")
            except Exception:
                resume_chunk = 0

        t0 = time.time()
        task_store.update_step(task_id, "parse", status="running",
                               detail={"sub_step": "streaming"})
        task_store.update_step(task_id, "clean", status="running")
        task_store.update_step(task_id, "import", status="running")

        # 全局去重集合（仅存 16 字节 MD5 摘要，1100 万条 ≈ 176 MB）
        seen_hashes: set = set()
        total_valid = 0
        total_failed = 0
        total_empty = 0
        total_dup = 0
        total_inserted = 0
        total_skipped = 0
        chunk_idx = 0

        for chunk, failed_in_chunk in LogParser.parse_csv_chunked(
                str(csv_path), chunk_size=CHUNK_SIZE):
            chunk_idx += 1

            # 断点续传：跳过已完成的批次
            if chunk_idx <= resume_chunk:
                total_valid += len(chunk)
                total_failed += failed_in_chunk
                del chunk
                continue

            # 协作式取消检测
            if task_store.is_cancel_requested(task_id):
                task_store.clear_cancel(task_id)
                raise InterruptedError("用户取消了任务")

            total_valid += len(chunk)
            total_failed += failed_in_chunk

            # --- 清洗：去空值 ---
            cleaned = []
            for log in chunk:
                c = LogCleaner.clean_single(log)
                if not LogCleaner.is_empty(c):
                    cleaned.append(c)
                else:
                    total_empty += 1
            del chunk

            # --- 清洗：去重（跨批次全局） ---
            unique = []
            for log in cleaned:
                raw = "|".join((
                    log.get("timestamp", ""),
                    log.get("level", ""),
                    log.get("service", ""),
                    log.get("message", ""),
                ))
                h = _hashlib.md5(raw.encode("utf-8", errors="replace")).digest()
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    unique.append(log)
                else:
                    total_dup += 1
            del cleaned

            # --- 入库 ---
            if unique:
                ins, skp = bulk_insert_logs(unique, batch_size=500)
                total_inserted += ins
                total_skipped += skp
            del unique
            gc.collect()

            # --- 保存断点 ---
            try:
                with open(checkpoint_file, "w", encoding="utf-8") as f:
                    json.dump({
                        "csv_path": str(csv_path),
                        "chunk_idx": chunk_idx,
                        "total_valid": total_valid,
                        "total_inserted": total_inserted,
                    }, f)
            except Exception:
                pass  # 断点写入失败不阻断主流程

            # 更新进度（每批刷新一次）
            task_store.update_step(task_id, "parse", status="running",
                                   detail={"valid_so_far": total_valid,
                                           "failed_so_far": total_failed,
                                           "chunks": chunk_idx})
            task_store.update_step(task_id, "import", status="running",
                                   detail={"inserted_so_far": total_inserted})

        # 释放去重集合
        del seen_hashes
        gc.collect()

        parse_duration = time.time() - t0

        if total_valid == 0:
            raise ValueError(f"CSV 解析后无有效日志，失败 {total_failed} 条")

        # 标记三步完成
        task_store.update_step(task_id, "parse", status="done",
                               detail={
                                   "valid": total_valid,
                                   "failed": total_failed,
                                   "chunks": chunk_idx,
                               },
                               duration_sec=round(parse_duration, 2))
        task_store.update_step(task_id, "clean", status="done",
                               detail={
                                   "input": total_valid,
                                   "output": total_valid - total_empty - total_dup,
                                   "removed_empty": total_empty,
                                   "removed_duplicate": total_dup,
                               },
                               duration_sec=round(parse_duration, 2))
        task_store.update_step(task_id, "import", status="done",
                               detail={
                                   "inserted": total_inserted,
                                   "skipped_duplicate": total_skipped,
                               },
                               duration_sec=round(parse_duration, 2))

        # ---------- Step 4: 向量化（可选） ----------
        if vectorize:
            t0 = time.time()
            task_store.update_step(task_id, "vectorize", status="running",
                                   detail={"processed": 0, "total": 0})

            from services.batch_vectorize import batch_vectorize

            def _on_progress(processed: int, total: int):
                task_store.update_step(task_id, "vectorize",
                                       detail={"processed": processed, "total": total})

            # 协作式取消回调：batch_vectorize 每批开始前调用
            # 返回 True 表示收到取消请求，会保存检查点后抛 InterruptedError
            def _cancel_check() -> bool:
                return task_store.is_cancel_requested(task_id)

            try:
                batch_vectorize(
                    batch_size=256,
                    vector_batch_size=64,
                    resume=not rebuild_vector,
                    rebuild=rebuild_vector,
                    progress_callback=_on_progress,
                    cancel_callback=_cancel_check,
                )
            except InterruptedError as cancel_err:
                # 用户取消：清理取消标记，标记 vectorize 步骤为 cancelled
                # 然后重新抛出，让外层 except 统一处理 task_store.finish
                task_store.clear_cancel(task_id)
                task_store.update_step(task_id, "vectorize", status="cancelled",
                                       detail={"reason": str(cancel_err)})
                # 取消后不清理中间文件（保留 checkpoint + CSV 以便重试）
                raise

            vec_duration = time.time() - t0
            task_store.update_step(task_id, "vectorize", status="done",
                                   detail={"processed": "done"},
                                   duration_sec=round(vec_duration, 2))

            # ---------- Step 4.5: 重建 BM25 索引 ----------
            # BM25 索引独立缓存于 bm25_index.pkl，与 SQLite/Qdrant 不会自动同步。
            # BM25Okapi 不支持增量更新，每次入库后必须全量重建。
            # 使用流式加载 + 模板去重，避免千万级数据一次性加载导致 OOM。
            try:
                t0 = time.time()
                logger.info("🔨 开始重建 BM25 索引...")

                # BM25 重建前检测取消（千万级日志重建可能耗时几分钟）
                if task_store.is_cancel_requested(task_id):
                    task_store.clear_cancel(task_id)
                    raise InterruptedError("用户在 BM25 重建前取消了任务")

                # 清除全局单例，强制从最新 DB 数据重建
                import services.bm25_retriever as bm25_module
                bm25_module._bm25_retriever = None

                # 流式加载 + 模板去重（与 rebuild_indexes.py 一致）
                # rank_bm25 是纯 Python 实现，千万级文档会 MemoryError
                # HDFS 等日志高度重复，模板去重后通常只剩几万条独立模板
                from core.database import engine
                from sqlalchemy import text
                from services.batch_vectorize import normalize_template

                seen_templates = {}  # template -> corpus item
                processed = 0
                fetch_batch = 50000

                with engine.connect() as conn:
                    result = conn.execution_options(stream_results=True).execute(
                        text("SELECT id, level, service, timestamp, message FROM logs ORDER BY id")
                    )
                    while True:
                        rows = result.fetchmany(fetch_batch)
                        if not rows:
                            break
                        for row in rows:
                            msg = row[4] or ""
                            template = normalize_template(msg)
                            if template not in seen_templates:
                                seen_templates[template] = {
                                    "log_id": row[0],
                                    "level": row[1],
                                    "service": row[2],
                                    "timestamp": str(row[3]),
                                    "message": msg,
                                    "chunk_text": msg,
                                    "source": row[2],
                                }
                        processed += len(rows)
                        logger.info(f"📥 BM25 加载进度: {processed:,} 条已扫描, "
                                    f"{len(seen_templates):,} 个独立模板")

                dedup_corpus = list(seen_templates.values())
                del seen_templates  # 释放内存

                logger.info(f"📦 BM25 模板去重完成: {processed:,} → {len(dedup_corpus):,} 条")

                from services.bm25_retriever import get_bm25_retriever
                bm25 = get_bm25_retriever(corpus=dedup_corpus, cache_path="./bm25_index.pkl")
                bm25_duration = time.time() - t0
                logger.info(f"✅ BM25 索引重建完成: 原始 {processed:,} 条 → "
                            f"模板 {len(dedup_corpus):,} 条, 耗时 {bm25_duration:.2f}s")
            except Exception as bm25_err:
                # BM25 重建失败不阻断入库主流程，但记录错误
                logger.error(f"⚠️ BM25 索引重建失败（不影响向量检索）: {bm25_err}", exc_info=True)
        else:
            task_store.update_step(task_id, "vectorize", status="skipped")

        # ---------- 完成 ----------
        # 自动清理：删除断点续传检查点 + 中间 CSV（仅流水线生成的文件）
        # 失败时不清理，保留以便重试。
        cleanup_result = _cleanup_intermediate_files(csv_path, owns_csv)

        total_duration = time.time() - start_total
        task_store.update(task_id, artifacts={
            **(task_store.get(task_id).artifacts if task_store.get(task_id) else {}),
            "total_duration_sec": round(total_duration, 2),
            "cleanup": cleanup_result,
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
