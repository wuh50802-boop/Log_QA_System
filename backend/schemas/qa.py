from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class QARequest(BaseModel):
    """问答请求"""
    question: str = Field(..., min_length=1, max_length=500, description="用户问题")
    filters: Optional[Dict[str, Any]] = Field(
        None, description="检索过滤条件，如 {level, service, source}"
    )
    top_k: Optional[int] = Field(None, ge=1, le=50, description="检索返回的日志数量")
    template_type: Optional[str] = Field(
        None, description="Prompt 模板类型: evidence_chain / quick / short"
    )
    retriever_type: Optional[str] = Field(
        None, description="检索器类型: vector / bm25 / hybrid（默认 hybrid）"
    )
    conversation_id: Optional[str] = Field(
        None,
        description="会话 ID。传已有的 ID 表示继续多轮对话；不传或为空表示开启新会话",
    )


class QASourceRef(BaseModel):
    """来源引用"""
    ref_id: str = Field(..., description="引用编号，如 [1]")
    log_id: Optional[int] = Field(None, description="日志 ID")
    service: str = Field("unknown", description="服务名")
    timestamp: str = Field("", description="日志时间")
    level: str = Field("INFO", description="日志级别")
    content: str = Field("", description="日志内容（截断）")
    score: float = Field(0.0, description="相关性分数")
    snippet: str = Field("", description="引用片段")


class QAQualityIssue(BaseModel):
    """质量检查中的单条问题/警告"""
    type: str = Field(..., description="类型: issue / warning")
    message: str = Field(..., description="问题描述")
    penalty: float = Field(0.0, description="扣分")
    suggestion: Optional[str] = Field(None, description="改进建议")


class QAQualityCheck(BaseModel):
    """回答质量自检结果"""
    passed: bool = Field(True, description="是否通过（score >= 70 且无 issue）")
    score: float = Field(100.0, description="质量得分 0-100，越高越好")
    issues: List[QAQualityIssue] = Field(
        default_factory=list, description="问题列表（严重，会阻断通过）"
    )
    warnings: List[str] = Field(
        default_factory=list, description="警告列表（提示性）"
    )
    suggestions: List[str] = Field(
        default_factory=list, description="改进建议列表"
    )


class QAResponse(BaseModel):
    """问答响应"""
    success: bool = Field(True, description="是否成功")
    question: str = Field(..., description="原始问题")
    answer: str = Field(..., description="回答（带来源标注）")
    sources: List[QASourceRef] = Field(
        default_factory=list, description="来源引用列表"
    )
    confidence: str = Field("中", description="置信度: 高 / 中 / 低")
    retriever_type: str = Field("hybrid", description="使用的检索器类型")
    total_tokens: int = Field(0, description="LLM 消耗的 token 数")
    retrieval_time: float = Field(0.0, description="检索耗时（秒）")
    llm_time: float = Field(0.0, description="LLM 调用耗时（秒）")
    total_time: float = Field(0.0, description="总耗时（秒）")
    qa_id: Optional[int] = Field(None, description="问答历史记录 ID")
    conversation_id: Optional[str] = Field(
        None, description="会话 ID（前端应在后续提问中携带以维持多轮上下文）"
    )
    quality_check: Optional[QAQualityCheck] = Field(
        None, description="回答质量自检结果（含分数、问题、警告、建议）"
    )
    error: Optional[str] = Field(None, description="错误信息（失败时）")


# ============================================================
# 问答历史查询
# ============================================================

class QAHistoryItem(BaseModel):
    """单条问答历史"""
    id: int = Field(..., description="历史记录 ID")
    question: str = Field(..., description="用户问题")
    answer: str = Field(..., description="系统回答")
    sources: Optional[List[Dict[str, Any]]] = Field(
        None, description="引用的日志来源列表"
    )
    feedback: str = Field("none", description="用户反馈: like / dislike / none")
    created_at: str = Field(..., description="提问时间（ISO 格式）")


class QAHistoryListResponse(BaseModel):
    """问答历史列表响应"""
    success: bool = Field(True, description="是否成功")
    total: int = Field(..., description="历史记录总数（符合过滤条件）")
    page: int = Field(..., description="当前页码（从 1 开始）")
    page_size: int = Field(..., description="每页大小")
    total_pages: int = Field(..., description="总页数")
    items: List[QAHistoryItem] = Field(
        default_factory=list, description="历史记录列表（按时间倒序）"
    )


