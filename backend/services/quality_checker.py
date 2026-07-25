"""
回答质量自检模块
检测回答中是否包含幻觉（无来源的信息）
"""

import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from collections import Counter


@dataclass
class QualityCheckResult:
    """质量检查结果"""
    passed: bool
    score: float  # 0-100
    issues: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "issues": self.issues,
            "warnings": self.warnings,
            "suggestions": self.suggestions
        }
    
    def to_markdown(self) -> str:
        md = f"## 质量检查结果\n\n"
        md += f"**状态**: {'✅ 通过' if self.passed else '❌ 未通过'}\n"
        md += f"**得分**: {self.score:.1f}/100\n\n"
        
        if self.issues:
            md += "### ❌ 问题\n"
            for issue in self.issues:
                md += f"- {issue.get('message', '')}\n"
            md += "\n"
        
        if self.warnings:
            md += "### ⚠️ 警告\n"
            for warning in self.warnings:
                md += f"- {warning}\n"
            md += "\n"
        
        if self.suggestions:
            md += "### 💡 建议\n"
            for suggestion in self.suggestions:
                md += f"- {suggestion}\n"
        
        return md


class QualityChecker:
    """
    回答质量检查器
    检测幻觉、来源引用、置信度评估等
    """
    
    def __init__(self):
        self.checkers = [
            self._check_source_citation,
            self._check_hallucination_patterns,
            self._check_confidence_alignment,
            self._check_evidence_sufficiency,
            self._check_reasoning_consistency,
            self._check_section_completeness,
        ]
    
    def check(self, answer: str, sources: List[Dict[str, Any]], 
              confidence: str = "中") -> QualityCheckResult:
        """
        执行质量检查
        
        Args:
            answer: 回答内容
            sources: 来源日志列表
            confidence: 声明的置信度
            
        Returns:
            QualityCheckResult: 检查结果
        """
        issues = []
        warnings = []
        suggestions = []
        score = 100.0
        
        # 执行所有检查器
        for checker in self.checkers:
            result = checker(answer, sources, confidence)
            if result:
                if result.get('type') == 'issue':
                    issues.append(result)
                    score -= result.get('penalty', 10)
                elif result.get('type') == 'warning':
                    warnings.append(result.get('message', ''))
                    score -= result.get('penalty', 5)
                if result.get('suggestion'):
                    suggestions.append(result['suggestion'])
        
        # 确保得分在0-100之间
        score = max(0, min(100, score))
        
        # 判定是否通过（得分 >= 70）
        passed = score >= 70 and len(issues) == 0
        
        # 去重建议
        suggestions = list(dict.fromkeys(suggestions))
        
        return QualityCheckResult(
            passed=passed,
            score=score,
            issues=issues,
            warnings=warnings,
            suggestions=suggestions[:5]  # 最多5条建议
        )
    
    def _check_source_citation(self, answer: str, sources: List[Dict[str, Any]], 
                                confidence: str) -> Optional[Dict[str, Any]]:
        """
        检查是否有来源引用
        """
        # 检测各种引用格式
        citation_patterns = [
            r'\[ID:\d+\]',
            r'\[\d+\]',
            r'\[引用:.*?\]',
            r'\[日志\s*\d+\]',
        ]
        
        has_citation = False
        for pattern in citation_patterns:
            if re.search(pattern, answer):
                has_citation = True
                break
        
        # 检测是否提到了来源
        source_keywords = ['根据日志', '日志显示', '从日志', '日志中', '来源', '引用']
        has_source_keyword = any(kw in answer for kw in source_keywords)
        
        if sources and not has_citation and not has_source_keyword:
            return {
                'type': 'issue',
                'message': '回答引用了日志但未标注具体来源，请使用 [ID:xxx] 或 [n] 格式',
                'penalty': 12,
                'suggestion': '在引用日志时添加来源标注，如 [ID:6789] 或 [1]'
            }

        if not sources and not has_citation:
            # 没有来源，但也没有引用，可以接受
            return None

        # 检查引用的日志是否在来源中
        if sources and has_citation:
            source_ids = [str(s.get('log_id', '')) for s in sources if s.get('log_id')]
            # 提取回答中的ID引用
            id_refs = re.findall(r'\[ID:(\d+)\]', answer)
            for ref in id_refs:
                if ref not in source_ids:
                    return {
                        'type': 'warning',
                        'message': f'引用的日志ID [{ref}] 不在提供的来源列表中',
                        'penalty': 6,
                        'suggestion': '确保引用的日志ID与来源列表匹配'
                    }

        return None
    
    def _check_hallucination_patterns(self, answer: str, sources: List[Dict[str, Any]],
                                       confidence: str) -> Optional[Dict[str, Any]]:
        """
        检查是否包含常见的幻觉模式（仅检测明确的外部知识话术，避免误伤通用表述）
        """
        hallucination_patterns = [
            (r'我[的]?[经]?[验]?[告]?[诉]?[我]', '使用了个人经验而非日志证据'),
            (r'根据[我]?[的]?[了]?[解]', '可能使用了外部知识'),
            (r'据[我]?[所]?[知]', '可能使用了外部知识'),
            (r'一般来[说讲]', '使用了通用知识而非日志证据'),
            (r'通常来[说讲]', '使用了通用知识而非日志证据'),
        ]

        for pattern, message in hallucination_patterns:
            if re.search(pattern, answer):
                return {
                    'type': 'warning',
                    'message': f'检测到可能幻觉: {message}',
                    'penalty': 8,
                    'suggestion': '回答应严格基于提供的日志证据，避免使用外部知识'
                }

        return None
    
    def _check_confidence_alignment(self, answer: str, sources: List[Dict[str, Any]], 
                                     confidence: str) -> Optional[Dict[str, Any]]:
        """
        检查置信度是否与证据充分程度匹配
        """
        source_count = len(sources)
        has_citation = bool(re.search(r'\[ID:\d+\]|\[\d+\]', answer))
        has_detailed_analysis = len(answer.split('【分析推断】')) > 1
        
        # 计算证据充分度
        evidence_score = 0
        if source_count >= 3:
            evidence_score += 30
        elif source_count >= 2:
            evidence_score += 20
        elif source_count >= 1:
            evidence_score += 10
        
        if has_citation:
            evidence_score += 20
        if has_detailed_analysis:
            evidence_score += 20
        
        # 判断置信度是否合理
        if confidence == "高" and evidence_score < 50:
            return {
                'type': 'warning',
                'message': f'置信度标注为"高"但证据充分度较低（{evidence_score}/100）',
                'penalty': 6,
                'suggestion': '建议将置信度调整为"中"或"低"'
            }

        if confidence == "低" and evidence_score > 70:
            return {
                'type': 'warning',
                'message': f'置信度标注为"低"但证据充分度较高（{evidence_score}/100）',
                'penalty': 3,
                'suggestion': '建议将置信度调整为"高"或"中"'
            }

        return None
    
    def _check_evidence_sufficiency(self, answer: str, sources: List[Dict[str, Any]],
                                     confidence: str) -> Optional[Dict[str, Any]]:
        """
        检查证据是否足以支持结论
        """
        if not sources:
            return {
                'type': 'issue',
                'message': '没有检索到任何相关日志，但提供了回答',
                'penalty': 30,
                'suggestion': '当没有相关日志时，应明确告知用户"未找到相关日志"'
            }

        # 检查是否承认证据不足
        admits_insufficient = any(kw in answer for kw in ['证据不足', '未找到', '没有相关', '无法确认', '需要更多'])

        # 仅当只有 1 条日志且未承认证据不足时才提示
        if len(sources) <= 1 and not admits_insufficient:
            return {
                'type': 'warning',
                'message': f'只有 {len(sources)} 条日志，但回答未表明证据可能不足',
                'penalty': 5,
                'suggestion': '建议在回答中加入"证据有限"或"建议查看更多日志"的说明'
            }

        return None
    
    def _check_reasoning_consistency(self, answer: str, sources: List[Dict[str, Any]],
                                      confidence: str) -> Optional[Dict[str, Any]]:
        """
        检查推理逻辑是否一致。

        改进点：
        - 按句子粒度检测（句号/换行切分），避免跨句误报
        - 排除否定上下文：「未/没/无/不」+ 反义词，是在陈述"没出现 X"，不是矛盾
        - 排除对比上下文：
          a) 句中出现「或/和/与/、」等并列连接词 → 不同事件对比
          b) 转折词「但/却」+ 不同主语 → 不同事件对比
          c) 转折词「但/却」+ 同主语 → 真矛盾
        - penalty 从 15 降到 8，避免误报对总分影响过大
        """
        contradiction_pairs = [
            (r'成功', r'失败'),
            (r'正常', r'异常'),
            (r'正常', r'错误'),
            (r'已恢复', r'故障'),
            (r'可用', r'不可用'),
        ]

        # 否定词前缀：当反义词前出现这些词时，是在陈述"没出现 X"，不算矛盾
        negation_prefixes = ['未', '没', '无', '不', '尚未', '并非', '没有']

        # 并列对比连接词：明确列举两个事件，不算矛盾
        parallel_connectors = ['或', '和', '与', '、', '还是', '或者']

        # 转折词：需进一步判断主语是否相同
        transition_connectors = ['但', '但是', '却', '然而', '不过']

        # 按句号/问号/换行切分
        sentences = re.split(r'[。.！!？?\n]+', answer)

        for sentence in sentences:
            for word1, word2 in contradiction_pairs:
                # 找出句子中两个反义词的位置
                m1 = re.search(word1, sentence)
                m2 = re.search(word2, sentence)
                if not (m1 and m2):
                    continue

                pos1, pos2 = sorted([m1.start(), m2.start()])

                # 检查反义词前面是否有否定词（"未失败"、"没异常"）
                prefix_before_2 = sentence[max(0, pos2 - 5):pos2]
                prefix_before_1 = sentence[max(0, pos1 - 5):pos1]
                if any(neg in prefix_before_2 for neg in negation_prefixes):
                    continue
                if any(neg in prefix_before_1 for neg in negation_prefixes):
                    continue

                between = sentence[pos1 + len(word1):pos2]

                # 情况 a: 并列连接词 → 对比，不算矛盾
                if any(conn in between for conn in parallel_connectors):
                    continue

                # 情况 b/c: 转折词 → 需判断主语是否相同
                has_transition = any(conn in between for conn in transition_connectors)
                if has_transition:
                    # 找出 between 中转折词结束位置
                    transition_end = 0
                    for w in transition_connectors:
                        idx = between.find(w)
                        if idx >= 0:
                            transition_end = max(transition_end, idx + len(w))

                    # subj1：反义词1之前的内容（到上一个标点或句子开头）
                    prefix1 = sentence[:pos1]
                    # 从后往前找标点
                    last_punct_1 = max(
                        prefix1.rfind('，'), prefix1.rfind(','), prefix1.rfind('、'),
                        prefix1.rfind('：'), prefix1.rfind(':')
                    )
                    subj1_raw = prefix1[last_punct_1 + 1:] if last_punct_1 >= 0 else prefix1

                    # subj2：转折词之后到反义词2之间的内容
                    subj2_raw = between[transition_end:]

                    # 去掉标点和空格
                    def _clean_subject(s: str) -> str:
                        return re.sub(r'[，,。.！!？?\s、（）()【】[\]]', '', s)

                    subj1 = _clean_subject(subj1_raw)
                    subj2 = _clean_subject(subj2_raw)

                    # 主语片段重叠（任一包含另一，且长度 >= 2）→ 同主语 → 矛盾
                    if (
                        len(subj1) >= 2 and len(subj2) >= 2
                        and (subj1 in subj2 or subj2 in subj1)
                    ):
                        # 同主语转折 → 真矛盾
                        return {
                            'type': 'issue',
                            'message': f'同一主体既"{word1}"又"{word2}"，可能存在逻辑矛盾',
                            'penalty': 8,
                            'suggestion': '检查推理逻辑是否一致，或明确对比/否定关系'
                        }
                    # 主语不同 → 对比，不算矛盾
                    continue

                # 同句内同时出现两个反义词，无否定/对比/转折上下文 → 真矛盾
                return {
                    'type': 'issue',
                    'message': f'同一句中同时出现"{word1}"与"{word2}"，可能存在逻辑矛盾',
                    'penalty': 8,
                    'suggestion': '检查推理逻辑是否一致，或明确对比/否定关系'
                }

        return None
    
    def _check_section_completeness(self, answer: str, sources: List[Dict[str, Any]], 
                                     confidence: str) -> Optional[Dict[str, Any]]:
        """
        检查回答结构是否完整
        """
        required_sections = ['问题理解', '关键证据', '分析推断', '结论建议']
        missing_sections = []
        
        for section in required_sections:
            if f'【{section}】' not in answer:
                missing_sections.append(section)
        
        if missing_sections:
            return {
                'type': 'warning',
                'message': f'缺少以下部分: {", ".join(missing_sections)}',
                'penalty': 5,
                'suggestion': '按照建议格式组织回答'
            }

        return None


