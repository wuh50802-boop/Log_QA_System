# 问答 API 路由
import json
import time
import uuid
import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, func as sa_func, desc

from core.database import get_db
from api.auth import get_current_user, log_audit
from models.user import User
from models.qa_history import QAHistory, FeedbackType
from schemas.qa import (
    QARequest, QAResponse, QASourceRef,
    QAQualityCheck, QAQualityIssue,
    QAHistoryItem, QAHistoryListResponse, QAHistoryDetailResponse,
    FeedbackRequest, FeedbackResponse,
    ConversationItem, ConversationListResponse,
    ConversationMessageItem, ConversationDetailResponse,
    ConversationDeleteResponse,
    FeedbackStatsResponse, FeedbackStatsItem,
)
from services.qa_pipeline import QAResult
from services.error_handler import create_robust_pipeline, RobustQAPipeline
from services.quality_checker import QualityChecker

logger = logging.getLogger(__name__)

router = APIRouter()


# 多轮对话：传给 LLM 的最大历史轮数（1 轮 = 1 user + 1 assistant）
MAX_HISTORY_TURNS = 5

# 质量检查器（无状态，进程级单例即可）
_quality_checker = QualityChecker()


def _run_quality_check(
    answer: str,
    sources: List[Dict[str, Any]],
    confidence: str = "中",
) -> Optional[QAQualityCheck]:
    """
    执行回答质量自检并转换为响应 Schema。
    任何异常都视为"未通过检查"，但不影响主流程。
    """
    if not answer:
        return None
    try:
        result = _quality_checker.check(
            answer=answer,
            sources=sources,
            confidence=confidence,
        )
        issues = [
            QAQualityIssue(
                type=issue.get("type", "issue"),
                message=issue.get("message", ""),
                penalty=float(issue.get("penalty", 0) or 0),
                suggestion=issue.get("suggestion"),
            )
            for issue in result.issues
        ]
        return QAQualityCheck(
            passed=result.passed,
            score=round(float(result.score), 1),
            issues=issues,
            warnings=result.warnings,
            suggestions=result.suggestions,
        )
    except Exception as e:
        logger.warning(f"质量自检失败（不影响回答）: {e}")
        return None


def _build_pipeline(request: QARequest) -> RobustQAPipeline:
    """
    构建健壮的问答流水线（每次请求新建，避免多用户共享状态）。
    使用 RobustQAPipeline 包装 QAPipeline，接管异常处理：
    - LLM 超时/Qdrant 故障时自动重试
    - 异常时返回友好错误提示而非 500，返回类型仍为 QAResult
    """
    return create_robust_pipeline(
        top_k=request.top_k or 5,
        template_type=request.template_type or "evidence_chain",
        retriever_type=request.retriever_type or "hybrid",
    )


def _resolve_conversation_id(
    db: Session,
    user_id: int,
    conversation_id: Optional[str],
) -> str:
    """
    解析会话 ID：传入有效 ID 时校验归属并复用；否则新建一个。
    返回值保证是当前用户可见的会话 ID。
    """
    if conversation_id and conversation_id.strip():
        cid = conversation_id.strip()
        # 校验该会话确实属于当前用户（避免越权访问他人会话）
        exists = (
            db.query(QAHistory.id)
            .filter(
                QAHistory.conversation_id == cid,
                QAHistory.user_id == user_id,
            )
            .first()
        )
        if exists:
            return cid
        # 不属于当前用户或不存在：当作新会话处理（避免直接报错打断 UX）
        logger.warning(
            f"用户 {user_id} 提供的 conversation_id={cid} 不存在或不属于该用户，已新建会话"
        )
    return f"conv_{uuid.uuid4().hex[:16]}"


