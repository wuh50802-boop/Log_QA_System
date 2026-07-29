"""
混合检索器 - RRF 融合重排 (异步版本)
融合三种检索：
    - 向量检索（Qdrant）：语义相似
    - BM25 检索（索引文件）：关键词匹配
    - SQLite LIKE（数据库）：精确子串匹配（专门处理具体标识符）
使用 asyncio 并行执行三路检索，提高性能
"""
import logging
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

from services.retriever import LogRetriever, RetrievalResult
from services.bm25_retriever import bm25_search, get_bm25_retriever
from services.sqlite_retriever import sqlite_search, get_sqlite_retriever
from services.formatter import ResultFormatter, RetrievedLog

logger = logging.getLogger(__name__)


@dataclass
class HybridResult:
    """混合检索结果"""
    log_id: int
    payload: Dict[str, Any]
    vector_score: float = 0.0
    bm25_score: float = 0.0
    sqlite_score: float = 0.0
    rrf_score: float = 0.0
    vector_rank: int = 0
    bm25_rank: int = 0
    sqlite_rank: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "log_id": self.log_id,
            "level": self.payload.get('level'),
            "service": self.payload.get('service'),
            "timestamp": self.payload.get('timestamp'),
            "message": self.payload.get('chunk_text', ''),
            "source": self.payload.get('source'),
            "vector_score": round(self.vector_score, 4),
            "bm25_score": round(self.bm25_score, 4),
            "sqlite_score": round(self.sqlite_score, 4),
            "rrf_score": round(self.rrf_score, 4),
            "vector_rank": self.vector_rank,
            "bm25_rank": self.bm25_rank,
            "sqlite_rank": self.sqlite_rank,
            "metadata": self.metadata,
        }
    
    def get_log_info(self) -> Dict[str, Any]:
        return {
            "log_id": self.log_id,
            "level": self.payload.get('level'),
            "service": self.payload.get('service'),
            "timestamp": self.payload.get('timestamp'),
            "message": self.payload.get('chunk_text', ''),
            "source": self.payload.get('source'),
            "score": round(self.rrf_score, 4),
        }


