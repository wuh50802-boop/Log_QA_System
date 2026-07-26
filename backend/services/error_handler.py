"""
异常处理模块
统一处理问答系统中的各种异常，返回友好提示
"""

import logging
import time
from typing import Optional, Dict, Any, Callable, TypeVar, Union
from functools import wraps
from dataclasses import dataclass, field
from .qa_pipeline import QAResult, StreamChunk
from .exceptions import (
    QASystemError,
    NoSearchResultsError,
    LLMTimeoutError,
    LLMServiceError,
    RetrieverError,
    InvalidQueryError,
    RateLimitError,
    ConversationNotFoundError
)

logger = logging.getLogger(__name__)

T = TypeVar('T')


@dataclass
class ErrorResponse:
    """错误响应"""
    success: bool = False
    error_code: str = ""
    message: str = ""
    suggestions: list = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "error_code": self.error_code,
            "message": self.message,
            "suggestions": self.suggestions,
            "details": self.details
        }


class ErrorHandler:
    """
    统一错误处理器
    将异常转换为友好的错误响应
    """
    
    def __init__(self):
        self.error_count = 0
        self.error_history: list = []
    
    def handle(self, error: Exception, context: Optional[Dict[str, Any]] = None) -> ErrorResponse:
        """
        处理异常，返回友好的错误响应
        """
        self.error_count += 1
        self.error_history.append({
            "error": str(error),
            "type": type(error).__name__,
            "time": time.time(),
            "context": context or {}
        })
        
        # 处理已知异常
        if isinstance(error, NoSearchResultsError):
            return self._handle_no_results(error)
        elif isinstance(error, LLMTimeoutError):
            return self._handle_timeout(error)
        elif isinstance(error, LLMServiceError):
            return self._handle_llm_error(error)
        elif isinstance(error, RetrieverError):
            return self._handle_retriever_error(error)
        elif isinstance(error, InvalidQueryError):
            return self._handle_invalid_query(error)
        elif isinstance(error, RateLimitError):
            return self._handle_rate_limit(error)
        elif isinstance(error, ConversationNotFoundError):
            return self._handle_conversation_not_found(error)
        elif isinstance(error, QASystemError):
            return self._handle_qa_error(error)
        else:
            return self._handle_unknown_error(error)
    
    def _handle_no_results(self, error: NoSearchResultsError) -> ErrorResponse:
        """处理检索无结果"""
        query = error.details.get('query', '')
        filters = error.details.get('filters', {})
        
        suggestions = [
            "尝试使用更宽泛的关键词",
            "检查过滤条件是否过于严格",
            "确认日志数据是否已导入",
        ]
        
        if filters:
            suggestions.append(f"尝试移除或放宽过滤条件: {filters}")
        
        return ErrorResponse(
            error_code=error.error_code,
            message=error.message,
            suggestions=suggestions,
            details={
                "query": query,
                "filters": filters,
                "retriever_type": error.details.get('retriever_type', 'unknown')
            }
        )
    
    def _handle_timeout(self, error: LLMTimeoutError) -> ErrorResponse:
        """处理LLM超时"""
        timeout = error.details.get('timeout', 30)
        
        suggestions = [
            "稍后重试，系统可能正在处理其他请求",
            "尝试使用更简短的查询",
            "检查网络连接是否稳定",
        ]
        
        return ErrorResponse(
            error_code=error.error_code,
            message=error.message,
            suggestions=suggestions,
            details={"timeout": timeout}
        )
    
    def _handle_llm_error(self, error: LLMServiceError) -> ErrorResponse:
        """处理LLM服务异常"""
        suggestions = [
            "稍后重试",
            "检查API密钥是否有效",
            "联系系统管理员"
        ]
        
        return ErrorResponse(
            error_code=error.error_code,
            message=error.message,
            suggestions=suggestions,
            details={"original_error": error.details.get('original_error', '')}
        )
    
    def _handle_retriever_error(self, error: RetrieverError) -> ErrorResponse:
        """处理检索器异常"""
        retriever_type = error.details.get('retriever_type', 'unknown')
        
        suggestions = [
            "尝试使用其他检索方式",
            "检查索引是否已构建",
            "稍后重试"
        ]
        
        if retriever_type == 'vector':
            suggestions.insert(0, "尝试使用关键词检索（BM25）")
        elif retriever_type == 'bm25':
            suggestions.insert(0, "尝试使用向量检索")
        
        return ErrorResponse(
            error_code=error.error_code,
            message=error.message,
            suggestions=suggestions,
            details={"retriever_type": retriever_type}
        )
    
    def _handle_invalid_query(self, error: InvalidQueryError) -> ErrorResponse:
        """处理无效查询"""
        suggestions = [
            "输入具体的问题，如'数据库连接超时是什么原因？'",
            "描述您遇到的问题或现象",
            "输入至少2个字符的关键词"
        ]
        
        return ErrorResponse(
            error_code=error.error_code,
            message=error.message,
            suggestions=suggestions,
            details={"query": error.details.get('query', '')}
        )
    
    def _handle_rate_limit(self, error: RateLimitError) -> ErrorResponse:
        """处理限流"""
        retry_after = error.details.get('retry_after', 60)
        
        suggestions = [
            f"等待 {retry_after} 秒后重试",
            "减少并发请求数量"
        ]
        
        return ErrorResponse(
            error_code=error.error_code,
            message=error.message,
            suggestions=suggestions,
            details={"retry_after": retry_after}
        )
    
    def _handle_conversation_not_found(self, error: ConversationNotFoundError) -> ErrorResponse:
        """处理对话不存在"""
        conversation_id = error.details.get('conversation_id', '')
        
        suggestions = [
            "创建新的对话",
            "检查对话ID是否正确"
        ]
        
        return ErrorResponse(
            error_code=error.error_code,
            message=error.message,
            suggestions=suggestions,
            details={"conversation_id": conversation_id}
        )
    
    def _handle_qa_error(self, error: QASystemError) -> ErrorResponse:
        """处理其他QA系统异常"""
        suggestions = [
            "稍后重试",
            "尝试使用不同的表述方式",
            "联系系统管理员"
        ]
        
        return ErrorResponse(
            error_code=error.error_code,
            message=error.message,
            suggestions=suggestions,
            details=error.details
        )
    
    def _handle_unknown_error(self, error: Exception) -> ErrorResponse:
        """处理未知异常"""
        logger.error(f"未知异常: {error}", exc_info=True)
        
        return ErrorResponse(
            error_code="UNKNOWN_ERROR",
            message="系统暂时无法处理您的请求，请稍后重试",
            suggestions=[
                "刷新页面后重试",
                "检查网络连接",
                "如果问题持续，联系技术支持"
            ],
            details={"error_type": type(error).__name__}
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """获取错误统计"""
        return {
            "total_errors": self.error_count,
            "recent_errors": self.error_history[-10:] if self.error_history else [],
            "last_error": self.error_history[-1] if self.error_history else None
        }


# ============================================================
# 装饰器 - 自动处理异常
# ============================================================

def handle_errors(
    fallback_message: str = "系统暂时无法处理您的请求",
    log_error: bool = True
):
    """
    异常处理装饰器
    自动捕获并处理异常，返回友好的错误响应
    
    Args:
        fallback_message: 默认错误消息
        log_error: 是否记录错误日志
    """
    def decorator(func: Callable[..., T]) -> Callable[..., Union[T, ErrorResponse]]:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if log_error:
                    logger.error(f"函数 {func.__name__} 执行失败: {e}", exc_info=True)
                
                handler = ErrorHandler()
                return handler.handle(e)
        return wrapper
    return decorator


# ============================================================
# 集成到 QAPipeline
# ============================================================

class RobustQAPipeline:
    """
    健壮的问答流水线
    包装 QAPipeline，自动处理各种异常
    """
    
    def __init__(self, pipeline, error_handler: Optional[ErrorHandler] = None):
        self.pipeline = pipeline
        self.error_handler = error_handler or ErrorHandler()
    
    def ask(self, question: str, **kwargs):
        """
        带异常处理的问答
        """
        from .qa_pipeline import QAResult
        
        # 验证查询
        if not question or not question.strip():
            error = InvalidQueryError(question)
            error_response = self.error_handler.handle(error)
            return self._error_response_to_qa_result(question, error_response)
        
        try:
            # 执行问答
            result = self.pipeline.ask(question, **kwargs)
            return result
            
        except Exception as e:
            # 捕获所有异常，返回友好提示
            error_response = self.error_handler.handle(e, context={"question": question})
            return self._error_response_to_qa_result(question, error_response)
    
    def _error_response_to_qa_result(self, question: str, error_response: ErrorResponse) -> 'QAResult':
        """
        将 ErrorResponse 转换为 QAResult
        """
        from .qa_pipeline import QAResult
        
        # 构建友好的回答
        friendly_answer = self._build_friendly_answer(error_response)
        
        return QAResult(
            question=question,
            answer=friendly_answer,
            sources=[],
            confidence="低",
            total_tokens=0,
            retrieval_time=0,
            llm_time=0,
            total_time=0,
            retriever_type=self.pipeline.retriever_type if hasattr(self.pipeline, 'retriever_type') else "unknown"
        )
    
    def _build_friendly_answer(self, error_response: ErrorResponse) -> str:
        """构建友好的错误回答"""
        parts = [
            f"❌ {error_response.message}",
            "",
            "💡 **建议：**"
        ]
        
        for i, suggestion in enumerate(error_response.suggestions, 1):
            parts.append(f"{i}. {suggestion}")
        
        return "\n".join(parts)
    
    def ask_stream(self, question: str, **kwargs):
        """
        流式问答 + 异常处理
        """
        try:
            for chunk in self.pipeline.ask_stream(question, **kwargs):
                yield chunk
        except Exception as e:
            error_response = self.error_handler.handle(e, context={"question": question})
            
            # 返回错误信息
            friendly_message = self._build_friendly_answer(error_response)
            from .qa_pipeline import StreamChunk
            yield StreamChunk(
                type="answer",
                content=f"\n\n{friendly_message}"
            )
    
    def get_error_stats(self) -> Dict[str, Any]:
        """获取错误统计"""
        return self.error_handler.get_stats()
    
    def clear_error_history(self):
        """清除错误历史"""
        self.error_handler.error_history = []
        self.error_handler.error_count = 0


def create_robust_pipeline(
    top_k: int = 5,
    retriever_type: str = "hybrid",
    template_type: str = "evidence_chain",
    timeout: float = 30.0,
    rerank: bool = False,
    rerank_model: Optional[str] = None,
    rerank_candidate_k: int = 20,
    vector_weight: float = 1.0,
    bm25_weight: float = 1.0,
) -> RobustQAPipeline:
    """
    创建健壮的问答流水线

    Args:
        top_k: 检索返回的日志数量
        retriever_type: 检索器类型 (vector, bm25, hybrid)
        template_type: Prompt 模板类型
        timeout: 超时时间
        rerank: 是否启用 Cross-Encoder 重排序
        rerank_model: 重排序模型名称
        rerank_candidate_k: 重排序候选数
        vector_weight: 混合检索向量权重
        bm25_weight: 混合检索 BM25 权重
    """
    from .qa_pipeline import create_pipeline

    pipeline = create_pipeline(
        top_k=top_k,
        template_type=template_type,
        retriever_type=retriever_type,
        rerank=rerank,
        rerank_model=rerank_model,
        rerank_candidate_k=rerank_candidate_k,
        vector_weight=vector_weight,
        bm25_weight=bm25_weight,
    )

    return RobustQAPipeline(pipeline)