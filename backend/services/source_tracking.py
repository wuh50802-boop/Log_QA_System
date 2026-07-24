"""
来源溯源模块 - 在回答中标注引用的日志来源
支持双向追溯：回答 → 日志，日志 → 回答
"""

from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
import re
import json
import hashlib


@dataclass
class SourceReference:
    """单个来源引用"""
    ref_id: str  # 引用ID，如 [1], [2]
    log_id: int
    service: str
    timestamp: str
    level: str
    content: str
    score: float = 0.0
    snippet: str = ""  # 引用的具体片段
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "ref_id": self.ref_id,
            "log_id": self.log_id,
            "service": self.service,
            "timestamp": self.timestamp,
            "level": self.level,
            "content": self.content[:500] if len(self.content) > 500 else self.content,
            "score": self.score,
            "snippet": self.snippet
        }
    
    def to_markdown(self) -> str:
        """转换为 Markdown 格式"""
        return (
            f"[{self.ref_id}] **{self.service}** | "
            f"{self.level} | {self.timestamp}\n"
            f"> {self.snippet or self.content[:200]}"
        )


@dataclass
class SourceAnnotatedAnswer:
    """带来源标注的回答"""
    question: str
    answer: str  # 带标注的完整回答
    sources: List[SourceReference] = field(default_factory=list)
    confidence: str = "中"
    total_tokens: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "sources": [s.to_dict() for s in self.sources],
            "confidence": self.confidence,
            "total_tokens": self.total_tokens
        }
    
    def to_markdown(self) -> str:
        """转换为 Markdown 格式"""
        md = f"## {self.question}\n\n"
        md += self.answer + "\n\n"
        
        if self.sources:
            md += "---\n\n### 📎 来源引用\n\n"
            for source in self.sources:
                md += source.to_markdown() + "\n\n"
        
        md += f"\n**置信度**: {self.confidence}"
        return md


class SourceTracker:
    """
    来源追踪器
    管理回答中的引用标注和溯源
    """
    
    def __init__(self):
        self.ref_counter = 0
        self.references: Dict[str, SourceReference] = {}
        self.log_to_refs: Dict[int, List[str]] = {}  # log_id -> ref_ids
    
    def add_source(
        self,
        log_id: int,
        service: str,
        timestamp: str,
        level: str,
        content: str,
        snippet: Optional[str] = None,
        score: float = 0.0
    ) -> str:
        """
        添加一个来源，返回引用ID
        """
        self.ref_counter += 1
        ref_id = f"[{self.ref_counter}]"
        
        # 如果没有指定 snippet，取内容的前100字符
        if snippet is None:
            snippet = content[:100] + "..." if len(content) > 100 else content
        
        ref = SourceReference(
            ref_id=ref_id,
            log_id=log_id,
            service=service,
            timestamp=timestamp,
            level=level,
            content=content,
            snippet=snippet,
            score=score
        )
        
        self.references[ref_id] = ref
        
        # 建立 log_id -> ref_id 映射
        if log_id not in self.log_to_refs:
            self.log_to_refs[log_id] = []
        self.log_to_refs[log_id].append(ref_id)
        
        return ref_id
    
    def get_ref(self, ref_id: str) -> Optional[SourceReference]:
        """获取引用"""
        return self.references.get(ref_id)
    
    def get_refs_for_log(self, log_id: int) -> List[SourceReference]:
        """获取某个日志的所有引用"""
        ref_ids = self.log_to_refs.get(log_id, [])
        return [self.references[rid] for rid in ref_ids if rid in self.references]
    
    def annotate_answer(self, answer: str) -> str:
        """
        为回答添加引用标注
        自动检测并替换 [ID:xxx] 格式为 [n]
        """
        # 查找所有 [ID:xxx] 格式的引用
        pattern = r'\[ID:(\d+)\]'
        matches = re.findall(pattern, answer)
        
        # 为每个找到的 log_id 分配引用编号
        log_to_ref = {}
        for log_id_str in matches:
            log_id = int(log_id_str)
            if log_id not in log_to_ref:
                # 查找是否已有该 log 的引用
                existing_refs = self.get_refs_for_log(log_id)
                if existing_refs:
                    ref_id = existing_refs[0].ref_id
                else:
                    # 需要从其他地方获取日志信息
                    # 这里假设调用者会先 add_source
                    ref_id = f"[?{log_id}]"
                log_to_ref[log_id] = ref_id
        
        # 替换 [ID:xxx] 为 [n]
        def replace_ref(match):
            log_id = int(match.group(1))
            return log_to_ref.get(log_id, match.group(0))
        
        annotated = re.sub(pattern, replace_ref, answer)
        
        return annotated
    
    def get_reference_list(self) -> List[SourceReference]:
        """获取所有引用列表（按编号排序）"""
        # 按 ref_id 排序
        ref_ids = sorted(self.references.keys(), key=lambda x: int(x[1:-1]))
        return [self.references[rid] for rid in ref_ids]
    
    def format_reference_list(self, format_type: str = "markdown") -> str:
        """格式化引用列表"""
        refs = self.get_reference_list()
        
        if format_type == "markdown":
            lines = ["### 来源引用"]
            for ref in refs:
                lines.append(f"- **{ref.ref_id}** `{ref.service}` | {ref.level} | {ref.timestamp}")
                lines.append(f"  > {ref.snippet}")
            return "\n".join(lines)
        
        elif format_type == "json":
            return json.dumps([r.to_dict() for r in refs], ensure_ascii=False, indent=2)
        
        elif format_type == "text":
            lines = ["来源引用:"]
            for ref in refs:
                lines.append(f"  {ref.ref_id} {ref.service} | {ref.level} | {ref.timestamp}")
                lines.append(f"    {ref.snippet}")
            return "\n".join(lines)
        
        return ""
    
    def clear(self):
        """清空追踪器"""
        self.ref_counter = 0
        self.references = {}
        self.log_to_refs = {}