def calculate_self_check_pass_rate(results: List[QualityCheckResult]) -> Dict[str, Any]:
    """
    计算自检通过率
    
    Args:
        results: 质量检查结果列表
        
    Returns:
        统计信息
    """
    total = len(results)
    if total == 0:
        return {"pass_rate": 0, "passed": 0, "total": 0, "avg_score": 0}
    
    passed = sum(1 for r in results if r.passed)
    avg_score = sum(r.score for r in results) / total
    
    # 统计问题类型
    issue_types = Counter()
    for r in results:
        for issue in r.issues:
            issue_types[issue.get('message', 'unknown')] += 1
    
    return {
        "pass_rate": passed / total * 100,
        "passed": passed,
        "total": total,
        "avg_score": avg_score,
        "issue_types": dict(issue_types.most_common(5))
    }


# ============================================================
# 集成到 QAPipeline
# ============================================================

class QualityAwarePipeline:
    """
    支持质量自检的问答流水线
    包装 QAPipeline，自动进行质量检查
    """
    
    def __init__(self, pipeline, checker: Optional[QualityChecker] = None):
        self.pipeline = pipeline
        self.checker = checker or QualityChecker()
        self.last_check: Optional[QualityCheckResult] = None
        self.check_history: List[QualityCheckResult] = []
    
    def ask(self, question: str, **kwargs):
        """
        问答 + 质量自检
        """
        result = self.pipeline.ask(question, **kwargs)
        
        # 执行质量检查
        check_result = self.checker.check(
            answer=result.answer,
            sources=result.sources,
            confidence=result.confidence
        )
        
        self.last_check = check_result
        self.check_history.append(check_result)
        
        # 将检查结果附加到返回值
        result.quality_check = check_result
        
        return result
    
    def ask_stream(self, question: str, **kwargs):
        """
        流式问答 + 质量自检（在完成后检查）
        """
        full_answer = ""
        sources = []
        
        for chunk in self.pipeline.ask_stream(question, **kwargs):
            if chunk.type == "answer":
                full_answer += chunk.content
            if chunk.type == "source" and chunk.data:
                sources = chunk.data.get('sources', [])
            yield chunk
        
        # 执行质量检查
        check_result = self.checker.check(
            answer=full_answer,
            sources=sources,
            confidence="中"
        )
        
        self.last_check = check_result
        self.check_history.append(check_result)
    
    def get_last_check(self) -> Optional[QualityCheckResult]:
        """获取最后一次质量检查结果"""
        return self.last_check
    
    def get_check_stats(self) -> Dict[str, Any]:
        """获取质量检查统计"""
        return calculate_self_check_pass_rate(self.check_history)


def create_quality_pipeline(
    top_k: int = 5,
    retriever_type: str = "hybrid",
    template_type: str = "evidence_chain"
) -> QualityAwarePipeline:
    """
    创建支持质量自检的问答流水线
    """
    from .qa_pipeline import create_pipeline
    
    pipeline = create_pipeline(
        top_k=top_k,
        template_type=template_type,
        retriever_type=retriever_type
    )
    
    return QualityAwarePipeline(pipeline)