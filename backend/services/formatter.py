"""
检索结果格式化服务
将检索结果整理为统一数据结构
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class RetrievedLog:
    """
    检索到的日志数据结构
    
    统一返回格式，包含日志原始信息和相似度分数
    """
    log_id: int
    level: str
    service: str
    timestamp: str
    message: str
    source: str
    score: float
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "log_id": self.log_id,
            "level": self.level,
            "service": self.service,
            "timestamp": self.timestamp,
            "message": self.message,
            "source": self.source,
            "score": round(self.score, 4),
        }
    
    def to_markdown(self) -> str:
        """转换为 Markdown 格式（用于 LLM Prompt）"""
        return f"""### 日志 #{self.log_id}
- **级别**: {self.level}
- **服务**: {self.service}
- **时间**: {self.timestamp}
- **来源**: {self.source}
- **内容**: {self.message}
- **相关性**: {self.score:.4f}
"""
    
    def to_evidence(self) -> str:
        """生成证据链字符串（用于 LLM Prompt）"""
        return f"[{self.timestamp}] [{self.level}] [{self.service}] {self.message}"


class ResultFormatter:
    """
    检索结果格式化器
    统一处理检索结果的格式化输出
    """
    
    @staticmethod
    def format_single(payload: Dict[str, Any], score: float) -> RetrievedLog:
        """
        格式化单条检索结果
        
        Args:
            payload: Qdrant 返回的 payload
            score: 相似度分数
        
        Returns:
            RetrievedLog: 格式化的日志对象
        """
        return RetrievedLog(
            log_id=payload.get('log_id', 0),
            level=payload.get('level', 'UNKNOWN'),
            service=payload.get('service', 'unknown'),
            timestamp=payload.get('timestamp', ''),
            message=payload.get('chunk_text', ''),
            source=payload.get('source', 'unknown'),
            score=score,
        )
    
    @staticmethod
    def format_batch(results: List[tuple]) -> List[RetrievedLog]:
        """
        批量格式化检索结果
        
        Args:
            results: [(score, payload), ...] 格式的检索结果
        
        Returns:
            List[RetrievedLog]: 格式化后的日志列表
        """
        formatted = []
        for score, payload in results:
            formatted.append(ResultFormatter.format_single(payload, score))
        return formatted
    
    @staticmethod
    def to_dict_list(results: List[RetrievedLog]) -> List[Dict[str, Any]]:
        """转换为字典列表（用于 API 返回）"""
        return [r.to_dict() for r in results]
    
    @staticmethod
    def to_evidence_text(results: List[RetrievedLog]) -> str:
        """
        生成证据文本（用于 LLM Prompt）
        
        Args:
            results: 格式化后的检索结果列表
        
        Returns:
            str: 证据文本，每条日志一行
        """
        if not results:
            return "未找到相关日志"
        
        evidence_lines = []
        for i, log in enumerate(results, 1):
            evidence_lines.append(f"{i}. {log.to_evidence()}")
        
        return "\n".join(evidence_lines)
    
    @staticmethod
    def to_markdown_text(results: List[RetrievedLog]) -> str:
        """
        生成 Markdown 格式文本（用于 LLM Prompt）
        
        Args:
            results: 格式化后的检索结果列表
        
        Returns:
            str: Markdown 格式的日志列表
        """
        if not results:
            return "未找到相关日志"
        
        return "\n\n".join([log.to_markdown() for log in results])
    
    @staticmethod
    def summarize(results: List[RetrievedLog]) -> Dict[str, Any]:
        """
        生成检索结果摘要
        
        Args:
            results: 格式化后的检索结果列表
        
        Returns:
            Dict: 摘要信息
        """
        if not results:
            return {
                "total": 0,
                "levels": {},
                "services": {},
                "avg_score": 0.0,
                "max_score": 0.0,
                "min_score": 0.0,
            }
        
        levels = {}
        services = {}
        scores = []
        
        for log in results:
            levels[log.level] = levels.get(log.level, 0) + 1
            services[log.service] = services.get(log.service, 0) + 1
            scores.append(log.score)
        
        return {
            "total": len(results),
            "levels": levels,
            "services": services,
            "avg_score": round(sum(scores) / len(scores), 4),
            "max_score": round(max(scores), 4),
            "min_score": round(min(scores), 4),
        }


# ============ 便捷函数 ============

def format_retrieval_results(
    results: List[tuple],
    include_summary: bool = False,
    include_evidence: bool = False,
    include_markdown: bool = False,
) -> Dict[str, Any]:
    """
    格式化检索结果（一站式函数）
    
    Args:
        results: [(score, payload), ...] 格式的检索结果
        include_summary: 是否包含摘要
        include_evidence: 是否包含证据文本
        include_markdown: 是否包含 Markdown 格式
    
    Returns:
        Dict: 包含所有格式化的结果
    """
    # 1. 基础格式化
    formatted = ResultFormatter.format_batch(results)
    
    # 2. 构建返回结果
    output = {
        "logs": ResultFormatter.to_dict_list(formatted),
        "count": len(formatted),
    }
    
    # 3. 可选：摘要
    if include_summary:
        output["summary"] = ResultFormatter.summarize(formatted)
    
    # 4. 可选：证据文本
    if include_evidence:
        output["evidence"] = ResultFormatter.to_evidence_text(formatted)
    
    # 5. 可选：Markdown
    if include_markdown:
        output["markdown"] = ResultFormatter.to_markdown_text(formatted)
    
    return output


def format_for_llm(results: List[tuple]) -> Dict[str, Any]:
    """
    专门为 LLM 格式化的结果
    
    Args:
        results: [(score, payload), ...] 格式的检索结果
    
    Returns:
        Dict: 包含证据文本和原始日志数据
    """
    formatted = ResultFormatter.format_batch(results)
    
    return {
        "logs": [r.to_dict() for r in formatted],
        "evidence": ResultFormatter.to_evidence_text(formatted),
        "markdown": ResultFormatter.to_markdown_text(formatted),
        "summary": ResultFormatter.summarize(formatted),
        "count": len(formatted),
    }