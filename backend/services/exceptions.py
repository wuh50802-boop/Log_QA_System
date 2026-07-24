"""
自定义异常类
用于问答系统中的各种异常情况
"""

from typing import Optional, Dict, Any


class QASystemError(Exception):
    """问答系统基础异常"""
    def __init__(self, message: str, error_code: str = "QA_ERROR", details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(message)


class NoSearchResultsError(QASystemError):
    """检索无结果异常"""
    def __init__(self, query: str, filters: Optional[Dict[str, Any]] = None):
        message = f"未找到与 '{query}' 相关的日志"
        if filters:
            message += f"（过滤条件: {filters}）"
        super().__init__(
            message=message,
            error_code="NO_SEARCH_RESULTS",
            details={"query": query, "filters": filters}
        )


class LLMTimeoutError(QASystemError):
    """LLM超时异常"""
    def __init__(self, timeout: float = 30.0):
        super().__init__(
            message=f"LLM 请求超时（{timeout}s），请稍后重试",
            error_code="LLM_TIMEOUT",
            details={"timeout": timeout}
        )


class LLMServiceError(QASystemError):
    """LLM服务异常"""
    def __init__(self, original_error: str):
        super().__init__(
            message=f"LLM 服务暂时不可用: {original_error}",
            error_code="LLM_SERVICE_ERROR",
            details={"original_error": original_error}
        )


class RetrieverError(QASystemError):
    """检索器异常"""
    def __init__(self, retriever_type: str, original_error: str):
        super().__init__(
            message=f"检索服务暂时不可用（{retriever_type}）",
            error_code="RETRIEVER_ERROR",
            details={"retriever_type": retriever_type, "original_error": original_error}
        )


class InvalidQueryError(QASystemError):
    """无效查询异常"""
    def __init__(self, query: str):
        super().__init__(
            message="查询内容为空或无效，请输入有效的问题",
            error_code="INVALID_QUERY",
            details={"query": query}
        )


class RateLimitError(QASystemError):
    """限流异常"""
    def __init__(self, retry_after: int = 60):
        super().__init__(
            message=f"请求过于频繁，请在 {retry_after} 秒后重试",
            error_code="RATE_LIMIT",
            details={"retry_after": retry_after}
        )


class ConversationNotFoundError(QASystemError):
    """对话不存在异常"""
    def __init__(self, conversation_id: str):
        super().__init__(
            message=f"对话 {conversation_id} 不存在",
            error_code="CONVERSATION_NOT_FOUND",
            details={"conversation_id": conversation_id}
        )