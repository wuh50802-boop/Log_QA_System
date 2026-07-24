"""
问答流水线 - 将检索 + Prompt + LLM 串联为完整流水线
端到端可运行
"""

import time
import logging
import re
from typing import List, Dict, Any, Optional, Generator, Union
from dataclasses import dataclass, field

from .llm_client import DeepSeekClient, ChatMessage
from .prompt_templates import PromptTemplates, build_qa_prompt
from .retriever import LogRetriever, RetrievalResult
from .bm25_retriever import get_bm25_retriever, BM25Result
from .hybrid_retriever import get_hybrid_retriever_async, HybridResult


logger = logging.getLogger(__name__)


@dataclass
class SourceReference:
    """来源引用 - 用于溯源"""
    ref_id: str  # 引用ID，如 [1]
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
            "snippet": self.snippet or self.content[:100] + "..."
        }


@dataclass
class QAResult:
    """问答结果"""
    question: str
    answer: str
    sources: List[Dict[str, Any]] = field(default_factory=list)
    source_refs: List[SourceReference] = field(default_factory=list)  # 带标注的来源
    confidence: str = "中"
    total_tokens: int = 0
    retrieval_time: float = 0.0
    llm_time: float = 0.0
    total_time: float = 0.0
    retriever_type: str = "hybrid"
    
    def get_annotated_answer(self) -> str:
        """获取带来源标注的回答"""
        return self.answer
    
    def get_sources_with_refs(self) -> List[Dict[str, Any]]:
        """获取带引用ID的来源列表"""
        return [ref.to_dict() for ref in self.source_refs]
    
    def get_source_by_ref(self, ref_id: str) -> Optional[SourceReference]:
        """根据引用ID获取来源"""
        for ref in self.source_refs:
            if ref.ref_id == ref_id:
                return ref
        return None
    
    def get_source_by_log_id(self, log_id: int) -> List[SourceReference]:
        """根据日志ID获取所有引用"""
        return [ref for ref in self.source_refs if ref.log_id == log_id]
    
    def to_markdown(self) -> str:
        """转换为 Markdown 格式"""
        md = f"## {self.question}\n\n"
        md += self.answer + "\n\n"
        
        if self.source_refs:
            md += "---\n\n### 📎 来源引用\n\n"
            for ref in self.source_refs:
                md += f"**{ref.ref_id}** `{ref.service}` | {ref.level} | {ref.timestamp}\n"
                md += f"> {ref.snippet or ref.content[:100]}...\n\n"
        
        md += f"\n**置信度**: {self.confidence}"
        return md


@dataclass
class StreamChunk:
    """流式输出块"""
    type: str  # 'source', 'answer', 'source_ref'
    content: str
    data: Optional[Dict[str, Any]] = None