class SourceAwareQAPipeline:
    """
    支持来源溯源的问答流水线
    包装 QAPipeline，自动添加引用标注
    """
    
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.tracker = SourceTracker()
        self.last_answer: Optional[SourceAnnotatedAnswer] = None
    
    def ask(
        self,
        question: str,
        filters: Optional[Dict[str, Any]] = None,
        top_k: Optional[int] = None,
        template_type: Optional[str] = None
    ) -> SourceAnnotatedAnswer:
        """
        带来源溯源的问答
        """
        # 清空追踪器
        self.tracker.clear()
        
        # 执行问答
        result = self.pipeline.ask(
            question=question,
            filters=filters,
            top_k=top_k,
            template_type=template_type
        )
        
        # 提取来源并建立引用
        sources = []
        for source in result.sources:
            log_id = source.get('log_id')
            if log_id:
                ref_id = self.tracker.add_source(
                    log_id=log_id,
                    service=source.get('service', 'unknown'),
                    timestamp=source.get('timestamp', ''),
                    level=source.get('level', 'INFO'),
                    content=source.get('content', ''),
                    score=source.get('score', 0.0)
                )
                sources.append(self.tracker.get_ref(ref_id))
        
        # 标注回答
        annotated_answer = self.tracker.annotate_answer(result.answer)
        
        # 构建带来源的回答
        annotated_result = SourceAnnotatedAnswer(
            question=question,
            answer=annotated_answer,
            sources=sources,
            confidence=result.confidence,
            total_tokens=result.total_tokens
        )
        
        self.last_answer = annotated_result
        return annotated_result
    
    def ask_stream(self, question: str, **kwargs):
        """
        流式问答（来源信息在开始时发送）
        """
        # 清空追踪器
        self.tracker.clear()
        
        # 先执行检索（流式开始时需要知道来源）
        # 这里简化处理，实际可以改为流式输出来源信息
        for chunk in self.pipeline.ask_stream(question, **kwargs):
            if chunk.type == "source":
                # 提取来源信息
                sources_data = chunk.data.get('sources', [])
                for source in sources_data:
                    log_id = source.get('log_id')
                    if log_id:
                        self.tracker.add_source(
                            log_id=log_id,
                            service=source.get('service', 'unknown'),
                            timestamp=source.get('timestamp', ''),
                            level=source.get('level', 'INFO'),
                            content=source.get('content', ''),
                            score=source.get('score', 0.0)
                        )
                yield chunk
            
            elif chunk.type == "answer":
                yield chunk
    
    def get_last_answer(self) -> Optional[SourceAnnotatedAnswer]:
        """获取最后一次回答"""
        return self.last_answer
    
    def get_source_trace(self, ref_id: str) -> Optional[SourceReference]:
        """根据引用ID获取来源详情"""
        return self.tracker.get_ref(ref_id)
    
    def get_sources_for_log(self, log_id: int) -> List[SourceReference]:
        """根据日志ID获取所有引用"""
        return self.tracker.get_refs_for_log(log_id)
    
    def get_all_sources(self) -> List[SourceReference]:
        """获取所有来源"""
        return self.tracker.get_reference_list()


def create_source_aware_pipeline(
    top_k: int = 5,
    retriever_type: str = "hybrid",
    template_type: str = "evidence_chain"
) -> SourceAwareQAPipeline:
    """
    创建支持来源溯源的问答流水线
    """
    from .qa_pipeline import create_pipeline
    
    pipeline = create_pipeline(
        top_k=top_k,
        template_type=template_type,
        retriever_type=retriever_type
    )
    
    return SourceAwareQAPipeline(pipeline)