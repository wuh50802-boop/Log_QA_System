"""
Prompt 模板设计 - 含证据链约束（精简版）
用于日志智能问答系统，强制 LLM 基于检索到的日志证据进行回答
"""

from typing import List, Dict, Any, Optional


class PromptTemplates:
    """Prompt 模板集合（精简版）"""

    # ============================================================
    # 系统提示词（精简）
    # ============================================================

    SYSTEM_PROMPT = """你是日志分析助手。基于提供的日志证据回答问题，禁止编造。引用格式：[ID:xxx]"""

    # ============================================================
    # 证据链约束 Prompt（自然语言版）
    # ============================================================

    @staticmethod
    def evidence_chain_prompt(
        question: str,
        context: List[Dict[str, Any]],
        chat_history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """
        精简版证据链 Prompt - 自然语言输出
        """
        # 紧凑的日志格式 - 一行一条
        logs_text = []
        for idx, log in enumerate(context, 1):
            log_id = log.get('log_id', log.get('id', f'#{idx}'))
            service = log.get('service', 'unknown')
            timestamp = log.get('timestamp', log.get('time', 'unknown'))
            level = log.get('level', 'INFO')
            content = log.get('content', log.get('chunk_text', log.get('message', '')))
            # 移除换行，压缩空格
            content = ' '.join(content.split())
            
            # 格式: [ID] 服务/级别 时间: 内容
            logs_text.append(f"{idx}.[{log_id}] {service}/{level} {timestamp}: {content}")
        
        context_text = "\n".join(logs_text)

        # 对话历史（精简）
        history_text = ""
        if chat_history:
            history_lines = []
            for msg in chat_history[-4:]:  # 只保留最近4条
                role = '用户' if msg.get('role') == 'user' else '助手'
                content = ' '.join(msg.get('content', '').split())[:100]  # 截断
                history_lines.append(f"{role}: {content}")
            history_text = "历史:\n" + "\n".join(history_lines) + "\n"

        # 自然语言格式 Prompt
        return f"""{history_text}日志:
{context_text}

问题: {question}

请按以下格式回答（使用自然语言，不要用管道符分隔）：
【问题理解】简要复述用户的问题
【关键证据】列出相关的日志条目，必须带引用如[ID:xxx]
【分析推断】基于证据进行分析
【结论建议】给出明确的结论或操作建议
【置信度】高/中/低

回答:"""

    # ============================================================
    # 快速问答 Prompt（最短模式）
    # ============================================================

    @staticmethod
    def quick_prompt(
        question: str,
        context: List[Dict[str, Any]]
    ) -> str:
        """
        快速问答 Prompt - 最短模式，适用于简单问题
        """
        # 超紧凑格式
        logs_text = []
        for idx, log in enumerate(context, 1):
            log_id = log.get('log_id', f'#{idx}')
            content = ' '.join(log.get('content', '').split())[:150]
            logs_text.append(f"{idx}.[{log_id}] {content}")
        
        context_text = "\n".join(logs_text)
        
        return f"""日志:
{context_text}

Q: {question}

简短回答（带引用如[ID:xxx]）:
A:"""

    # ============================================================
    # 简短问答 Prompt（保留格式）
    # ============================================================

    @staticmethod
    def short_prompt(
        question: str,
        context: List[Dict[str, Any]]
    ) -> str:
        """
        简短问答 Prompt - 保留基本格式
        """
        logs_text = []
        for idx, log in enumerate(context, 1):
            log_id = log.get('log_id', f'#{idx}')
            service = log.get('service', 'unknown')
            level = log.get('level', 'INFO')
            content = ' '.join(log.get('content', '').split())[:200]
            logs_text.append(f"{idx}.[{log_id}] {service}|{level}: {content}")
        
        context_text = "\n".join(logs_text)
        
        return f"""基于日志回答问题，引用来源如[ID:xxx]。

{context_text}

Q: {question}

格式：
【问题理解】
【关键证据】（带引用）
【分析推断】
【结论建议】

回答:"""

    # ============================================================
    # 格式化工具（保留兼容）
    # ============================================================

    @staticmethod
    def format_logs_as_context(logs: List[Dict[str, Any]]) -> str:
        """将日志列表格式化为紧凑的上下文字符串"""
        if not logs:
            return "（未找到相关日志）"

        lines = []
        for idx, log in enumerate(logs, 1):
            log_id = log.get('log_id', log.get('id', idx))
            service = log.get('service', 'unknown')
            timestamp = log.get('timestamp', log.get('time', 'unknown'))
            level = log.get('level', 'INFO')
            content = ' '.join(log.get('content', log.get('message', log.get('chunk_text', ''))).split())
            
            lines.append(f"{idx}.[{log_id}] {service}/{level} {timestamp}: {content}")

        return "\n".join(lines)

    @staticmethod
    def format_chat_history(history: List[Dict[str, str]]) -> str:
        """格式化对话历史（精简）"""
        if not history:
            return ""
        
        lines = []
        for msg in history[-6:]:  # 只保留最近6条
            role = '用户' if msg.get('role') == 'user' else '助手'
            content = ' '.join(msg.get('content', '').split())[:100]
            lines.append(f"{role}: {content}")
        return "\n".join(lines)


# ============================================================
# 便捷函数
# ============================================================

def build_qa_prompt(
    question: str,
    logs: List[Dict[str, Any]],
    history: Optional[List[Dict[str, str]]] = None,
    template_type: str = "evidence_chain"
) -> str:
    """
    构建问答 Prompt

    Args:
        question: 用户问题
        logs: 检索到的日志列表
        history: 对话历史
        template_type: 模板类型 (evidence_chain, quick, short)
    """
    if template_type == "quick":
        return PromptTemplates.quick_prompt(question, logs)
    elif template_type == "short":
        return PromptTemplates.short_prompt(question, logs)
    else:  # evidence_chain (默认)
        return PromptTemplates.evidence_chain_prompt(question, logs, history)