def _load_conversation_history(
    db: Session,
    user_id: int,
    conversation_id: str,
    max_turns: int = MAX_HISTORY_TURNS,
) -> List[Dict[str, str]]:
    """
    从 DB 加载多轮对话历史，转换为 LLM 可用的 [{role, content}] 格式。
    只取最近 max_turns 轮（每轮 = user + assistant 两条），按时间正序返回。
    """
    records = (
        db.query(QAHistory.question, QAHistory.answer)
        .filter(
            QAHistory.user_id == user_id,
            QAHistory.conversation_id == conversation_id,
        )
        .order_by(QAHistory.created_at.asc())
        .all()
    )
    # 取最近 max_turns 轮
    recent = records[-max_turns:] if len(records) > max_turns else records
    history: List[Dict[str, str]] = []
    for q, a in recent:
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant", "content": a})
    return history


@router.post("/ask", response_model=QAResponse, summary="同步问答")
def ask(
    request: QARequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    同步问答接口：检索 + LLM 生成，返回带来源标注的回答。

    - **question**: 用户问题（必填，1-500 字符）
    - **filters**: 检索过滤条件，如 {"level": "ERROR", "service": "auth-service"}
    - **top_k**: 检索返回的日志数量（1-50，默认 5）
    - **template_type**: Prompt 模板类型（evidence_chain / quick / short）
    - **retriever_type**: 检索器类型（vector / bm25 / hybrid，默认 hybrid）
    - **conversation_id**: 会话 ID，传已有的 ID 表示继续多轮对话；不传或为空表示开启新会话。
      响应中始终返回当前会话 ID，前端应在后续提问中携带以维持上下文。

    需要在 Header 中携带 `Authorization: Bearer <token>`。
    """
    # 1. 解析会话 ID（复用或新建），并加载多轮对话历史
    conversation_id = _resolve_conversation_id(db, current_user.id, request.conversation_id)
    history = _load_conversation_history(db, current_user.id, conversation_id)

    logger.info(
        f"用户 {current_user.username} 提问: {request.question[:50]}... "
        f"(retriever={request.retriever_type or 'hybrid'}, top_k={request.top_k or 5}, "
        f"conversation={conversation_id}, history_turns={len(history)//2})"
    )

    # 2. 构建流水线并执行问答（传入历史以支持多轮上下文）
    # RobustQAPipeline 内部已接管异常处理：LLM 超时/检索故障时自动重试，
    # 重试仍失败则返回带友好提示的 QAResult（confidence="低"），不会抛出异常
    pipeline = _build_pipeline(request)
    result = pipeline.ask(
        question=request.question,
        filters=request.filters,
        top_k=request.top_k,
        template_type=request.template_type,
        history=history,
    )

    # 3. 转换来源引用为响应 Schema
    source_refs = [
        QASourceRef(
            ref_id=ref.ref_id,
            log_id=ref.log_id,
            service=ref.service,
            timestamp=ref.timestamp,
            level=ref.level,
            content=ref.content,
            score=ref.score,
            snippet=ref.snippet,
        )
        for ref in result.source_refs
    ]

    # 4. 持久化问答历史（带 conversation_id）
    qa_id = None
    # 预先计算质量自检结果，便于随历史记录一起持久化
    quality_check = None if (result.confidence == "低" and not result.source_refs) else (
        _run_quality_check(
            answer=result.answer,
            sources=[ref.to_dict() for ref in result.source_refs],
            confidence=result.confidence,
        )
    )
    try:
        history_record = QAHistory(
            user_id=current_user.id,
            question=request.question,
            answer=result.answer,
            sources=json.dumps(
                [ref.to_dict() for ref in result.source_refs],
                ensure_ascii=False,
            ) if result.source_refs else None,
            feedback=FeedbackType.NONE,
            conversation_id=conversation_id,
            quality_check=(
                quality_check.model_dump_json() if quality_check else None
            ),
        )
        db.add(history_record)
        db.commit()
        db.refresh(history_record)
        qa_id = history_record.id
    except Exception as e:
        logger.warning(f"保存问答历史失败（不影响回答）: {e}")
        db.rollback()

    # 5. 记录审计日志
    try:
        log_audit(
            db=db,
            user_id=current_user.id,
            username=current_user.username,
            action="ask",
            resource="qa",
            details={
                "question": request.question[:200],
                "confidence": result.confidence,
                "retriever_type": result.retriever_type,
                "sources_count": len(result.source_refs),
                "qa_id": qa_id,
                "conversation_id": conversation_id,
                "history_turns": len(history) // 2,
                "total_time": round(result.total_time, 3),
            },
        )
    except Exception as e:
        logger.warning(f"记录问答审计日志失败: {e}")

    # 6. 返回响应
    # 当 RobustQAPipeline 兜底返回错误结果时，confidence 为 "低" 且 sources 为空，
    # 此时标记 success=False 并回填 error 字段，便于前端识别
    is_fallback = result.confidence == "低" and not result.source_refs

    return QAResponse(
        success=not is_fallback,
        question=result.question,
        answer=result.answer,
        sources=source_refs,
        confidence=result.confidence,
        retriever_type=result.retriever_type,
        total_tokens=result.total_tokens,
        retrieval_time=round(result.retrieval_time, 3),
        llm_time=round(result.llm_time, 3),
        total_time=round(result.total_time, 3),
        qa_id=qa_id,
        conversation_id=conversation_id,
        quality_check=quality_check,
        error="问答链路异常，已返回兜底响应" if is_fallback else None,
    )


# ============================================================
# SSE 流式问答接口
# ============================================================

def _sse_event(event: str, data: dict) -> str:
    """格式化一个 SSE 事件"""
    # data 用 JSON 字符串，每个 SSE 行以 "data: " 前缀
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/ask/stream", summary="流式问答 (SSE)")
def ask_stream(
    request: QARequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    流式问答接口：通过 Server-Sent Events 逐字输出回答。

    **SSE 事件协议：**

    - `event: source` — 检索完成，data 含来源列表 `{sources, source_refs, retriever_type}`
    - `event: answer` — 逐字输出回答，data 为 `{content: "片段"}`
    - `event: done` — 流结束，data 含完整 `{answer, sources, total_time, qa_id, conversation_id}`
    - `event: error` — 异常，data 含 `{message}`

    **多轮对话：**
    请求体可携带 `conversation_id`，服务端会自动加载该会话历史作为上下文。
    `done` 事件中返回 `conversation_id`，前端应在后续提问中携带以维持上下文。

    **Postman 验证：**
    - Method: POST
    - Headers: `Authorization: Bearer <token>`, `Accept: text/event-stream`
    - Body: 同 /ask
    - 在 Postman 中需要禁用自动 JSON 解析，查看原始 SSE 文本流
    """
    # 解析会话 ID 与加载历史必须在路由处理器中完成（流开始前），
    # 之后通过闭包传入 event_generator
    conversation_id = _resolve_conversation_id(db, current_user.id, request.conversation_id)
    history = _load_conversation_history(db, current_user.id, conversation_id)

    logger.info(
        f"用户 {current_user.username} 流式提问: {request.question[:50]}... "
        f"(retriever={request.retriever_type or 'hybrid'}, top_k={request.top_k or 5}, "
        f"conversation={conversation_id}, history_turns={len(history)//2})"
    )

    def event_generator():
        start_time = time.time()
        pipeline = _build_pipeline(request)
        full_answer = ""
        sources_data = []
        source_refs_data = []
        retriever_type = request.retriever_type or "hybrid"

        try:
            for chunk in pipeline.ask_stream(
                question=request.question,
                filters=request.filters,
                top_k=request.top_k,
                template_type=request.template_type,
                history=history,
            ):
                if chunk.type == "source":
                    # 检索完成事件
                    sources_data = chunk.data.get("sources", []) if chunk.data else []
                    source_refs_data = (
                        chunk.data.get("source_refs", []) if chunk.data else []
                    )
                    retriever_type = (
                        chunk.data.get("retriever_type", retriever_type)
                        if chunk.data
                        else retriever_type
                    )
                    yield _sse_event("source", {
                        "message": chunk.content,
                        "sources": source_refs_data,
                        "retriever_type": retriever_type,
                        "sources_count": len(source_refs_data),
                    })

                elif chunk.type == "answer":
                    # 逐字输出事件
                    full_answer += chunk.content
                    yield _sse_event("answer", {"content": chunk.content})

            # 流正常结束，发送 done 事件
            total_time = round(time.time() - start_time, 3)

            # 质量自检（流式结束后对完整回答执行）
            quality_check_data = _run_quality_check(
                answer=full_answer,
                sources=source_refs_data,
                confidence="中",
            )

            # 持久化问答历史（带 conversation_id + quality_check）
            qa_id = None
            try:
                history_record = QAHistory(
                    user_id=current_user.id,
                    question=request.question,
                    answer=full_answer,
                    sources=json.dumps(source_refs_data, ensure_ascii=False)
                    if source_refs_data
                    else None,
                    feedback=FeedbackType.NONE,
                    conversation_id=conversation_id,
                    quality_check=(
                        quality_check_data.model_dump_json()
                        if quality_check_data
                        else None
                    ),
                )
                db.add(history_record)
                db.commit()
                db.refresh(history_record)
                qa_id = history_record.id
            except Exception as e:
                logger.warning(f"保存流式问答历史失败: {e}")
                db.rollback()

            quality_check_payload = (
                quality_check_data.model_dump() if quality_check_data else None
            )

            # 审计日志
            try:
                log_audit(
                    db=db,
                    user_id=current_user.id,
                    username=current_user.username,
                    action="ask_stream",
                    resource="qa",
                    details={
                        "question": request.question[:200],
                        "retriever_type": retriever_type,
                        "sources_count": len(source_refs_data),
                        "qa_id": qa_id,
                        "conversation_id": conversation_id,
                        "history_turns": len(history) // 2,
                        "total_time": total_time,
                        "answer_length": len(full_answer),
                        "quality_score": (
                            quality_check_data.score if quality_check_data else None
                        ),
                        "quality_passed": (
                            quality_check_data.passed if quality_check_data else None
                        ),
                    },
                )
            except Exception as e:
                logger.warning(f"记录流式审计日志失败: {e}")

            yield _sse_event("done", {
                "success": True,
                "answer_length": len(full_answer),
                "sources": source_refs_data,
                "retriever_type": retriever_type,
                "total_time": total_time,
                "qa_id": qa_id,
                "conversation_id": conversation_id,
                "quality_check": quality_check_payload,
            })

        except Exception as e:
            logger.error(f"流式问答异常: {e}", exc_info=True)
            total_time = round(time.time() - start_time, 3)
            yield _sse_event("error", {
                "message": f"流式问答异常: {str(e)}",
                "total_time": total_time,
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲，确保逐字输出
        },
    )


# ============================================================
# 问答历史查询接口
# ============================================================

def _parse_sources(sources_json: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """安全解析 sources 字段（JSON 字符串 → 列表）"""
    if not sources_json:
        return None
    try:
        parsed = json.loads(sources_json)
        return parsed if isinstance(parsed, list) else None
    except (json.JSONDecodeError, TypeError):
        return None


def _parse_quality_check(qc_json: Optional[str]) -> Optional[Dict[str, Any]]:
    """安全解析 quality_check 字段（JSON 字符串 → dict）"""
    if not qc_json:
        return None
    try:
        parsed = json.loads(qc_json)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


@router.get("/history", response_model=QAHistoryListResponse, summary="查询问答历史列表")
def list_history(
    page: int = Query(1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量（1-100）"),
    keyword: Optional[str] = Query(None, description="关键词搜索（匹配问题或回答）"),
    feedback: Optional[str] = Query(
        None, description="按反馈过滤: like / dislike / none"
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查询当前用户的问答历史列表（按时间倒序，分页）。

    - **page**: 页码，从 1 开始
    - **page_size**: 每页数量（1-100，默认 20）
    - **keyword**: 可选，在问题和回答中模糊搜索
    - **feedback**: 可选，按反馈类型过滤（like / dislike / none）

    只返回当前登录用户自己的历史记录。
    """
    # 构建查询：只查当前用户的历史
    query = db.query(QAHistory).filter(QAHistory.user_id == current_user.id)

    # 关键词搜索（同时匹配 question 和 answer）
    if keyword:
        kw = f"%{keyword}%"
        query = query.filter(
            or_(
                QAHistory.question.like(kw),
                QAHistory.answer.like(kw),
            )
        )

    # 反馈过滤
    if feedback:
        try:
            feedback_enum = FeedbackType(feedback)
            query = query.filter(QAHistory.feedback == feedback_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"无效的 feedback 值: {feedback}，可选: like / dislike / none",
            )

    # 总数
    total = query.count()

    # 分页（倒序）
    total_pages = (total + page_size - 1) // page_size if total > 0 else 0
    offset = (page - 1) * page_size
    items = (
        query.order_by(QAHistory.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    # 构造响应
    history_items = [
        QAHistoryItem(
            id=item.id,
            question=item.question,
            answer=item.answer,
            sources=_parse_sources(item.sources),
            feedback=item.feedback.value if item.feedback else "none",
            created_at=item.created_at.isoformat() if item.created_at else "",
        )
        for item in items
    ]

    return QAHistoryListResponse(
        success=True,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        items=history_items,
    )


@router.get("/history/{history_id}", response_model=QAHistoryDetailResponse, summary="查询问答历史详情")
def get_history_detail(
    history_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查询单条问答历史详情。

    只能查到当前登录用户自己的历史记录。若记录不存在或不属于当前用户，返回 404。
    """
    item = (
        db.query(QAHistory)
        .filter(
            QAHistory.id == history_id,
            QAHistory.user_id == current_user.id,
        )
        .first()
    )

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到历史记录 ID={history_id}，或该记录不属于当前用户",
        )

    return QAHistoryDetailResponse(
        success=True,
        id=item.id,
        question=item.question,
        answer=item.answer,
        sources=_parse_sources(item.sources),
        feedback=item.feedback.value if item.feedback else "none",
        created_at=item.created_at.isoformat() if item.created_at else "",
        username=current_user.username,
        quality_check=_parse_quality_check(item.quality_check),
    )


# ============================================================
# 问答反馈接口
# ============================================================

@router.post("/feedback/{qa_id}", response_model=FeedbackResponse, summary="提交问答反馈")
def submit_feedback(
    qa_id: int,
    request: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    对某条问答记录提交点赞 / 点踩 / 取消反馈。

    - **qa_id**: 问答历史记录 ID（URL 路径参数）
    - **feedback**: `like` / `dislike` / `none`（none 表示取消反馈）

    只能对自己的问答记录反馈。重复反馈会覆盖上一次的值。
    """
    # 1. 校验 feedback 值
    try:
        feedback_enum = FeedbackType(request.feedback)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"无效的 feedback 值: {request.feedback}，可选: like / dislike / none",
        )

    # 2. 查询记录（必须属于当前用户）
    item = (
        db.query(QAHistory)
        .filter(
            QAHistory.id == qa_id,
            QAHistory.user_id == current_user.id,
        )
        .first()
    )

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到问答记录 ID={qa_id}，或该记录不属于当前用户",
        )

    # 3. 记录旧值用于审计
    old_feedback = item.feedback.value if item.feedback else "none"

    # 4. 更新反馈
    item.feedback = feedback_enum
    try:
        db.commit()
        db.refresh(item)
    except Exception as e:
        db.rollback()
        logger.error(f"保存反馈失败: qa_id={qa_id}, feedback={request.feedback}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"保存反馈失败: {str(e)}",
        )

    # 5. 审计日志
    try:
        log_audit(
            db=db,
            user_id=current_user.id,
            username=current_user.username,
            action="feedback",
            resource="qa",
            details={
                "qa_id": qa_id,
                "old_feedback": old_feedback,
                "new_feedback": request.feedback,
            },
        )
    except Exception as e:
        logger.warning(f"记录反馈审计日志失败: {e}")

    # 6. 构造提示信息
    action_map = {
        "like": "点赞",
        "dislike": "点踩",
        "none": "取消反馈",
    }
    message = f"已{action_map.get(request.feedback, '更新')}问答记录 {qa_id}"

    logger.info(
        f"用户 {current_user.username} 对 qa_id={qa_id} 提交反馈: "
        f"{old_feedback} → {request.feedback}"
    )

    return FeedbackResponse(
        success=True,
        qa_id=qa_id,
        feedback=request.feedback,
        message=message,
    )


# ============================================================
# 多轮对话会话管理接口
# ============================================================

@router.get(
    "/conversations",
    response_model=ConversationListResponse,
    summary="查询会话列表（当前用户 / 全平台 admin 可选）",
)
def list_conversations(
    scope: str = Query("me", description="统计范围: me（仅自己）/ all（全平台，仅 admin 可选）"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查询会话列表（按最近更新倒序）。

    - **scope=me**（默认）：仅当前用户自己的会话
    - **scope=all**：全平台所有用户的会话，仅 admin 可选；非 admin 传 all 会被降级为 me

    每个会话由多条共享相同 `conversation_id` 的问答记录组成。
    返回字段中：
    - **title**: 取首条问题作为标题
    - **message_count**: 该会话的问答轮数
    - **last_question**: 最近一次提问（用于预览）
    - **created_at / updated_at**: 首条与最近一条记录的时间
    """
    from models.user import UserRole

    requested_scope = (scope or "me").strip().lower()
    is_admin = current_user.role == UserRole.ADMIN if current_user.role else False
    effective_scope = "all" if (requested_scope == "all" and is_admin) else "me"

    # 全平台模式不加 user_id 过滤；仅自己模式加 user_id 过滤
    user_filter = [] if effective_scope == "all" else [QAHistory.user_id == current_user.id]

    # 一次查询拿到每个会话的聚合信息：首条问题、最近问题、轮数、最早/最晚时间
    rows = (
        db.query(
            QAHistory.conversation_id,
            sa_func.count(QAHistory.id).label("message_count"),
            sa_func.min(QAHistory.created_at).label("created_at"),
            sa_func.max(QAHistory.created_at).label("updated_at"),
        )
        .filter(
            *user_filter,
            QAHistory.conversation_id.isnot(None),
        )
        .group_by(QAHistory.conversation_id)
        .order_by(desc("updated_at"))
        .all()
    )

    if not rows:
        return ConversationListResponse(success=True, total=0, items=[])

    # 批量取每个会话的首条问题和最近问题，避免 N+1
    conv_ids = [r.conversation_id for r in rows]

    # 首条问题（按时间最早）
    first_rows = (
        db.query(QAHistory.conversation_id, QAHistory.question)
        .filter(
            *user_filter,
            QAHistory.conversation_id.in_(conv_ids),
        )
        .order_by(QAHistory.created_at.asc())
        .all()
    )
    first_question_map: Dict[str, str] = {}
    for cid, q in first_rows:
        # 取第一条
        if cid not in first_question_map:
            first_question_map[cid] = q

    # 最近问题（按时间最晚）
    last_rows = (
        db.query(QAHistory.conversation_id, QAHistory.question)
        .filter(
            *user_filter,
            QAHistory.conversation_id.in_(conv_ids),
        )
        .order_by(QAHistory.created_at.desc())
        .all()
    )
    last_question_map: Dict[str, str] = {}
    for cid, q in last_rows:
        if cid not in last_question_map:
            last_question_map[cid] = q

    items = [
        ConversationItem(
            conversation_id=r.conversation_id,
            title=first_question_map.get(r.conversation_id, "")[:60],
            message_count=int(r.message_count),
            last_question=last_question_map.get(r.conversation_id, "")[:60],
            created_at=r.created_at.isoformat() if r.created_at else "",
            updated_at=r.updated_at.isoformat() if r.updated_at else "",
        )
        for r in rows
    ]

    return ConversationListResponse(success=True, total=len(items), items=items)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
    summary="查询会话详情（完整多轮对话）",
)
def get_conversation_detail(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查询某个会话的完整问答记录（按时间正序）。

    - 普通用户：只能查到自己的会话
    - **admin**：可查任意用户的会话（用于从反馈统计/审计跳转查看上下文）

    若会话不存在或不属于当前用户（且非 admin），返回 404。
    """
    from models.user import UserRole

    is_admin = current_user.role == UserRole.ADMIN if current_user.role else False

    # 普通用户加 user_id 过滤；admin 不加，可查任意会话
    if is_admin:
        records = (
            db.query(QAHistory)
            .filter(QAHistory.conversation_id == conversation_id)
            .order_by(QAHistory.created_at.asc())
            .all()
        )
    else:
        records = (
            db.query(QAHistory)
            .filter(
                QAHistory.conversation_id == conversation_id,
                QAHistory.user_id == current_user.id,
            )
            .order_by(QAHistory.created_at.asc())
            .all()
        )

    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到会话 {conversation_id}，或该会话不属于当前用户",
        )

    title = records[0].question[:60] if records else ""

    items = [
        ConversationMessageItem(
            id=item.id,
            question=item.question,
            answer=item.answer,
            sources=_parse_sources(item.sources),
            feedback=item.feedback.value if item.feedback else "none",
            created_at=item.created_at.isoformat() if item.created_at else "",
            quality_check=_parse_quality_check(item.quality_check),
        )
        for item in records
    ]

    # admin 模式额外返回 owner_username，便于前端展示「查看中：xxx 的会话」
    owner_username = ""
    if is_admin and records:
        owner = db.query(User).filter(User.id == records[0].user_id).first()
        owner_username = owner.username if owner else ""

    return ConversationDetailResponse(
        success=True,
        conversation_id=conversation_id,
        title=title,
        message_count=len(items),
        items=items,
        owner_username=owner_username,
    )


@router.delete(
    "/conversations/{conversation_id}",
    response_model=ConversationDeleteResponse,
    summary="删除会话（连同其全部问答记录）",
)
def delete_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    删除指定会话及其全部问答记录。

    只能删除当前登录用户自己的会话。若会话不存在或不属于当前用户，返回 404。
    删除后不可恢复。
    """
    # 先确认会话存在且属于当前用户
    records = (
        db.query(QAHistory)
        .filter(
            QAHistory.conversation_id == conversation_id,
            QAHistory.user_id == current_user.id,
        )
        .all()
    )

    if not records:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到会话 {conversation_id}，或该会话不属于当前用户",
        )

    deleted_count = len(records)

    # 审计日志（在删除前记录）
    try:
        log_audit(
            db=db,
            user_id=current_user.id,
            username=current_user.username,
            action="delete_conversation",
            resource="qa",
            details={
                "conversation_id": conversation_id,
                "deleted_count": deleted_count,
            },
        )
    except Exception as e:
        logger.warning(f"记录删除会话审计日志失败: {e}")

    # 执行删除
    for r in records:
        db.delete(r)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"删除会话失败: conversation_id={conversation_id}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除会话失败: {str(e)}",
        )

    logger.info(
        f"用户 {current_user.username} 删除会话 {conversation_id}（{deleted_count} 条记录）"
    )

    return ConversationDeleteResponse(
        success=True,
        conversation_id=conversation_id,
        deleted_count=deleted_count,
        message=f"已删除会话 {conversation_id}（共 {deleted_count} 条问答记录）",
    )


# ============================================================
# 反馈统计接口
# ============================================================

@router.get(
    "/feedback/stats",
    response_model=FeedbackStatsResponse,
    summary="查询反馈统计（当前用户 / 全平台 admin 可选）",
)
def get_feedback_stats(
    scope: str = Query("me", description="统计范围: me（仅自己）/ all（全平台，仅 admin 可选）"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查询反馈统计，让点赞/点踩数据产生实际价值。

    - **scope=me**（默认）：仅统计当前用户自己的数据，所有用户可用。
    - **scope=all**：统计全平台数据，仅 admin 角色可选；
      非 admin 传 all 会被强制降级为 me，避免越权。

    返回字段：
    - **total_qa**: 统计范围内的总问答数
    - **total_likes / total_dislikes / total_no_feedback**: 各反馈类型计数
    - **like_rate**: 好评率 = likes / (likes + dislikes)，0-1 之间
    - **top_disliked**: 差评问题列表（按时间倒序，最多 10 条），
      每项包含 conversation_id 与 username，前端可据此跳回原会话查看完整上下文
    """
    from models.user import UserRole

    # 1. 鉴权：scope=all 仅 admin 可用，其他用户强制降级为 me
    requested_scope = (scope or "me").strip().lower()
    is_admin = current_user.role == UserRole.ADMIN if current_user.role else False
    effective_scope = "all" if (requested_scope == "all" and is_admin) else "me"

    # 2. 构建查询过滤器
    if effective_scope == "all":
        base_filter = []  # 全平台：不加 user_id 过滤
    else:
        base_filter = [QAHistory.user_id == current_user.id]

    # 3. 按反馈类型分组计数
    rows = (
        db.query(QAHistory.feedback, sa_func.count(QAHistory.id))
        .filter(*base_filter)
        .group_by(QAHistory.feedback)
        .all()
    )

    total_qa = 0
    total_likes = 0
    total_dislikes = 0
    total_no_feedback = 0
    for fb, cnt in rows:
        cnt = int(cnt or 0)
        total_qa += cnt
        if fb == FeedbackType.LIKE:
            total_likes = cnt
        elif fb == FeedbackType.DISLIKE:
            total_dislikes = cnt
        else:
            total_no_feedback = cnt

    # 4. 好评率：避免分母为 0
    rated = total_likes + total_dislikes
    like_rate = round(total_likes / rated, 4) if rated > 0 else 0.0

    # 5. 差评问题 Top 10（按时间倒序）
    # 联表 users 取 username，便于 admin 识别来源
    disliked_query = (
        db.query(QAHistory, User.username)
        .outerjoin(User, QAHistory.user_id == User.id)
        .filter(QAHistory.feedback == FeedbackType.DISLIKE, *base_filter)
        .order_by(QAHistory.created_at.desc())
        .limit(10)
    )
    disliked_records = disliked_query.all()

    top_disliked = [
        FeedbackStatsItem(
            qa_id=item.id,
            question=item.question,
            answer=(item.answer or "")[:200],
            feedback="dislike",
            created_at=item.created_at.isoformat() if item.created_at else "",
            conversation_id=item.conversation_id,
            username=username or "",
        )
        for item, username in disliked_records
    ]

    logger.info(
        f"用户 {current_user.username} 查询反馈统计 (scope={effective_scope}): "
        f"total={total_qa}, likes={total_likes}, dislikes={total_dislikes}, "
        f"like_rate={like_rate}"
    )

    return FeedbackStatsResponse(
        success=True,
        scope=effective_scope,
        total_qa=total_qa,
        total_likes=total_likes,
        total_dislikes=total_dislikes,
        total_no_feedback=total_no_feedback,
        like_rate=like_rate,
        top_disliked=top_disliked,
    )
