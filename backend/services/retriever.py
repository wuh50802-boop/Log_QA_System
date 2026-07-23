"""
向量检索服务 - 基于Qdrant的语义检索
支持Top-K检索、过滤条件、相似度阈值控制
适配 payload 结构: log_id, chunk_text, level, service, timestamp, source
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

from services.embedder import BGEEmbedder
from services.qdrant_client import get_qdrant_client, QdrantClientWrapper
from services.formatter import ResultFormatter, RetrievedLog, format_retrieval_results
from core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """检索结果数据类"""
    id: str
    payload: Dict[str, Any]
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为完整字典格式"""
        return {
            "id": self.id,
            "payload": self.payload,
            "score": round(self.score, 4),
            "metadata": self.metadata
        }
    
    def get_log_info(self) -> Dict[str, Any]:
        """提取日志关键信息（便于展示）"""
        return {
            "log_id": self.payload.get("log_id"),
            "level": self.payload.get("level"),
            "service": self.payload.get("service"),
            "timestamp": self.payload.get("timestamp"),
            "message": self.payload.get("chunk_text", ""),
            "source": self.payload.get("source"),
            "score": round(self.score, 4)
        }
    
    def to_retrieved_log(self) -> RetrievedLog:
        """转换为 RetrievedLog 对象（使用格式化器）"""
        return RetrievedLog(
            log_id=self.payload.get('log_id', 0),
            level=self.payload.get('level', 'UNKNOWN'),
            service=self.payload.get('service', 'unknown'),
            timestamp=self.payload.get('timestamp', ''),
            message=self.payload.get('chunk_text', ''),
            source=self.payload.get('source', 'unknown'),
            score=self.score,
        )