class HybridRetrieverAsync:
    """
    异步混合检索器 - RRF 融合重排
    
    使用 asyncio 并行执行向量检索和 BM25 检索
    """
    
    def __init__(
        self,
        k: int = 60,
        top_k: int = 10,
        vector_weight: float = 1.0,
        bm25_weight: float = 1.0,
        sqlite_weight: float = 1.0,
        max_workers: int = 3,
    ):
        self.k = k
        self.top_k = top_k
        self.vector_weight = vector_weight
        self.bm25_weight = bm25_weight
        self.sqlite_weight = sqlite_weight
        self.max_workers = max_workers
        
        # 初始化检索器（延迟初始化，避免阻塞）
        self._vector_retriever = None
        self._bm25_retriever = None
        self._sqlite_retriever = None
        
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        
        logger.info(f"✅ HybridRetrieverAsync 初始化完成")
        logger.info(f"   k={k}, top_k={top_k}, max_workers={max_workers}")
        logger.info(f"   weights: vector={vector_weight}, bm25={bm25_weight}, sqlite={sqlite_weight}")
    
    @property
    def vector_retriever(self):
        """延迟初始化向量检索器"""
        if self._vector_retriever is None:
            self._vector_retriever = LogRetriever()
        return self._vector_retriever
    
    @property
    def bm25_retriever(self):
        """延迟初始化 BM25 检索器"""
        if self._bm25_retriever is None:
            self._bm25_retriever = get_bm25_retriever()
        return self._bm25_retriever
    
    @property
    def sqlite_retriever(self):
        """延迟初始化 SQLite 检索器"""
        if self._sqlite_retriever is None:
            self._sqlite_retriever = get_sqlite_retriever()
        return self._sqlite_retriever
    
    def _rrf_score(self, rank: int) -> float:
        """计算 RRF 分数"""
        return 1.0 / (self.k + rank)
    
    async def _search_vector_async(
        self,
        query: str,
        top_k: int,
        filter_params: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievalResult]:
        """
        异步执行向量检索
        使用 run_in_executor 将同步方法转为异步
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self.vector_retriever.search,
            query,
            top_k,
            filter_params,
        )
    
    async def _search_bm25_async(
        self,
        query: str,
        top_k: int,
        filter_params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        异步执行 BM25 检索
        使用 run_in_executor 将同步方法转为异步
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            bm25_search,
            query,
            top_k,
            filter_params.get('level') if filter_params else None,
            filter_params.get('service') if filter_params else None,
            filter_params.get('source') if filter_params else None,
        )
    
    async def _search_sqlite_async(
        self,
        query: str,
        top_k: int,
        filter_params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        异步执行 SQLite 精确匹配检索
        使用 run_in_executor 将同步方法转为异步
        
        如果查询中无标识符，SQLite 检索器内部会返回空列表，不影响其他检索。
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            sqlite_search,
            query,
            top_k,
            filter_params,
        )
    
    async def search_async(
        self,
        query: str,
        top_k: Optional[int] = None,
        filter_params: Optional[Dict[str, Any]] = None,
        vector_top_k: Optional[int] = None,
        bm25_top_k: Optional[int] = None,
        sqlite_top_k: Optional[int] = None,
    ) -> List[HybridResult]:
        """
        异步执行混合检索（RRF 融合三路检索）
        
        Args:
            query: 查询文本
            top_k: 最终返回结果数量
            filter_params: 过滤条件
            vector_top_k: 向量检索返回数量
            bm25_top_k: BM25 检索返回数量
            sqlite_top_k: SQLite 检索返回数量
        
        Returns:
            HybridResult 列表
        """
        if not query or not query.strip():
            logger.warning("查询文本为空")
            return []
        
        top_k = top_k or self.top_k
        vector_top_k = vector_top_k or top_k * 3
        bm25_top_k = bm25_top_k or top_k * 3
        sqlite_top_k = sqlite_top_k or top_k * 2  # SQLite 精确匹配，少取一些
        
        logger.info(f"🔍 执行异步混合检索: '{query[:50]}...'")
        logger.info(f"   向量 Top-{vector_top_k}, BM25 Top-{bm25_top_k}, SQLite Top-{sqlite_top_k}")
        
        try:
            # ============ 并行执行三路检索 ============
            logger.debug("🚀 并行执行向量检索、BM25 检索、SQLite 检索...")
            
            vector_task = self._search_vector_async(
                query, vector_top_k, filter_params
            )
            bm25_task = self._search_bm25_async(
                query, bm25_top_k, filter_params
            )
            sqlite_task = self._search_sqlite_async(
                query, sqlite_top_k, filter_params
            )
            
            # 等待三个任务完成
            vector_results, bm25_results, sqlite_results = await asyncio.gather(
                vector_task, bm25_task, sqlite_task,
                return_exceptions=True
            )
            
            # 处理异常
            if isinstance(vector_results, Exception):
                logger.error(f"向量检索失败: {vector_results}")
                vector_results = []
            if isinstance(bm25_results, Exception):
                logger.error(f"BM25 检索失败: {bm25_results}")
                bm25_results = []
            if isinstance(sqlite_results, Exception):
                logger.error(f"SQLite 检索失败: {sqlite_results}")
                sqlite_results = []
            
            logger.debug(f"向量检索返回 {len(vector_results)} 条结果")
            logger.debug(f"BM25 检索返回 {len(bm25_results)} 条结果")
            logger.debug(f"SQLite 检索返回 {len(sqlite_results)} 条结果")
            
        except Exception as e:
            logger.error(f"检索执行失败: {e}")
            return []
        
        # ============ RRF 融合 ============
        result_map: Dict[int, HybridResult] = {}
        
        # 处理向量检索结果
        for rank, result in enumerate(vector_results, 1):
            log_id = result.payload.get('log_id')
            if log_id is None:
                continue
            
            if log_id not in result_map:
                result_map[log_id] = HybridResult(
                    log_id=log_id,
                    payload=result.payload,
                )
            
            result_map[log_id].vector_score = result.score
            result_map[log_id].vector_rank = rank
        
        # 处理 BM25 检索结果
        for rank, result in enumerate(bm25_results, 1):
            log_id = result.get('log_id')
            if log_id is None:
                continue
            
            payload = result.get('payload', {})
            
            if log_id not in result_map:
                result_map[log_id] = HybridResult(
                    log_id=log_id,
                    payload=payload,
                )
            
            result_map[log_id].bm25_score = result.get('score', 0)
            result_map[log_id].bm25_rank = rank
        
        # 处理 SQLite 精确匹配结果
        for rank, result in enumerate(sqlite_results, 1):
            log_id = result.get('log_id')
            if log_id is None:
                continue
            
            payload = result.get('payload', {})
            
            if log_id not in result_map:
                result_map[log_id] = HybridResult(
                    log_id=log_id,
                    payload=payload,
                )
            
            result_map[log_id].sqlite_score = result.get('score', 0)
            result_map[log_id].sqlite_rank = rank
        
        # 计算 RRF 分数
        for hybrid_result in result_map.values():
            rrf_score = 0.0
            
            if hybrid_result.vector_rank > 0:
                rrf_score += self.vector_weight * self._rrf_score(hybrid_result.vector_rank)
            
            if hybrid_result.bm25_rank > 0:
                rrf_score += self.bm25_weight * self._rrf_score(hybrid_result.bm25_rank)
            
            if hybrid_result.sqlite_rank > 0:
                rrf_score += self.sqlite_weight * self._rrf_score(hybrid_result.sqlite_rank)
            
            hybrid_result.rrf_score = rrf_score
        
        # 排序并返回 Top-K
        sorted_results = sorted(
            result_map.values(),
            key=lambda x: x.rrf_score,
            reverse=True
        )
        
        final_results = sorted_results[:top_k]
        
        logger.info(f"✅ 异步混合检索完成，返回 {len(final_results)} 条结果")
        if final_results:
            logger.info(f"   最高 RRF 分数: {final_results[0].rrf_score:.4f}")
        
        return final_results
    
    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        filter_params: Optional[Dict[str, Any]] = None,
        vector_top_k: Optional[int] = None,
        bm25_top_k: Optional[int] = None,
        sqlite_top_k: Optional[int] = None,
    ) -> List[HybridResult]:
        """
        同步接口 - 内部调用异步方法
        """
        return asyncio.run(
            self.search_async(query, top_k, filter_params, vector_top_k, bm25_top_k, sqlite_top_k)
        )
    
    def search_formatted(
        self,
        query: str,
        top_k: Optional[int] = None,
        filter_params: Optional[Dict[str, Any]] = None,
        include_summary: bool = True,
        include_evidence: bool = True,
    ) -> Dict[str, Any]:
        """
        同步格式化检索
        """
        results = self.search(query, top_k, filter_params)
        
        retrieved_logs = []
        for r in results:
            log = RetrievedLog(
                log_id=r.log_id,
                level=r.payload.get('level', 'UNKNOWN'),
                service=r.payload.get('service', 'unknown'),
                timestamp=r.payload.get('timestamp', ''),
                message=r.payload.get('chunk_text', ''),
                source=r.payload.get('source', 'unknown'),
                score=r.rrf_score,
            )
            retrieved_logs.append(log)
        
        output = {
            "logs": [log.to_dict() for log in retrieved_logs],
            "count": len(retrieved_logs),
        }
        
        if include_summary:
            output["summary"] = ResultFormatter.summarize(retrieved_logs)
        
        if include_evidence:
            output["evidence"] = ResultFormatter.to_evidence_text(retrieved_logs)
        
        return output
    
    async def search_formatted_async(
        self,
        query: str,
        top_k: Optional[int] = None,
        filter_params: Optional[Dict[str, Any]] = None,
        include_summary: bool = True,
        include_evidence: bool = True,
    ) -> Dict[str, Any]:
        """
        异步格式化检索
        """
        results = await self.search_async(query, top_k, filter_params)
        
        retrieved_logs = []
        for r in results:
            log = RetrievedLog(
                log_id=r.log_id,
                level=r.payload.get('level', 'UNKNOWN'),
                service=r.payload.get('service', 'unknown'),
                timestamp=r.payload.get('timestamp', ''),
                message=r.payload.get('chunk_text', ''),
                source=r.payload.get('source', 'unknown'),
                score=r.rrf_score,
            )
            retrieved_logs.append(log)
        
        output = {
            "logs": [log.to_dict() for log in retrieved_logs],
            "count": len(retrieved_logs),
        }
        
        if include_summary:
            output["summary"] = ResultFormatter.summarize(retrieved_logs)
        
        if include_evidence:
            output["evidence"] = ResultFormatter.to_evidence_text(retrieved_logs)
        
        return output
    
    def close(self):
        """关闭线程池"""
        if self._executor:
            self._executor.shutdown(wait=True)
    
    def __del__(self):
        self.close()


# ============ 单例 ============
_hybrid_retriever_async: Optional[HybridRetrieverAsync] = None


def get_hybrid_retriever_async(
    k: int = 60,
    top_k: int = 10,
    vector_weight: float = 1.0,
    bm25_weight: float = 1.0,
    max_workers: int = 2,
) -> HybridRetrieverAsync:
    """获取异步混合检索器单例"""
    global _hybrid_retriever_async
    if _hybrid_retriever_async is None:
        _hybrid_retriever_async = HybridRetrieverAsync(
            k=k,
            top_k=top_k,
            vector_weight=vector_weight,
            bm25_weight=bm25_weight,
            max_workers=max_workers,
        )
    return _hybrid_retriever_async


# ============ 便捷函数 ============

def hybrid_search_async(
    query: str,
    top_k: int = 10,
    level: Optional[str] = None,
    service: Optional[str] = None,
    source: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    便捷异步混合检索函数（同步接口）
    """
    filter_params = {}
    if level:
        filter_params['level'] = level
    if service:
        filter_params['service'] = service
    if source:
        filter_params['source'] = source
    
    retriever = get_hybrid_retriever_async()
    results = retriever.search(
        query=query,
        top_k=top_k,
        filter_params=filter_params if filter_params else None,
    )
    
    return [r.to_dict() for r in results]


async def hybrid_search_async_only(
    query: str,
    top_k: int = 10,
    level: Optional[str] = None,
    service: Optional[str] = None,
    source: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    纯异步混合检索函数
    """
    filter_params = {}
    if level:
        filter_params['level'] = level
    if service:
        filter_params['service'] = service
    if source:
        filter_params['source'] = source
    
    retriever = get_hybrid_retriever_async()
    results = await retriever.search_async(
        query=query,
        top_k=top_k,
        filter_params=filter_params if filter_params else None,
    )
    
    return [r.to_dict() for r in results]