class QAPipeline:
    """问答流水线"""

    def __init__(
        self,
        top_k: int = 5,
        template_type: str = "evidence_chain",
        retriever_type: str = "hybrid",
        max_log_length: int = 300
    ):
        """
        初始化问答流水线

        Args:
            top_k: 检索返回的日志数量
            template_type: Prompt 模板类型 (evidence_chain, quick, analysis)
            retriever_type: 检索器类型 (vector, bm25, hybrid)
            max_log_length: 每条日志的最大长度
        """
        self.top_k = top_k
        self.template_type = template_type
        self.retriever_type = retriever_type
        self.max_log_length = max_log_length
        
        # 初始化检索器
        self._init_retriever(retriever_type)
        
        self.llm_client = DeepSeekClient()
        self.conversation_history: List[Dict[str, str]] = []

    def _init_retriever(self, retriever_type: str):
        """初始化检索器"""
        if retriever_type == "vector":
            self.retriever = LogRetriever(top_k=self.top_k)
            self._search_method = self._search_vector
        elif retriever_type == "bm25":
            self.retriever = get_bm25_retriever()
            self._search_method = self._search_bm25
        else:  # hybrid
            self.retriever = get_hybrid_retriever_async(top_k=self.top_k)
            self._search_method = self._search_hybrid

    def _search_vector(
        self,
        query: str,
        top_k: int,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """向量检索"""
        results = self.retriever.search(
            query=query,
            top_k=top_k,
            filter_params=filters
        )
        return self._convert_vector_results(results)

    def _search_bm25(
        self,
        query: str,
        top_k: int,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """BM25 关键词检索"""
        level = filters.get('level') if filters else None
        service = filters.get('service') if filters else None
        source = filters.get('source') if filters else None
        
        results = self.retriever.search(
            query=query,
            top_k=top_k,
            filter_level=level,
            filter_service=service,
            filter_source=source
        )
        return self._convert_bm25_results(results)

    def _search_hybrid(
        self,
        query: str,
        top_k: int,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """混合检索"""
        results = self.retriever.search(
            query=query,
            top_k=top_k,
            filter_params=filters
        )
        return self._convert_hybrid_results(results)

    def _convert_vector_results(self, results: List[RetrievalResult]) -> List[Dict[str, Any]]:
        """转换向量检索结果为统一格式"""
        converted = []
        for r in results:
            converted.append({
                "log_id": r.payload.get('log_id'),
                "service": r.payload.get('service', 'unknown'),
                "timestamp": r.payload.get('timestamp', ''),
                "level": r.payload.get('level', 'INFO'),
                "content": r.payload.get('chunk_text', ''),
                "score": r.score,
                "source": r.payload.get('source', 'unknown')
            })
        return converted

    def _convert_bm25_results(self, results: List[BM25Result]) -> List[Dict[str, Any]]:
        """转换 BM25 检索结果为统一格式"""
        converted = []
        for r in results:
            payload = r.payload
            converted.append({
                "log_id": r.log_id,
                "service": payload.get('service', 'unknown'),
                "timestamp": payload.get('timestamp', ''),
                "level": payload.get('level', 'INFO'),
                "content": payload.get('chunk_text', ''),
                "score": r.score,
                "source": payload.get('source', 'unknown')
            })
        return converted

    def _convert_hybrid_results(self, results: List[HybridResult]) -> List[Dict[str, Any]]:
        """转换混合检索结果为统一格式"""
        converted = []
        for r in results:
            payload = r.payload
            converted.append({
                "log_id": r.log_id,
                "service": payload.get('service', 'unknown'),
                "timestamp": payload.get('timestamp', ''),
                "level": payload.get('level', 'INFO'),
                "content": payload.get('chunk_text', ''),
                "score": r.rrf_score,
                "source": payload.get('source', 'unknown')
            })
        return converted

    def _extract_source_refs(self, answer: str, sources: List[Dict[str, Any]]) -> List[SourceReference]:
        """
        从回答中提取来源引用，并匹配到具体的日志
        """
        source_refs = []
        
        # 查找所有 [ID:xxx] 格式的引用
        pattern = r'\[ID:(\d+)\]'
        matches = re.findall(pattern, answer)
        
        # 去重
        unique_log_ids = list(set(int(m) for m in matches))
        
        # 为每个引用的日志创建 SourceReference
        ref_counter = 0
        for log_id in unique_log_ids:
            # 查找对应的日志
            log_data = None
            for source in sources:
                if source.get('log_id') == log_id:
                    log_data = source
                    break
            
            if log_data:
                ref_counter += 1
                ref_id = f"[{ref_counter}]"
                
                content = log_data.get('content', '')
                source_refs.append(SourceReference(
                    ref_id=ref_id,
                    log_id=log_id,
                    service=log_data.get('service', 'unknown'),
                    timestamp=log_data.get('timestamp', ''),
                    level=log_data.get('level', 'INFO'),
                    content=content,
                    score=log_data.get('score', 0.0),
                    snippet=content[:100] + "..." if len(content) > 100 else content
                ))
        
        # 如果没有 [ID:xxx] 格式的引用，但 sources 不为空，自动添加引用
        if not source_refs and sources:
            for idx, source in enumerate(sources[:5], 1):
                log_id = source.get('log_id')
                if log_id:
                    content = source.get('content', '')
                    source_refs.append(SourceReference(
                        ref_id=f"[{idx}]",
                        log_id=log_id,
                        service=source.get('service', 'unknown'),
                        timestamp=source.get('timestamp', ''),
                        level=source.get('level', 'INFO'),
                        content=content,
                        score=source.get('score', 0.0),
                        snippet=content[:100] + "..." if len(content) > 100 else content
                    ))
        
        return source_refs

    def _annotate_answer_with_refs(self, answer: str, source_refs: List[SourceReference]) -> str:
        """
        将回答中的 [ID:xxx] 替换为 [n] 格式
        """
        if not source_refs:
            return answer
        
        # 创建 log_id -> ref_id 映射
        log_to_ref = {ref.log_id: ref.ref_id for ref in source_refs}
        
        # 替换 [ID:xxx] 为 [n]
        def replace_ref(match):
            log_id = int(match.group(1))
            return log_to_ref.get(log_id, match.group(0))
        
        annotated = re.sub(r'\[ID:(\d+)\]', replace_ref, answer)
        
        return annotated

    def ask(
        self,
        question: str,
        filters: Optional[Dict[str, Any]] = None,
        top_k: Optional[int] = None,
        template_type: Optional[str] = None
    ) -> QAResult:
        """同步问答"""
        start_time = time.time()

        # 1. 检索
        retrieval_start = time.time()
        k = top_k or self.top_k
        logs = self._search_method(question, k, filters)
        retrieval_time = time.time() - retrieval_start

        logger.info(f"[{self.retriever_type}] 检索到 {len(logs)} 条相关日志，耗时 {retrieval_time:.3f}s")

        # 截断过长的日志
        for log in logs:
            if 'content' in log and len(log['content']) > self.max_log_length:
                log['content'] = log['content'][:self.max_log_length] + "..."

        # 2. 构建 Prompt
        template = template_type or self.template_type
        prompt = build_qa_prompt(
            question=question,
            logs=logs,
            history=self.conversation_history,
            template_type=template
        )

        logger.info(f"Prompt 长度: {len(prompt)} 字符")

        # 3. 调用 LLM
        llm_start = time.time()
        try:
            messages = [
                ChatMessage(role="system", content=PromptTemplates.SYSTEM_PROMPT),
                ChatMessage(role="user", content=prompt)
            ]
            response = self.llm_client.chat(
                messages, 
                temperature=0.3,
                max_tokens=500  # 稍微增加，以支持完整回答
            )
            llm_time = time.time() - llm_start
            answer = response.content
            total_tokens = response.total_tokens

            logger.info(f"LLM 调用完成，耗时 {llm_time:.3f}s，Token: {total_tokens}")

        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            llm_time = time.time() - llm_start
            answer = f"抱歉，处理您的问题时出现错误: {str(e)}"
            total_tokens = 0

        # 4. 提取来源
        sources = self._extract_sources(logs)
        
        # 5. 提取来源引用（从回答中解析 [ID:xxx]）
        source_refs = self._extract_source_refs(answer, sources)
        
        # 6. 标注回答（将 [ID:xxx] 替换为 [n]）
        annotated_answer = self._annotate_answer_with_refs(answer, source_refs)

        # 7. 估计置信度
        confidence = self._estimate_confidence(logs, answer)

        # 8. 保存对话历史
        self.conversation_history.append({"role": "user", "content": question})
        self.conversation_history.append({"role": "assistant", "content": annotated_answer})

        total_time = time.time() - start_time

        return QAResult(
            question=question,
            answer=annotated_answer,
            sources=sources,
            source_refs=source_refs,
            confidence=confidence,
            total_tokens=total_tokens,
            retrieval_time=retrieval_time,
            llm_time=llm_time,
            total_time=total_time,
            retriever_type=self.retriever_type
        )

    def ask_stream(
        self,
        question: str,
        filters: Optional[Dict[str, Any]] = None,
        top_k: Optional[int] = None,
        template_type: Optional[str] = None
    ) -> Generator[StreamChunk, None, None]:
        """
        流式问答（支持来源标注）
        """
        # 1. 检索相关日志
        k = top_k or self.top_k
        logs = self._search_method(question, k, filters)

        logger.info(f"[{self.retriever_type}] 检索到 {len(logs)} 条相关日志")

        # 截断过长的日志
        for log in logs:
            if 'content' in log and len(log['content']) > self.max_log_length:
                log['content'] = log['content'][:self.max_log_length] + "..."

        # 2. 先输出来源信息（包含引用ID）
        sources = self._extract_sources(logs)
        if sources:
            # 为每个来源生成引用ID
            source_refs = []
            for idx, source in enumerate(sources[:5], 1):
                ref_id = f"[{idx}]"
                content = source.get('content', '')
                source_refs.append({
                    "ref_id": ref_id,
                    "log_id": source.get('log_id'),
                    "service": source.get('service', 'unknown'),
                    "timestamp": source.get('timestamp', ''),
                    "level": source.get('level', 'INFO'),
                    "content": content[:200] + "..." if len(content) > 200 else content,
                    "score": source.get('score', 0.0)
                })
            
            yield StreamChunk(
                type="source",
                content=f"找到 {len(sources)} 条相关日志（{self.retriever_type} 检索）",
                data={
                    "sources": sources,
                    "source_refs": source_refs,
                    "retriever_type": self.retriever_type
                }
            )

        # 3. 构建 Prompt
        template = template_type or self.template_type
        prompt = build_qa_prompt(
            question=question,
            logs=logs,
            history=self.conversation_history,
            template_type=template
        )

        # 4. 流式调用 LLM
        try:
            messages = [
                ChatMessage(role="system", content=PromptTemplates.SYSTEM_PROMPT),
                ChatMessage(role="user", content=prompt)
            ]

            full_answer = ""
            for chunk in self.llm_client.chat_stream(messages, temperature=0.3):
                full_answer += chunk
                yield StreamChunk(type="answer", content=chunk)

            # 5. 保存对话历史（使用标注后的答案）
            # 提取来源引用并标注
            source_refs = self._extract_source_refs(full_answer, sources)
            annotated_answer = self._annotate_answer_with_refs(full_answer, source_refs)
            
            self.conversation_history.append({"role": "user", "content": question})
            self.conversation_history.append({"role": "assistant", "content": annotated_answer})

        except Exception as e:
            logger.error(f"流式 LLM 调用失败: {e}")
            error_msg = f"\n\n抱歉，处理您的问题时出现错误: {str(e)}"
            yield StreamChunk(type="answer", content=error_msg)

    def ask_with_context(
        self,
        question: str,
        logs: List[Dict[str, Any]],
        template_type: Optional[str] = None
    ) -> str:
        """基于提供的日志直接问答（跳过检索步骤）"""
        template = template_type or self.template_type
        
        # 截断过长的日志
        for log in logs:
            if 'content' in log and len(log['content']) > self.max_log_length:
                log['content'] = log['content'][:self.max_log_length] + "..."

        prompt = build_qa_prompt(
            question=question,
            logs=logs,
            history=self.conversation_history,
            template_type=template
        )

        try:
            messages = [
                ChatMessage(role="system", content=PromptTemplates.SYSTEM_PROMPT),
                ChatMessage(role="user", content=prompt)
            ]
            response = self.llm_client.chat(messages, temperature=0.3)

            self.conversation_history.append({"role": "user", "content": question})
            self.conversation_history.append({"role": "assistant", "content": response.content})

            return response.content

        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return f"抱歉，处理您的问题时出现错误: {str(e)}"

    def clear_history(self):
        """清空对话历史"""
        self.conversation_history = []
        logger.info("对话历史已清空")

    def get_history(self) -> List[Dict[str, str]]:
        """获取对话历史"""
        return self.conversation_history.copy()

    def _extract_sources(self, logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """从日志中提取来源信息"""
        sources = []
        for log in logs:
            source = {
                "log_id": log.get('log_id'),
                "service": log.get('service', 'unknown'),
                "timestamp": log.get('timestamp', ''),
                "level": log.get('level', 'INFO'),
                "content": log.get('content', ''),
                "score": log.get('score', 0.0)
            }
            sources.append(source)
        return sources

    def _estimate_confidence(self, logs: List[Dict[str, Any]], answer: str) -> str:
        """估计回答置信度"""
        if not logs:
            return "低"

        # 检查是否有引用（支持 [ID:xxx] 和 [n] 两种格式）
        has_ref = bool(re.search(r'\[ID:\d+\]', answer)) or bool(re.search(r'\[\d+\]', answer))
        has_sections = all(k in answer for k in ['【问题理解】', '【关键证据】', '【分析推断】', '【结论建议】'])
        
        if has_ref and has_sections and len(logs) >= 3:
            return "高"
        elif has_ref and len(logs) >= 2:
            return "中"
        else:
            return "低"


def create_pipeline(
    top_k: int = 5,
    template_type: str = "evidence_chain",
    retriever_type: str = "hybrid",
    max_log_length: int = 300
) -> QAPipeline:
    """
    创建问答流水线实例

    Args:
        top_k: 检索返回的日志数量
        template_type: Prompt 模板类型 (evidence_chain, quick, short)
        retriever_type: 检索器类型 (vector, bm25, hybrid)
        max_log_length: 每条日志的最大长度

    Returns:
        QAPipeline: 问答流水线实例
    """
    return QAPipeline(
        top_k=top_k,
        template_type=template_type,
        retriever_type=retriever_type,
        max_log_length=max_log_length
    )