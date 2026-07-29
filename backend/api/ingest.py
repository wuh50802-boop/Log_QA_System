"""
日志采集与入库 API（仅 admin）。

端点：
    POST /api/ingest/generate       生成模拟日志并入库
    POST /api/ingest/upload         上传日志文件并入库
    GET  /api/ingest/tasks/{task_id} 查询任务状态（支持 task_token 鉴权）
    GET  /api/ingest/tasks           列出最近任务
    GET  /api/ingest/stats           数据库 + 向量库统计
    GET  /api/ingest/formats         支持的日志格式
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, status, Request
from pydantic import BaseModel, Field

from core.database import get_db
from core.tasks import task_store
from core.security import create_task_token, decode_task_token
from models.user import User, UserRole
from models.audit_log import AuditLog
from api.auth import get_current_user, log_audit, _require_admin
from services.ingest_service import (
    generate_task_id,
    run_upload_pipeline,
    run_generate_pipeline,
    save_upload_file,
    get_db_stats,
    get_qdrant_count,
    list_supported_formats,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# 上传文件大小上限：3GB（支持 HDFS Loghub 等大型数据集）
MAX_UPLOAD_BYTES = 3 * 1024 * 1024 * 1024
# 允许的文件后缀
ALLOWED_EXTENSIONS = {".csv", ".log", ".txt"}


# ============================================================
# 请求 / 响应模型
# ============================================================

class GenerateRequest(BaseModel):
    count: int = Field(default=10000, ge=1, le=100000, description="生成日志条数")
    vectorize: bool = Field(default=True, description="入库后向量化+重建BM25（强制开启，不可关闭）")
    rebuild_vector: bool = Field(default=False, description="是否重建向量索引（清空 Qdrant）")


class UploadParams(BaseModel):
    vectorize: bool = True
    rebuild_vector: bool = False


class TaskAcceptedResponse(BaseModel):
    success: bool = True
    task_id: str
    message: str
    task_type: str
    task_token: str = Field(..., description="任务专用长期 token（7 天有效期），用于轮询任务状态，不受登录 token 过期影响")


# ============================================================
# 内部辅助
# ============================================================

def _audit_ingest(db, user: User, action: str, task_id: str, details: dict):
    """记录入库操作审计日志"""
    log_audit(
        db=db,
        user_id=user.id,
        username=user.username,
        action=action,
        resource=f"task:{task_id}",
        details=details,
    )


def _start_background_task(task_id: str, task_type: str, target_fn, *args):
    """在独立线程中启动入库任务（避免阻塞 FastAPI 主线程）"""
    import threading
    thread = threading.Thread(
        target=target_fn,
        args=(task_id, *args),
        name=f"ingest-{task_id}",
        daemon=True,
    )
    thread.start()
    logger.info(f"后台任务已启动: {task_id} (thread={thread.name})")


# ============================================================
# 端点 1：生成模拟日志并入库
# ============================================================

@router.post(
    "/generate",
    response_model=TaskAcceptedResponse,
    summary="生成模拟日志并入库（仅 admin）",
)
async def generate_and_ingest(
    request: GenerateRequest,
    current_user: User = Depends(get_current_user),
    db = Depends(get_db),
):
    """
    生成模拟日志数据并完整走一遍入库流水线：
        生成 CSV → LogParser 解析 → LogCleaner 清洗 → 入库 SQLite → 向量化到 Qdrant

    **仅 admin 可调用**。任务异步执行，立即返回 task_id，
    通过 `GET /api/ingest/tasks/{task_id}` 查询进度。
    """
    _require_admin(current_user)

    # 检查是否已有任务在跑
    if task_store.is_busy():
        running_id = task_store.running_task_id()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"已有入库任务在运行: {running_id}，请等待完成",
        )

    task_id = generate_task_id("generate")
    task_store.create(task_id, task_type="generate")
    _audit_ingest(db, current_user, "ingest.generate.start", task_id, {
        "count": request.count,
        "vectorize": request.vectorize,
        "rebuild_vector": request.rebuild_vector,
    })

    # 签发任务专用长期 token，前端用它轮询进度，不受登录 token 过期影响
    task_token = create_task_token(
        user_id=current_user.id,
        username=current_user.username,
        task_id=task_id,
    )

    # 后台线程跑流水线（vectorize 强制 True：BM25 全量重建依赖向量化步骤）
    _start_background_task(
        task_id, "generate",
        run_generate_pipeline,
        request.count, True, request.rebuild_vector,
    )

    return TaskAcceptedResponse(
        task_id=task_id,
        message="任务已启动",
        task_type="generate",
        task_token=task_token,
    )


# ============================================================
# 端点 2：上传 CSV 文件并入库
# ============================================================

@router.post(
    "/upload",
    response_model=TaskAcceptedResponse,
    summary="上传日志文件并入库（仅 admin，支持 CSV/LOG）",
)
async def upload_and_ingest(
    file: UploadFile = File(..., description="日志文件（.csv / .log / .txt）"),
    vectorize: bool = Query(default=True, description="入库后向量化+重建BM25（强制开启）"),
    rebuild_vector: bool = Query(default=False, description="是否重建向量索引"),
    max_logs: int = Query(
        default=0, ge=0,
        description="当上传 .log 文件时，最多转换多少条日志（0=不限制）。建议先用 10000 测试",
    ),
    current_user: User = Depends(get_current_user),
    db = Depends(get_db),
):
    """
    上传日志文件，完整走一遍入库流水线：
        保存文件 → [可选] 格式转换 → LogParser 解析 → LogCleaner 清洗 → 入库 SQLite → 向量化到 Qdrant

    **仅 admin 可调用**。

    支持的文件格式：
    - **CSV**: 直接进入解析。需包含字段 `timestamp, level, service, ip, message, trace_id`
    - **LOG/TXT**: 自动识别日志格式并转换为 CSV。当前支持 HDFS（Loghub 数据集）格式

    文件大小上限 200MB。任务异步执行，立即返回 task_id。

    **max_logs 参数**：上传 .log 文件时，可限制最多转换多少条日志（默认 0=不限制）。
    建议先用 10000 条测试流程，确认通畅后再放开。
    """
    _require_admin(current_user)

    # 检查是否已有任务在跑
    if task_store.is_busy():
        running_id = task_store.running_task_id()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"已有入库任务在运行: {running_id}，请等待完成",
        )

    # 1. 校验文件后缀
    filename = file.filename or ""
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型: {suffix}，仅支持: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # 2. 读取并校验大小
    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件过大: {len(file_bytes)} bytes，上限 {MAX_UPLOAD_BYTES} bytes",
        )
    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="上传文件为空",
        )

    # 3. 保存文件
    saved_path = save_upload_file(file_bytes, filename)

    # 4. 创建任务 + 审计
    task_id = generate_task_id("upload")
    task_store.create(task_id, task_type="upload")
    _audit_ingest(db, current_user, "ingest.upload.start", task_id, {
        "filename": filename,
        "size_bytes": len(file_bytes),
        "saved_path": str(saved_path),
        "file_type": suffix,
        "vectorize": vectorize,
        "rebuild_vector": rebuild_vector,
        "max_logs": max_logs,
    })

    # 签发任务专用长期 token，前端用它轮询进度，不受登录 token 过期影响
    task_token = create_task_token(
        user_id=current_user.id,
        username=current_user.username,
        task_id=task_id,
    )

    # 5. 后台线程跑流水线（vectorize 强制 True：BM25 全量重建依赖向量化步骤）
    max_for_convert = max_logs if max_logs > 0 else None
    _start_background_task(
        task_id, "upload",
        run_upload_pipeline,
        saved_path, True, rebuild_vector, max_for_convert,
    )

    return TaskAcceptedResponse(
        task_id=task_id,
        message="文件已接收，入库任务已启动",
        task_type="upload",
        task_token=task_token,
    )


# ============================================================
# 端点 3：查询任务状态
# ============================================================

def _extract_bearer_token(request: Request) -> Optional[str]:
    """从 Authorization 头提取 Bearer token"""
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    return auth[7:]


def _auth_task_query(request: Request, task_id: str, db):
    """
    任务状态查询的鉴权逻辑：
    - 优先用 task_token（长期 token，仅能查指定任务）
    - 否则用普通 admin token（需要 admin 角色）

    这样前端轮询任务状态时，即使登录 token 过期，也能用 task_token 继续查。
    """
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少认证信息",
        )

    # 1. 先尝试 task_token（长期 token）
    payload = decode_task_token(token, task_id)
    if payload is not None:
        # task_token 校验通过，仅允许查这一个任务
        return

    # 2. 回退到普通 token + admin 校验
    from core.security import get_username_from_token
    from models.user import User
    username = get_username_from_token(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效或已过期",
        )
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )
    _require_admin(user)


@router.get(
    "/tasks/{task_id}",
    summary="查询入库任务状态（支持 task_token 鉴权）",
)
async def get_task_status(
    task_id: str,
    request: Request,
    db = Depends(get_db),
):
    """
    返回指定任务的详细状态，包括每个步骤的进度。

    **鉴权方式**（二选一）：
    - 任务专用 token（task_token，7 天有效期）：仅能查询本任务
    - 普通 admin token：需要 admin 角色

    前端轮询时建议用 task_token，避免登录 token 30 分钟过期后无法继续查询。
    """
    _auth_task_query(request, task_id, db)

    task = task_store.get(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务不存在: {task_id}",
        )
    return {"success": True, "data": task.to_dict()}


# ============================================================
# 端点 4：列出最近任务
# ============================================================

@router.get(
    "/tasks",
    summary="列出最近的入库任务（仅 admin）",
)
async def list_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
):
    """按开始时间倒序返回最近 N 个任务摘要。"""
    _require_admin(current_user)

    tasks = task_store.list_recent(limit)
    return {
        "success": True,
        "data": [t.to_dict() for t in tasks],
        "count": len(tasks),
    }


@router.post(
    "/tasks/{task_id}/cancel",
    summary="取消正在运行的入库任务（仅 admin）",
)
async def cancel_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
):
    """协作式取消：标记取消请求，流水线在下一批次检测到后自行停止。"""
    _require_admin(current_user)

    ok = task_store.request_cancel(task_id)
    if not ok:
        return {"success": False, "detail": "任务不存在或已结束，无法取消"}
    return {"success": True, "detail": "取消请求已发送，任务将在当前批次完成后停止"}


# ============================================================
# 端点 5：数据库 + 向量库统计
# ============================================================

@router.get(
    "/stats",
    summary="日志数据库与向量库统计（仅 admin）",
)
async def get_stats(
    current_user: User = Depends(get_current_user),
):
    """返回日志总数、按级别/服务分布、向量库总数、最近入库时间。"""
    _require_admin(current_user)

    db_stats = get_db_stats()
    qdrant_total = get_qdrant_count()

    return {
        "success": True,
        "data": {
            **db_stats,
            "qdrant_total": qdrant_total,
        },
    }


# ============================================================
# 端点 6：支持的日志格式
# ============================================================

@router.get(
    "/formats",
    summary="支持的日志格式列表（仅 admin）",
)
async def get_formats(
    current_user: User = Depends(get_current_user),
):
    """返回当前系统支持的日志文件格式及说明，供前端上传组件展示。"""
    _require_admin(current_user)
    return {
        "success": True,
        "data": list_supported_formats(),
    }


# ============================================================
# 端点 7：补建索引（向量索引和/或 BM25 索引）
# ============================================================

class RebuildRequest(BaseModel):
    mode: str = Field(
        default="both",
        description="重建模式：vector=只补建向量索引，bm25=只重建 BM25，both=两者都做",
    )
    rebuild_vector: bool = Field(
        default=False,
        description="是否清空 Qdrant Collection 全量重建（慎用，默认 False=增量续传）",
    )


def _validate_rebuild_mode(mode: str) -> bool:
    return mode in ("vector", "bm25", "both")


def _run_rebuild_pipeline(task_id: str, mode: str, rebuild_vector: bool):
    """
    重建索引后台任务：
        - mode=vector : 增量补建 Qdrant 向量索引（从 last_log_id 检查点续传）
        - mode=bm25   : 从 DB 全量重建 BM25 索引
        - mode=both   : 先补建向量索引，再重建 BM25

    复用 task_store 的 vectorize 步骤上报进度：
        - sub_step=vector 时显示向量化进度
        - sub_step=bm25 时显示 BM25 重建进度
    """
    from services.batch_vectorize import batch_vectorize

    if not task_store.try_start(task_id):
        task_store.finish(task_id, success=False, error="已有任务在运行")
        return

    try:
        # rebuild 任务不涉及解析/清洗/入库，标记为 skipped
        for step in ["convert", "parse", "clean", "import"]:
            task_store.update_step(task_id, step, status="skipped")

        # ---- Step 1: 向量索引补建 ----
        if mode in ("vector", "both"):
            task_store.update_step(
                task_id, "vectorize", status="running",
                detail={"sub_step": "vector", "processed": 0, "total": 0},
            )

            def _on_progress(processed, total):
                task_store.update_step(
                    task_id, "vectorize",
                    detail={"sub_step": "vector", "processed": processed, "total": total},
                )

            def _cancel_check():
                return task_store.is_cancel_requested(task_id)

            try:
                batch_vectorize(
                    batch_size=1024,
                    vector_batch_size=512,
                    resume=not rebuild_vector,
                    rebuild=rebuild_vector,
                    progress_callback=_on_progress,
                    cancel_callback=_cancel_check,
                )
            except InterruptedError as e:
                task_store.clear_cancel(task_id)
                task_store.update_step(
                    task_id, "vectorize", status="failed",
                    detail={"reason": str(e)},
                )
                task_store.finish(task_id, success=False, error=str(e))
                return

            if mode == "both":
                task_store.update_step(task_id, "vectorize", status="done")

        # ---- Step 2: BM25 重建 ----
        if mode in ("bm25", "both"):
            # 如果只跑 BM25，vectorize 之前是 pending，标记为 running 以显示 BM25 进度
            # 如果 both，vectorize 已经 done，这里改回 running 显示 BM25 子步骤
            task_store.update_step(
                task_id, "vectorize", status="running",
                detail={"sub_step": "bm25", "phase": "loading"},
            )

            # BM25 重建前检测取消
            if task_store.is_cancel_requested(task_id):
                task_store.clear_cancel(task_id)
                task_store.finish(task_id, success=False, error="用户在 BM25 重建前取消了任务")
                return

            _rebuild_bm25_index(task_id)

        task_store.update_step(task_id, "vectorize", status="done")
        task_store.finish(task_id, success=True)

    except Exception as e:
        logger.error(f"重建任务失败: {task_id}", exc_info=True)
        task_store.update_step(task_id, "vectorize", status="failed")
        task_store.finish(task_id, success=False, error=str(e))


def _rebuild_bm25_index(task_id: str):
    """
    从 DB 全量重建 BM25 索引（流式加载，避免一次性加载千万级 ORM 对象）。

    进度通过 task_store 上报到 vectorize 步骤的 detail.sub_step=bm25。
    """
    import time
    from sqlalchemy import text
    from core.database import engine
    import services.bm25_retriever as bm25_module
    from services.bm25_retriever import get_bm25_retriever

    t0 = time.time()

    # 清除全局单例，强制从最新 DB 数据重建
    bm25_module._bm25_retriever = None

    # 统计总数
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM logs")).scalar()
    logger.info(f"[{task_id}] BM25 重建：待索引日志数 {total}")

    # 流式加载
    corpus = []
    processed = 0
    batch_size = 50000
    with engine.connect() as conn:
        result = conn.execution_options(stream_results=True).execute(
            text("SELECT id, level, service, timestamp, message FROM logs ORDER BY id")
        )
        while True:
            # 检测取消
            if task_store.is_cancel_requested(task_id):
                task_store.clear_cancel(task_id)
                raise InterruptedError("用户在 BM25 加载阶段取消了任务")

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
            task_store.update_step(
                task_id, "vectorize",
                detail={
                    "sub_step": "bm25",
                    "phase": "loading",
                    "processed": processed,
                    "total": total,
                    "speed": round(speed, 0),
                },
            )
            logger.info(
                f"[{task_id}] BM25 加载: {processed}/{total} "
                f"({processed/total*100:.1f}%) | {speed:.0f} rows/s"
            )

    # 构建 BM25 索引
    task_store.update_step(
        task_id, "vectorize",
        detail={"sub_step": "bm25", "phase": "building", "total": len(corpus)},
    )
    logger.info(f"[{task_id}] BM25 构建：{len(corpus)} 条文档")
    get_bm25_retriever(corpus=corpus, cache_path="./bm25_index.pkl")

    elapsed = time.time() - t0
    logger.info(f"[{task_id}] BM25 重建完成：{len(corpus)} 条，耗时 {elapsed:.1f}s")


@router.post(
    "/rebuild",
    response_model=TaskAcceptedResponse,
    summary="补建索引（仅 admin）",
)
async def rebuild_indexes(
    request: RebuildRequest,
    current_user: User = Depends(get_current_user),
    db = Depends(get_db),
):
    """
    补建向量索引和/或 BM25 索引。适用场景：
        - 上传时未勾选「入库后向量化」，事后补建
        - 向量化阶段失败，从检查点续传
        - BM25 索引未构建或过时，全量重建

    **mode 参数**：
        - `vector` : 增量补建 Qdrant 向量索引（从 last_log_id 检查点续传）
        - `bm25`   : 从 DB 全量重建 BM25 索引
        - `both`   : 先补建向量索引，再重建 BM25（推荐）

    **rebuild_vector**：True=清空 Qdrant 全量重做（慎用），False=增量续传（默认）

    任务异步执行，立即返回 task_id，通过 `GET /api/ingest/tasks/{task_id}` 查询进度。
    """
    _require_admin(current_user)

    if not _validate_rebuild_mode(request.mode):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的 mode: {request.mode}，可选: vector / bm25 / both",
        )

    # 检查是否已有任务在跑
    if task_store.is_busy():
        running_id = task_store.running_task_id()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"已有入库任务在运行: {running_id}，请等待完成",
        )

    task_id = generate_task_id("rebuild")
    task_store.create(task_id, task_type="rebuild")
    _audit_ingest(db, current_user, "ingest.rebuild.start", task_id, {
        "mode": request.mode,
        "rebuild_vector": request.rebuild_vector,
    })

    # 签发任务专用长期 token
    task_token = create_task_token(
        user_id=current_user.id,
        username=current_user.username,
        task_id=task_id,
    )

    # 后台线程跑重建流水线
    _start_background_task(
        task_id, "rebuild",
        _run_rebuild_pipeline, task_id, request.mode, request.rebuild_vector,
    )

    return TaskAcceptedResponse(
        task_id=task_id,
        message=f"索引重建任务已启动（mode={request.mode}）",
        task_type="rebuild",
        task_token=task_token,
    )