class QAHistoryDetailResponse(BaseModel):
    """单条问答历史详情响应"""
    success: bool = Field(True, description="是否成功")
    id: int = Field(..., description="历史记录 ID")
    question: str = Field(..., description="用户问题")
    answer: str = Field(..., description="系统回答")
    sources: Optional[List[Dict[str, Any]]] = Field(
        None, description="引用的日志来源列表"
    )
    feedback: str = Field("none", description="用户反馈")
    created_at: str = Field(..., description="提问时间")
    username: str = Field(..., description="提问用户名")
    quality_check: Optional[Dict[str, Any]] = Field(
        None, description="回答质量自检结果（含 passed/score/issues/warnings/suggestions）"
    )


# ============================================================
# 问答反馈
# ============================================================

class FeedbackRequest(BaseModel):
    """反馈请求"""
    feedback: str = Field(
        ...,
        description="反馈类型: like / dislike / none（none 表示取消反馈）",
    )


class FeedbackResponse(BaseModel):
    """反馈响应"""
    success: bool = Field(True, description="是否成功")
    qa_id: int = Field(..., description="问答历史记录 ID")
    feedback: str = Field(..., description="当前反馈状态: like / dislike / none")
    message: str = Field("", description="提示信息")


# ============================================================
# 多轮对话会话管理
# ============================================================

class ConversationItem(BaseModel):
    """会话列表项（一个会话包含多条 Q&A）"""
    conversation_id: str = Field(..., description="会话 ID")
    title: str = Field("", description="会话标题（取首条问题）")
    message_count: int = Field(0, description="该会话的问答轮数")
    last_question: str = Field("", description="最近一次提问（用于预览）")
    created_at: str = Field("", description="会话首条记录时间（ISO 格式）")
    updated_at: str = Field("", description="会话最近记录时间（ISO 格式）")


class ConversationListResponse(BaseModel):
    """会话列表响应"""
    success: bool = Field(True, description="是否成功")
    total: int = Field(..., description="会话总数")
    items: List[ConversationItem] = Field(
        default_factory=list, description="会话列表（按最近更新倒序）"
    )


class ConversationMessageItem(BaseModel):
    """会话详情中的单条 Q&A"""
    id: int = Field(..., description="问答历史记录 ID")
    question: str = Field(..., description="用户问题")
    answer: str = Field(..., description="系统回答")
    sources: Optional[List[Dict[str, Any]]] = Field(
        None, description="引用的日志来源列表"
    )
    feedback: str = Field("none", description="用户反馈: like / dislike / none")
    created_at: str = Field(..., description="提问时间（ISO 格式）")
    quality_check: Optional[Dict[str, Any]] = Field(
        None, description="回答质量自检结果（含 passed/score/issues/warnings/suggestions）"
    )


class ConversationDetailResponse(BaseModel):
    """会话详情响应（包含完整多轮对话）"""
    success: bool = Field(True, description="是否成功")
    conversation_id: str = Field(..., description="会话 ID")
    title: str = Field("", description="会话标题")
    message_count: int = Field(0, description="问答轮数")
    items: List[ConversationMessageItem] = Field(
        default_factory=list, description="该会话的全部 Q&A（按时间正序）"
    )
    owner_username: str = Field(
        "", description="会话所有者用户名（admin 查看他人会话时返回，便于显示「查看中：xxx」）"
    )


class ConversationDeleteResponse(BaseModel):
    """会话删除响应"""
    success: bool = Field(True, description="是否成功")
    conversation_id: str = Field(..., description="被删除的会话 ID")
    deleted_count: int = Field(..., description="删除的问答记录数")
    message: str = Field("", description="提示信息")


# ============================================================
# 反馈统计
# ============================================================

class FeedbackStatsItem(BaseModel):
    """差评问题 Top 项"""
    qa_id: int = Field(..., description="问答记录 ID")
    question: str = Field(..., description="用户问题")
    answer: str = Field("", description="系统回答（截断）")
    feedback: str = Field("dislike", description="反馈类型")
    created_at: str = Field("", description="提问时间")
    conversation_id: Optional[str] = Field(
        None, description="所属会话 ID（前端可据此跳回原会话查看完整上下文）"
    )
    username: str = Field("", description="提问用户名（scope=all 时返回，便于 admin 识别来源）")


class FeedbackStatsResponse(BaseModel):
    """反馈统计响应"""
    success: bool = Field(True, description="是否成功")
    scope: str = Field("me", description="统计范围: me（仅自己）/ all（全平台，仅 admin 可选）")
    total_qa: int = Field(0, description="统计范围内的总问答数")
    total_likes: int = Field(0, description="总点赞数")
    total_dislikes: int = Field(0, description="总点踩数")
    total_no_feedback: int = Field(0, description="未反馈数")
    like_rate: float = Field(0.0, description="好评率 = likes / (likes + dislikes)，0-1 之间")
    top_disliked: List[FeedbackStatsItem] = Field(
        default_factory=list, description="差评问题列表（按时间倒序，最多 10 条）"
    )