class LogRetriever:
    """日志向量检索器"""
    
    def __init__(
        self,
        embedder: Optional[BGEEmbedder] = None,
        client: Optional[QdrantClientWrapper] = None,
        top_k: int = 10,
        score_threshold: float = 0.0
    ):
        """
        初始化检索器
        
        Args:
            embedder: 嵌入模型实例
            client: Qdrant客户端封装实例
            top_k: 默认返回的Top-K数量
            score_threshold: 相似度阈值（低于此值的结果将被过滤）
        """
        self.embedder = embedder or BGEEmbedder()
        self.client = client or get_qdrant_client()
        self.top_k = top_k
        self.score_threshold = score_threshold
        
        # 检查集合是否存在
        self._ensure_collection_exists()
    
    def _ensure_collection_exists(self) -> bool:
        """确保集合存在"""
        try:
            info = self.client.get_collection_info()
            if info and info.get('vectors_count', 0) > 0:
                logger.info(f"✅ Collection 已就绪: {info['vectors_count']} 个向量")
                return True
            else:
                logger.warning("⚠️ Collection 为空或不存在，请先运行向量化脚本")
                return False
        except Exception as e:
            logger.warning(f"⚠️ 获取集合信息失败: {e}")
            return False
    
    def _build_filter_dict(
        self,
        level: Optional[str] = None,
        service: Optional[str] = None,
        source: Optional[str] = None,
        timestamp_before: Optional[str] = None,
        timestamp_after: Optional[str] = None,
        timestamp_between: Optional[Tuple[str, str]] = None,
        log_id: Optional[int] = None,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        构建Qdrant过滤条件字典

        适配 payload 字段: level, service, source, timestamp, log_id

        Args:
            level: 日志级别 (ERROR, INFO, WARNING, DEBUG)
            service: 服务名称 (如 auth-service)
            source: 来源 (如 auth-service)
            timestamp_before: 某时间之前 (如 "2026-07-18 01:20:38")
            timestamp_after: 某时间之后 (如 "2026-07-18 01:20:38")
            timestamp_between: 时间段 (开始时间, 结束时间)
            log_id: 日志ID
            **kwargs: 其他过滤字段

        Returns:
            过滤条件字典或None
        """
        conditions = []

        # 精确匹配字段
        if level:
            conditions.append({
                "key": "level",
                "match": {"value": level}
            })
        if service:
            conditions.append({
                "key": "service",
                "match": {"value": service}
            })
        if source:
            conditions.append({
                "key": "source",
                "match": {"value": source}
            })
        if log_id is not None:
            conditions.append({
                "key": "log_id",
                "match": {"value": log_id}
            })

        # 时间过滤（timestamp字段）
        if timestamp_between:
            # 时间段过滤
            start_time, end_time = timestamp_between
            conditions.append({
                "key": "timestamp",
                "range": {"gte": start_time, "lte": end_time}
            })
        elif timestamp_before:
            # 某时间之前
            conditions.append({
                "key": "timestamp",
                "range": {"lte": timestamp_before}
            })
        elif timestamp_after:
            # 某时间之后
            conditions.append({
                "key": "timestamp",
                "range": {"gte": timestamp_after}
            })

        # 其他动态字段（精确匹配）
        for key, value in kwargs.items():
            if value is not None:
                conditions.append({
                    "key": key,
                    "match": {"value": value}
                })

        if not conditions:
            return None

        # 返回 Qdrant Filter 字典格式
        return {"must": conditions}
    
    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        filter_params: Optional[Dict[str, Any]] = None,
        score_threshold: Optional[float] = None
    ) -> List[RetrievalResult]:
        """
        执行向量语义检索

        Args:
            query: 查询文本
            top_k: 返回结果数量（默认使用初始化值）
            filter_params: 过滤条件字典
                示例:
                - {"level": "ERROR", "service": "auth-service"}
                - {"timestamp_before": "2026-07-18 12:00:00"}
                - {"timestamp_after": "2026-07-18 00:00:00"}
                - {"timestamp_between": ("2026-07-18 00:00:00", "2026-07-18 23:59:59")}
            score_threshold: 相似度阈值

        Returns:
            RetrievalResult列表
        """
        if not query or not query.strip():
            logger.warning("查询文本为空")
            return []

        try:
            # 1. 生成查询向量 - 使用 encode_single 确保一维
            query_vector = self.embedder.encode_single(query)
            
            # 2. 确保向量是一维列表格式
            import numpy as np
            if isinstance(query_vector, np.ndarray):
                if len(query_vector.shape) == 2:
                    query_vector = query_vector.flatten()
                query_vector = query_vector.tolist()
            elif isinstance(query_vector, list):
                if len(query_vector) > 0 and isinstance(query_vector[0], list):
                    query_vector = query_vector[0]
            
            # 3. 验证维度
            if len(query_vector) != 768:
                logger.warning(f"向量维度异常: {len(query_vector)}，期望 768")
                if len(query_vector) > 768:
                    query_vector = query_vector[:768]
                elif len(query_vector) < 768:
                    query_vector = query_vector + [0.0] * (768 - len(query_vector))
            
            logger.debug(f"查询向量生成完成，维度: {len(query_vector)}")

            # 4. 构建过滤条件
            filter_dict = None
            if filter_params:
                filter_dict = self._build_filter_dict(**filter_params)
                logger.debug(f"应用过滤条件: {filter_params}")

            # 5. 执行检索
            top_k = top_k or self.top_k
            threshold = score_threshold if score_threshold is not None else self.score_threshold

            search_results = self.client.search(
                query_vector=query_vector,
                top_k=top_k,
                score_threshold=threshold if threshold > 0 else None,
                filter_conditions=filter_dict
            )

            # 6. 使用格式化器格式化结果
            results = []
            for score, payload in search_results:
                # 使用 ResultFormatter 格式化
                log = ResultFormatter.format_single(payload, score)
                result = RetrievalResult(
                    id=str(log.log_id),
                    payload=payload,
                    score=score,
                    metadata={
                        "log_id": log.log_id,
                        "level": log.level,
                        "service": log.service,
                        "timestamp": log.timestamp,
                        "message": log.message,
                        "source": log.source,
                    }
                )
                results.append(result)

            logger.info(f"检索完成，查询: '{query[:50]}...'，返回 {len(results)} 条结果")
            return results

        except Exception as e:
            logger.error(f"检索失败: {str(e)}", exc_info=True)
            return []
    
    def search_formatted(
        self,
        query: str,
        top_k: Optional[int] = None,
        filter_params: Optional[Dict[str, Any]] = None,
        score_threshold: Optional[float] = None,
        include_summary: bool = True,
        include_evidence: bool = True,
        include_markdown: bool = False,
    ) -> Dict[str, Any]:
        """
        执行检索并返回格式化结果（含摘要、证据等）
        
        Args:
            query: 查询文本
            top_k: 返回结果数量
            filter_params: 过滤条件字典
            score_threshold: 相似度阈值
            include_summary: 是否包含摘要
            include_evidence: 是否包含证据文本
            include_markdown: 是否包含 Markdown 格式
        
        Returns:
            Dict: 包含格式化结果的字典
        """
        # 执行检索
        results = self.search(query, top_k, filter_params, score_threshold)
        
        # 转换为 (score, payload) 格式
        raw_results = [(r.score, r.payload) for r in results]
        
        # 使用格式化器
        return format_retrieval_results(
            raw_results,
            include_summary=include_summary,
            include_evidence=include_evidence,
            include_markdown=include_markdown,
        )
    
    def search_by_level(
        self,
        query: str,
        level: str,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None
    ) -> List[RetrievalResult]:
        """
        按日志级别过滤检索
        
        Args:
            query: 查询文本
            level: 日志级别 (ERROR, INFO, WARNING, DEBUG)
            top_k: 返回结果数量
            score_threshold: 相似度阈值
            
        Returns:
            RetrievalResult列表
        """
        return self.search(
            query=query,
            top_k=top_k,
            filter_params={"level": level},
            score_threshold=score_threshold
        )
    
    def search_by_service(
        self,
        query: str,
        service: str,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None
    ) -> List[RetrievalResult]:
        """
        按服务名称过滤检索
        
        Args:
            query: 查询文本
            service: 服务名称
            top_k: 返回结果数量
            score_threshold: 相似度阈值
            
        Returns:
            RetrievalResult列表
        """
        return self.search(
            query=query,
            top_k=top_k,
            filter_params={"service": service},
            score_threshold=score_threshold
        )
    
    def search_by_time(
        self,
        query: str,
        before: Optional[str] = None,
        after: Optional[str] = None,
        between: Optional[Tuple[str, str]] = None,
        top_k: Optional[int] = None,
        score_threshold: Optional[float] = None
    ) -> List[RetrievalResult]:
        """
        按时间过滤检索

        Args:
            query: 查询文本
            before: 某时间之前 (如 "2026-07-18 12:00:00")
            after: 某时间之后 (如 "2026-07-18 00:00:00")
            between: 时间段 (开始时间, 结束时间)
            top_k: 返回结果数量
            score_threshold: 相似度阈值

        Returns:
            RetrievalResult列表
        """
        filter_params = {}
        if before:
            filter_params['timestamp_before'] = before
        if after:
            filter_params['timestamp_after'] = after
        if between:
            filter_params['timestamp_between'] = between

        return self.search(
            query=query,
            top_k=top_k,
            filter_params=filter_params if filter_params else None,
            score_threshold=score_threshold
        )
    
    def search_batch(
        self,
        queries: List[str],
        top_k: Optional[int] = None,
        filter_params: Optional[Dict[str, Any]] = None,
        score_threshold: Optional[float] = None
    ) -> List[List[RetrievalResult]]:
        """
        批量检索（多个查询）
        
        Args:
            queries: 查询文本列表
            top_k: 每个查询返回结果数量
            filter_params: 过滤条件
            score_threshold: 相似度阈值
            
        Returns:
            每个查询对应的结果列表
        """
        results = []
        for query in queries:
            result = self.search(
                query=query,
                top_k=top_k,
                filter_params=filter_params,
                score_threshold=score_threshold
            )
            results.append(result)
        return results
    
    def search_by_vector(
        self,
        vector: List[float],
        top_k: Optional[int] = None,
        filter_params: Optional[Dict[str, Any]] = None,
        score_threshold: Optional[float] = None
    ) -> List[RetrievalResult]:
        """
        直接使用向量进行检索
        
        Args:
            vector: 查询向量
            top_k: 返回结果数量
            filter_params: 过滤条件
            score_threshold: 相似度阈值
            
        Returns:
            RetrievalResult列表
        """
        try:
            top_k = top_k or self.top_k
            threshold = score_threshold if score_threshold is not None else self.score_threshold

            filter_dict = None
            if filter_params:
                filter_dict = self._build_filter_dict(**filter_params)

            search_results = self.client.search(
                query_vector=vector,
                top_k=top_k,
                score_threshold=threshold if threshold > 0 else None,
                filter_conditions=filter_dict
            )

            results = []
            for score, payload in search_results:
                log = ResultFormatter.format_single(payload, score)
                result = RetrievalResult(
                    id=str(log.log_id),
                    payload=payload,
                    score=score,
                    metadata={
                        "log_id": log.log_id,
                        "level": log.level,
                        "service": log.service,
                        "timestamp": log.timestamp,
                        "message": log.message,
                        "source": log.source,
                    }
                )
                results.append(result)

            return results

        except Exception as e:
            logger.error(f"向量检索失败: {str(e)}", exc_info=True)
            return []
    
    def count_vectors(self) -> int:
        """获取向量总数"""
        try:
            return self.client.count()
        except Exception as e:
            logger.error(f"获取向量数量失败: {e}")
            return 0


# 单例实例
retriever = LogRetriever()


def get_retriever() -> LogRetriever:
    """获取检索器单例"""
    return retriever


# 便捷函数
def search_logs(
    query: str,
    top_k: int = 10,
    level: Optional[str] = None,
    service: Optional[str] = None,
    source: Optional[str] = None,
    timestamp_before: Optional[str] = None,
    timestamp_after: Optional[str] = None,
    timestamp_between: Optional[Tuple[str, str]] = None,
    score_threshold: float = 0.0
) -> List[Dict[str, Any]]:
    """
    便捷检索函数 - 返回格式化的字典列表

    Args:
        query: 查询文本
        top_k: 返回数量
        level: 日志级别过滤 (ERROR, INFO, WARNING, DEBUG)
        service: 服务名称过滤
        source: 来源过滤
        timestamp_before: 某时间之前 (如 "2026-07-18 12:00:00")
        timestamp_after: 某时间之后 (如 "2026-07-18 00:00:00")
        timestamp_between: 时间段 (开始时间, 结束时间)
        score_threshold: 相似度阈值

    Returns:
        检索结果字典列表，每个字典包含 log_id, level, service, timestamp, message, source, score
    """
    filter_params = {}
    if level:
        filter_params['level'] = level
    if service:
        filter_params['service'] = service
    if source:
        filter_params['source'] = source
    if timestamp_before:
        filter_params['timestamp_before'] = timestamp_before
    if timestamp_after:
        filter_params['timestamp_after'] = timestamp_after
    if timestamp_between:
        filter_params['timestamp_between'] = timestamp_between

    results = retriever.search(
        query=query,
        top_k=top_k,
        filter_params=filter_params if filter_params else None,
        score_threshold=score_threshold
    )

    # 返回格式化后的日志信息
    return [r.get_log_info() for r in results]


def search_logs_formatted(
    query: str,
    top_k: int = 10,
    level: Optional[str] = None,
    service: Optional[str] = None,
    source: Optional[str] = None,
    timestamp_before: Optional[str] = None,
    timestamp_after: Optional[str] = None,
    timestamp_between: Optional[Tuple[str, str]] = None,
    score_threshold: float = 0.0,
    include_summary: bool = True,
    include_evidence: bool = True,
    include_markdown: bool = False,
) -> Dict[str, Any]:
    """
    便捷检索函数 - 返回格式化结果（含摘要、证据等）
    
    Args:
        query: 查询文本
        top_k: 返回数量
        level: 日志级别过滤
        service: 服务名称过滤
        source: 来源过滤
        timestamp_before: 某时间之前
        timestamp_after: 某时间之后
        timestamp_between: 时间段
        score_threshold: 相似度阈值
        include_summary: 是否包含摘要
        include_evidence: 是否包含证据文本
        include_markdown: 是否包含 Markdown 格式
    
    Returns:
        Dict: 包含格式化结果的字典
    """
    filter_params = {}
    if level:
        filter_params['level'] = level
    if service:
        filter_params['service'] = service
    if source:
        filter_params['source'] = source
    if timestamp_before:
        filter_params['timestamp_before'] = timestamp_before
    if timestamp_after:
        filter_params['timestamp_after'] = timestamp_after
    if timestamp_between:
        filter_params['timestamp_between'] = timestamp_between

    return retriever.search_formatted(
        query=query,
        top_k=top_k,
        filter_params=filter_params if filter_params else None,
        score_threshold=score_threshold,
        include_summary=include_summary,
        include_evidence=include_evidence,
        include_markdown=include_markdown,
    )

