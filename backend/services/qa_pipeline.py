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
        max_log_length: int = 300,
        rerank: bool = False,
        rerank_model: Optional[str] = None,
        rerank_candidate_k: int = 20,
        vector_weight: float = 1.0,
        bm25_weight: float = 1.0,
    ):
        """
        初始化问答流水线

        Args:
            top_k: 检索返回的日志数量（最终送入 LLM 的数量）
            template_type: Prompt 模板类型 (evidence_chain, quick, analysis)
            retriever_type: 检索器类型 (vector, bm25, hybrid)
            max_log_length: 每条日志的最大长度
            rerank: 是否启用 Cross-Encoder 重排序
            rerank_model: 重排序模型名称（None 用默认）
            rerank_candidate_k: 启用重排序时，先检索 Top-N 候选再重排到 top_k
            vector_weight: 混合检索中向量权重
            bm25_weight: 混合检索中 BM25 权重
        """
        self.top_k = top_k
        self.template_type = template_type
        self.retriever_type = retriever_type
        self.max_log_length = max_log_length
        self.rerank = rerank
        self.rerank_candidate_k = rerank_candidate_k
        self.vector_weight = vector_weight
        self.bm25_weight = bm25_weight

        # 初始化检索器（注入权重）
        self._init_retriever(retriever_type)

        # 初始化重排序器（按需，复用全局单例避免重复加载 1.1GB 模型）
        self.reranker = None
        if rerank:
            from .reranker import get_reranker
            self.reranker = get_reranker()
            logger.info(f"已启用 Cross-Encoder 重排序: candidate_k={rerank_candidate_k} -> top_k={top_k}")

        self.llm_client = DeepSeekClient()
        self.conversation_history: List[Dict[str, str]] = []

    def _init_retriever(self, retriever_type: str):
        """初始化检索器"""
        # 启用重排序时，检索阶段取更多候选
        effective_top_k = self.rerank_candidate_k if self.rerank else self.top_k

        if retriever_type == "vector":
            self.retriever = LogRetriever(top_k=effective_top_k)
            self._search_method = self._search_vector
        elif retriever_type == "bm25":
            self.retriever = get_bm25_retriever()
            self._search_method = self._search_bm25
        else:  # hybrid
            # 默认权重走单例（复用已初始化的检索器，省开销）
            # 非默认权重直接 new 实例（消融实验需要切换权重）
            if self.vector_weight == 1.0 and self.bm25_weight == 1.0:
                self.retriever = get_hybrid_retriever_async(top_k=effective_top_k)
            else:
                from .hybrid_retriever import HybridRetrieverAsync
                self.retriever = HybridRetrieverAsync(
                    top_k=effective_top_k,
                    vector_weight=self.vector_weight,
                    bm25_weight=self.bm25_weight,
                )
                logger.info(f"使用自定义权重 hybrid: vector_w={self.vector_weight}, bm25_w={self.bm25_weight}")
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
        从回答中提取来源引用，并匹配到具体的日志。
        支持三种引用形式：
          - [ID:xxx]  规范格式（优先）
          - [xxx]     裸 log_id 形式（LLM 常见输出）
          - [n]       序号形式（1-based，对应 sources 顺序）
        """
        source_refs = []

        # 收集所有合法 log_id 与序号映射
        valid_log_ids = {s.get('log_id') for s in sources if s.get('log_id') is not None}
        serial_to_log_id = {idx: s.get('log_id') for idx, s in enumerate(sources, 1)
                            if s.get('log_id') is not None}

        # 第一步：提取 [ID:xxx]
        id_pattern = r'\[ID:(\d+)\]'
        id_matches = re.findall(id_pattern, answer)
        referenced_log_ids = set(int(m) for m in id_matches)

        # 第二步：提取 [数字]（排除已被 [ID:数字] 匹配的部分）
        # 用负向先行断言避免重复匹配 [ID:数字] 中的数字
        bare_pattern = r'(?<!ID:)\[(\d+)\]'
        bare_matches = re.findall(bare_pattern, answer)
        for m in bare_matches:
            num = int(m)
            if num in valid_log_ids:
                referenced_log_ids.add(num)
            elif num in serial_to_log_id:
                referenced_log_ids.add(serial_to_log_id[num])

        # 按回答中出现顺序排序（保持引用顺序稳定）
        # 重新扫描一次以获取出现顺序
        ordered_ids = []
        seen = set()
        for m in re.finditer(r'\[ID:(\d+)\]|(?<!ID:)\[(\d+)\]', answer):
            num = int(m.group(1) or m.group(2))
            target = num if num in valid_log_ids else serial_to_log_id.get(num)
            if target is not None and target not in seen:
                ordered_ids.append(target)
                seen.add(target)
        # 兜底：若有未在回答中按顺序出现的，补到末尾
        for lid in referenced_log_ids:
            if lid not in seen:
                ordered_ids.append(lid)
                seen.add(lid)

        # 为每个引用的日志创建 SourceReference
        ref_counter = 0
        for log_id in ordered_ids:
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

        # 如果没有任何引用，但 sources 不为空，自动添加引用（保留兜底）
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
        规范化回答中的引用格式：统一为 [ID:log_id] 形式。
        - LLM 正确输出 [ID:1646] -> 保留
        - LLM 输出 [1646] (裸 log_id) -> 修复为 [ID:1646]
        - LLM 输出 [1] / [2] (序号) -> 映射到对应的 [ID:log_id]
        """
        if not source_refs:
            return answer

        # 收集所有合法的 log_id（用于识别 [数字] 是否为裸 log_id）
        valid_log_ids = {ref.log_id for ref in source_refs}
        # 序号 -> log_id 映射（按 source_refs 顺序，1-based）
        serial_to_log_id = {idx: ref.log_id for idx, ref in enumerate(source_refs, 1)}

        # 第一步：把 [数字] 形式统一修复为 [ID:数字] 或 [ID:对应log_id]
        def replace_bracket_num(match):
            num_str = match.group(1)
            try:
                num = int(num_str)
            except ValueError:
                return match.group(0)
            # 情况 A：是合法 log_id（裸 log_id 形式）-> 补全为 [ID:num]
            if num in valid_log_ids:
                return f"[ID:{num}]"
            # 情况 B：是 1-N 序号 -> 映射到对应 log_id
            if num in serial_to_log_id:
                return f"[ID:{serial_to_log_id[num]}]"
            # 都不是，保持原样
            return match.group(0)

        # 仅替换 [数字]，不动已有的 [ID:数字]
        # 用负向先行断言确保不是 [ID:数字] 的一部分
        annotated = re.sub(r'(?<!ID:)\[(\d+)\]', replace_bracket_num, answer)

        return annotated

    def ask(
        self,
        question: str,
        filters: Optional[Dict[str, Any]] = None,
        top_k: Optional[int] = None,
        template_type: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None
    ) -> QAResult:
        """
        同步问答

        Args:
            question: 用户问题
            filters: 检索过滤条件
            top_k: 检索返回的日志数量
            template_type: Prompt 模板类型
            history: 外部传入的对话历史（如多轮对话上下文）。
                     若提供则覆盖内部 conversation_history，且不自动追加。
                     若为 None 则使用内部 conversation_history（向后兼容）。
        """
        start_time = time.time()

        # 1. 检索
        retrieval_start = time.time()
        k = top_k or self.top_k
        # 启用重排序时，先取 rerank_candidate_k 条候选，再重排到 k 条
        retrieve_k = self.rerank_candidate_k if self.rerank else k
        logs = self._search_method(question, retrieve_k, filters)
        retrieval_time = time.time() - retrieval_start

        logger.info(f"[{self.retriever_type}] 检索到 {len(logs)} 条相关日志，耗时 {retrieval_time:.3f}s")

        # 1.5 重排序（若启用）
        rerank_time = 0.0
        if self.rerank and self.reranker and logs:
            rerank_start = time.time()
            logs = self.reranker.rerank(question, logs, top_k=k)
            rerank_time = time.time() - rerank_start
            logger.info(f"[rerank] 重排序到 {len(logs)} 条，耗时 {rerank_time:.3f}s")

        # 截断过长的日志
        for log in logs:
            if 'content' in log and len(log['content']) > self.max_log_length:
                log['content'] = log['content'][:self.max_log_length] + "..."

        # 2. 构建 Prompt
        # 若外部传入 history 则使用之，否则回退到内部 conversation_history
        effective_history = history if history is not None else self.conversation_history
        template = template_type or self.template_type
        prompt = build_qa_prompt(
            question=question,
            logs=logs,
            history=effective_history,
            template_type=template
        )

        logger.info(f"Prompt 长度: {len(prompt)} 字符, history={len(effective_history or [])} 条")

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
                max_tokens=1024  # 保证长回答不被截断
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
        confidence = self._estimate_confidence(logs, answer, question)

        # 8. 保存对话历史
        # 仅当未外部传入 history 时才追加到内部（外部管理时由调用方持久化）
        if history is None:
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
        template_type: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None
    ) -> Generator[StreamChunk, None, None]:
        """
        流式问答（支持来源标注）

        Args:
            history: 外部传入的对话历史。若提供则覆盖内部 conversation_history，
                     且不自动追加；若为 None 则使用内部 conversation_history。
        """
        # 1. 检索相关日志
        k = top_k or self.top_k
        # 启用重排序时，先取 rerank_candidate_k 条候选，再重排到 k 条
        retrieve_k = self.rerank_candidate_k if self.rerank else k
        logs = self._search_method(question, retrieve_k, filters)

        logger.info(f"[{self.retriever_type}] 检索到 {len(logs)} 条相关日志")

        # 1.5 重排序（若启用）
        if self.rerank and self.reranker and logs:
            logs = self.reranker.rerank(question, logs, top_k=k)
            logger.info(f"[rerank] 重排序到 {len(logs)} 条")

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
        effective_history = history if history is not None else self.conversation_history
        template = template_type or self.template_type
        prompt = build_qa_prompt(
            question=question,
            logs=logs,
            history=effective_history,
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

            # 仅当未外部传入 history 时才追加到内部
            if history is None:
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

    def _estimate_confidence(
        self,
        logs: List[Dict[str, Any]],
        answer: str,
        question: str = "",
    ) -> str:
        """
        估计回答置信度。

        采用 0-100 加权综合分，从五个维度评估：
        - 检索证据强度（40 分）：综合来源数量、相关性分数、日志级别
        - 来源引用对齐（15 分）：回答中是否使用 [ID:xxx]/[n] 标注，且 ID 与来源匹配
        - 回答结构完整性（15 分）：是否包含问题理解/证据/分析/结论四段（容错匹配）
        - 证据-结论一致性（15 分）：回答是否承认证据不足、是否包含拒绝式表述
        - 回答信息密度（15 分）：长度过短或过长异常扣分

        最终映射：>=80 高 / 60-79 中 / <60 低

        特殊场景降级：
        - 非问题场景（闲聊/打招呼/无具体技术问题）：上限"中"
        - 问答不匹配（模型引导用户补充信息）：上限"中"
        """
        if not logs:
            return "低"

        # ---------- 预判：识别非问题场景 ----------
        # 用户输入过短、不含疑问词/问号，且不含日志/技术关键词 → 视为闲聊
        q = (question or "").strip()
        question_words = ['为什么', '怎么', '如何', '什么', '哪里', '哪种', '是否', '是不是', '有没有', '原因', '排查', '解决', '报错', '失败', '异常', '错误', '日志', '服务', '数据库', '连接', '超时', '?', '？']
        is_question_like = (
            len(q) >= 4
            and (
                any(w in q for w in question_words)
                or '?' in q
                or '？' in q
            )
        )

        # 回答中包含引导式表述（"请问有什么"、"请提供"、"请描述"）→ 模型识别为非问题
        guidance_phrases = [
            '请问有什么', '请提供', '请描述', '请告诉我', '需要我帮助',
            '没有具体问题', '请问您', '请补充', '请明确',
        ]
        is_guiding_response = any(p in answer for p in guidance_phrases)

        # 非问题场景（闲聊/打招呼）：置信度封顶"中"，且通常应为"低-中"
        non_question = (not is_question_like and len(q) < 10) or (not is_question_like and is_guiding_response)

        # ---------- 维度 1：检索证据强度（40 分） ----------
        # 数量分（最多 18）：1 条=6，2 条=12，3 条=15，4+ 条=18
        n_logs = len(logs)
        count_score = min(18, 6 + (n_logs - 1) * 3) if n_logs >= 1 else 0

        # 相关性分（最多 12）：取最高 score 映射
        # score 一般在 0-1 之间（不同 retriever 量纲略有差异，做兜底）
        scores = [float(l.get('score') or 0.0) for l in logs if l.get('score') is not None]
        if scores:
            max_score = max(scores)
            avg_score = sum(scores) / len(scores)
            # 归一化：>0.5 视为高相关
            if max_score >= 0.7:
                rel_score = 12
            elif max_score >= 0.5:
                rel_score = 10
            elif max_score >= 0.3:
                rel_score = 7
            else:
                rel_score = 4
            # 平均分微调（±2）
            if avg_score >= 0.5:
                rel_score = min(12, rel_score + 2)
            elif avg_score < 0.2:
                rel_score = max(0, rel_score - 2)
        else:
            rel_score = 6  # 无 score 信息，给中位

        # 日志级别加权（最多 10）：ERROR/WARN 比 INFO 更有诊断价值
        levels = [str(l.get('level', 'INFO')).upper() for l in logs]
        level_bonus = 0
        if any(l in ('ERROR', 'FATAL', 'CRITICAL') for l in levels):
            level_bonus += 6
        elif any(l in ('WARN', 'WARNING') for l in levels):
            level_bonus += 4
        if any(l in ('INFO',) for l in levels):
            level_bonus += 2
        level_bonus = min(10, level_bonus)

        evidence_score = count_score + rel_score + level_bonus  # 0-40

        # ---------- 维度 2：来源引用对齐（15 分） ----------
        # 提取回答中的 [ID:xxx] 和 [n] 引用
        id_refs = set(re.findall(r'\[ID:(\d+)\]', answer))
        bracket_refs = set(re.findall(r'\[(\d+)\]', answer))
        all_refs = id_refs | bracket_refs

        # 提取来源关键词
        source_keywords = ['根据日志', '日志显示', '从日志', '日志中', '来源', '引用', '证据']
        has_source_keyword = any(kw in answer for kw in source_keywords)

        if all_refs:
            # 检查引用是否在来源 log_id 中
            source_ids = {str(l.get('log_id')) for l in logs if l.get('log_id') is not None}
            matched = all_refs & source_ids
            if matched:
                citation_score = 15  # 完全对齐
            elif len(all_refs) >= 1:
                citation_score = 9  # 有引用但 ID 对不上（可能是 LLM 编造）
            else:
                citation_score = 6
        elif has_source_keyword:
            citation_score = 10  # 提到"根据日志"但没用标注
        else:
            citation_score = 4  # 完全没引用

        # ---------- 维度 3：回答结构完整性（15 分，容错匹配） ----------
        # 严格四段
        strict_sections = ['【问题理解】', '【关键证据】', '【分析推断】', '【结论建议】']
        strict_count = sum(1 for s in strict_sections if s in answer)
        # 宽松匹配（允许无【】包裹或同义词）
        loose_patterns = [
            r'问题[理分]?[解]?|现[象象]?[是]?|现象',
            r'证据|关键|日志显示',
            r'分析|推断|原因|可能',
            r'结论|建议|解决|处理',
        ]
        loose_count = sum(1 for p in loose_patterns if re.search(p, answer))
        # 综合：严格一段=4 分（最高 15），宽松一段=2 分兜底
        structure_score = min(15, strict_count * 4 + max(0, loose_count - strict_count) * 2)

        # ---------- 维度 4：证据-结论一致性（15 分） ----------
        # 检查 LLM 是否承认证据不足（这是好行为，应给分）
        admits_insufficient = any(
            kw in answer for kw in ['证据不足', '未找到', '没有相关', '无法确认', '需要更多', '建议查看更多']
        )
        # 检查过度自信表述（在证据少时仍下绝对结论）
        over_confident = any(kw in answer for kw in ['一定', '必定', '肯定是', '绝对是', '毫无疑问'])

        if admits_insufficient:
            consistency_score = 15  # 主动承认证据不足是好行为
        elif over_confident and n_logs <= 2:
            consistency_score = 6  # 证据少却过度自信，扣分
        else:
            consistency_score = 11  # 正常表述

        # ---------- 维度 5：回答信息密度（15 分） ----------
        answer_len = len(answer)
        if answer_len < 30:
            density_score = 4  # 过短，可能没说清楚
        elif answer_len < 80:
            density_score = 11  # 简短但可能完整
        elif answer_len <= 800:
            density_score = 15  # 正常长度
        elif answer_len <= 1500:
            density_score = 12  # 略长
        else:
            density_score = 8  # 过长，可能跑题

        # ---------- 汇总 ----------
        total = evidence_score + citation_score + structure_score + consistency_score + density_score
        # total 理论范围 0-100

        # 非问题场景降级：闲聊/打招呼/问答不匹配时，置信度封顶"中"
        # 这是基于"问题本身不构成技术问询"的判断，与回答质量无关
        if non_question:
            if total >= 60:
                return "中"
            else:
                return "低"

        if total >= 80:
            return "高"
        elif total >= 60:
            return "中"
        else:
            return "低"


def create_pipeline(
    top_k: int = 5,
    template_type: str = "evidence_chain",
    retriever_type: str = "hybrid",
    max_log_length: int = 300,
    rerank: bool = False,
    rerank_model: Optional[str] = None,
    rerank_candidate_k: int = 20,
    vector_weight: float = 1.0,
    bm25_weight: float = 1.0,
) -> QAPipeline:
    """
    创建问答流水线实例

    Args:
        top_k: 检索返回的日志数量（最终送入 LLM 的数量）
        template_type: Prompt 模板类型 (evidence_chain, quick, short)
        retriever_type: 检索器类型 (vector, bm25, hybrid)
        max_log_length: 每条日志的最大长度
        rerank: 是否启用 Cross-Encoder 重排序
        rerank_model: 重排序模型名称
        rerank_candidate_k: 重排序候选数（先检索 Top-N 再重排到 top_k）
        vector_weight: 混合检索向量权重
        bm25_weight: 混合检索 BM25 权重

    Returns:
        QAPipeline: 问答流水线实例
    """
    return QAPipeline(
        top_k=top_k,
        template_type=template_type,
        retriever_type=retriever_type,
        max_log_length=max_log_length,
        rerank=rerank,
        rerank_model=rerank_model,
        rerank_candidate_k=rerank_candidate_k,
        vector_weight=vector_weight,
        bm25_weight=bm25_weight,
    )