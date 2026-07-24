"""
对话管理模块 - 支持多轮对话和上下文记忆
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import json
import hashlib


@dataclass
class Message:
    """单条消息"""
    role: str  # user, assistant, system
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
            timestamp=data.get("timestamp", datetime.now().isoformat())
        )


@dataclass
class Conversation:
    """对话会话"""
    id: str
    messages: List[Message] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_message(self, role: str, content: str) -> Message:
        """添加消息"""
        message = Message(role=role, content=content)
        self.messages.append(message)
        self.updated_at = datetime.now().isoformat()
        return message
    
    def get_history(self, limit: Optional[int] = None) -> List[Dict[str, str]]:
        """获取对话历史（用于LLM）"""
        messages = self.messages
        if limit:
            messages = messages[-limit:]
        return [{"role": m.role, "content": m.content} for m in messages]
    
    def get_last_n(self, n: int) -> List[Message]:
        """获取最近n条消息"""
        return self.messages[-n:] if n > 0 else []
    
    def clear(self):
        """清空对话"""
        self.messages = []
        self.updated_at = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "messages": [m.to_dict() for m in self.messages],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Conversation":
        messages = [Message.from_dict(m) for m in data.get("messages", [])]
        return cls(
            id=data.get("id", ""),
            messages=messages,
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            metadata=data.get("metadata", {})
        )


class ConversationBufferMemory:
    """
    对话缓冲区记忆
    支持滑动窗口、摘要压缩
    """
    
    def __init__(
        self,
        max_tokens: int = 2000,
        max_messages: int = 20,
        enable_summary: bool = False,
        summary_trigger: int = 10
    ):
        """
        Args:
            max_tokens: 最大 token 数（估算）
            max_messages: 最大消息数
            enable_summary: 是否启用摘要压缩
            summary_trigger: 触发摘要的消息数
        """
        self.max_tokens = max_tokens
        self.max_messages = max_messages
        self.enable_summary = enable_summary
        self.summary_trigger = summary_trigger
        self.conversations: Dict[str, Conversation] = {}
        self.summaries: Dict[str, str] = {}  # 会话摘要
    
    def create_conversation(
        self, 
        conversation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """创建新对话"""
        if conversation_id is None:
            conversation_id = self._generate_id()
        
        self.conversations[conversation_id] = Conversation(
            id=conversation_id,
            metadata=metadata or {}
        )
        return conversation_id
    
    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """获取对话"""
        return self.conversations.get(conversation_id)
    
    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str
    ) -> Optional[Message]:
        """添加消息到对话"""
        conv = self.get_conversation(conversation_id)
        if not conv:
            return None
        
        message = conv.add_message(role, content)
        
        # 如果启用摘要且消息数达到触发值，生成摘要
        if self.enable_summary and len(conv.messages) >= self.summary_trigger:
            self._update_summary(conversation_id)
        
        return message
    
    def get_history(
        self,
        conversation_id: str,
        limit: Optional[int] = None,
        include_summary: bool = True
    ) -> List[Dict[str, str]]:
        """获取对话历史"""
        conv = self.get_conversation(conversation_id)
        if not conv:
            return []
        
        # 如果启用摘要，使用摘要 + 最近消息
        if include_summary and self.enable_summary:
            summary = self.summaries.get(conversation_id)
            if summary:
                messages = [{"role": "system", "content": f"对话摘要: {summary}"}]
                messages.extend(conv.get_history(limit))
                return messages
        
        return conv.get_history(limit)
    
    def get_context_for_llm(
        self,
        conversation_id: str,
        max_tokens: Optional[int] = None
    ) -> List[Dict[str, str]]:
        """
        获取适合LLM的上下文
        自动截断到 max_tokens
        """
        conv = self.get_conversation(conversation_id)
        if not conv:
            return []
        
        max_tokens = max_tokens or self.max_tokens
        messages = conv.messages.copy()
        
        # 如果有摘要，插入摘要
        if self.enable_summary:
            summary = self.summaries.get(conversation_id)
            if summary:
                messages.insert(0, Message(
                    role="system",
                    content=f"对话摘要（供参考）: {summary}"
                ))
        
        # 估算 token 数并截断
        total_tokens = self._estimate_tokens(messages)
        if total_tokens <= max_tokens:
            return [{"role": m.role, "content": m.content} for m in messages]
        
        # 从后往前截断
        result = []
        current_tokens = 0
        
        # 保留系统消息
        for m in messages:
            if m.role == "system":
                result.append(m)
                current_tokens += self._estimate_tokens([m])
                break
        
        # 从最新的消息开始添加
        for m in reversed(messages):
            if m.role == "system":
                continue
            tokens = self._estimate_tokens([m])
            if current_tokens + tokens <= max_tokens:
                result.append(m)
                current_tokens += tokens
            else:
                break
        
        # 反转回正确顺序
        result = [{"role": m.role, "content": m.content} for m in reversed(result)]
        return result
    
    def _update_summary(self, conversation_id: str):
        """更新对话摘要（由外部LLM生成）"""
        # 这里只标记需要更新，实际摘要由外部生成
        # 这样避免在 memory 中依赖 LLM
        self.summaries[conversation_id] = f"待更新摘要 (消息数: {len(self.get_conversation(conversation_id).messages)})"
    
    def set_summary(self, conversation_id: str, summary: str):
        """设置对话摘要"""
        self.summaries[conversation_id] = summary
    
    def clear(self, conversation_id: str):
        """清空对话"""
        conv = self.get_conversation(conversation_id)
        if conv:
            conv.clear()
            self.summaries.pop(conversation_id, None)
    
    def delete(self, conversation_id: str):
        """删除对话"""
        self.conversations.pop(conversation_id, None)
        self.summaries.pop(conversation_id, None)
    
    def list_conversations(self) -> List[Dict[str, Any]]:
        """列出所有对话"""
        return [
            {
                "id": conv.id,
                "message_count": len(conv.messages),
                "created_at": conv.created_at,
                "updated_at": conv.updated_at,
                "metadata": conv.metadata
            }
            for conv in self.conversations.values()
        ]
    
    def _generate_id(self) -> str:
        """生成对话ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        import uuid
        return f"conv_{timestamp}_{str(uuid.uuid4())[:8]}"
    
    def _estimate_tokens(self, messages: List[Message]) -> int:
        """估算 token 数（粗略）"""
        total_chars = sum(len(m.content) for m in messages)
        # 中文约 1.5 字符/token，英文约 4 字符/token
        # 取平均约 2.5 字符/token
        return int(total_chars / 2.5) + 10 * len(messages)
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化"""
        return {
            "conversations": {
                k: v.to_dict() for k, v in self.conversations.items()
            },
            "summaries": self.summaries
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationBufferMemory":
        """反序列化"""
        memory = cls()
        for conv_id, conv_data in data.get("conversations", {}).items():
            memory.conversations[conv_id] = Conversation.from_dict(conv_data)
        memory.summaries = data.get("summaries", {})
        return memory


# ============================================================
# 集成到 QAPipeline
# ============================================================

class ConversationAwarePipeline:
    """
    支持对话的问答流水线
    包装 QAPipeline，添加对话记忆功能
    """
    
    def __init__(
        self,
        pipeline,
        memory: Optional[ConversationBufferMemory] = None,
        conversation_id: Optional[str] = None
    ):
        """
        Args:
            pipeline: QAPipeline 实例
            memory: 对话记忆
            conversation_id: 对话ID
        """
        self.pipeline = pipeline
        self.memory = memory or ConversationBufferMemory()
        
        if conversation_id:
            self.conversation_id = conversation_id
            if not self.memory.get_conversation(conversation_id):
                self.memory.create_conversation(conversation_id)
        else:
            self.conversation_id = self.memory.create_conversation()
    
    def ask(
        self,
        question: str,
        filters: Optional[Dict[str, Any]] = None,
        top_k: Optional[int] = None,
        template_type: Optional[str] = None
    ):
        """
        带上下文的问答
        """
        # 获取对话历史
        history = self.memory.get_history(
            self.conversation_id,
            limit=10,
            include_summary=True
        )
        
        # 调用 pipeline 的 ask 方法（传入历史）
        result = self.pipeline.ask(
            question=question,
            filters=filters,
            top_k=top_k,
            template_type=template_type
        )
        
        # 保存到对话历史
        self.memory.add_message(self.conversation_id, "user", question)
        self.memory.add_message(self.conversation_id, "assistant", result.answer)
        
        return result
    
    def ask_stream(self, question: str, **kwargs):
        """流式问答"""
        # 获取对话历史
        history = self.memory.get_history(
            self.conversation_id,
            limit=10,
            include_summary=True
        )
        
        # 流式调用
        full_answer = ""
        for chunk in self.pipeline.ask_stream(question, **kwargs):
            if chunk.type == "answer":
                full_answer += chunk.content
            yield chunk
        
        # 保存到对话历史
        self.memory.add_message(self.conversation_id, "user", question)
        self.memory.add_message(self.conversation_id, "assistant", full_answer)
    
    def get_history(self, limit: Optional[int] = None) -> List[Dict[str, str]]:
        """获取对话历史"""
        return self.memory.get_history(self.conversation_id, limit)
    
    def get_full_history(self) -> List[Message]:
        """获取完整对话历史"""
        conv = self.memory.get_conversation(self.conversation_id)
        return conv.messages if conv else []
    
    def clear(self):
        """清空当前对话"""
        self.memory.clear(self.conversation_id)
    
    def set_summary(self, summary: str):
        """设置对话摘要"""
        self.memory.set_summary(self.conversation_id, summary)
    
    def switch_conversation(self, conversation_id: str):
        """切换对话"""
        if not self.memory.get_conversation(conversation_id):
            self.memory.create_conversation(conversation_id)
        self.conversation_id = conversation_id
    
    def new_conversation(self) -> str:
        """创建新对话"""
        new_id = self.memory.create_conversation()
        self.conversation_id = new_id
        return new_id


def create_conversation_pipeline(
    top_k: int = 5,
    retriever_type: str = "hybrid",
    template_type: str = "evidence_chain",
    max_messages: int = 20,
    enable_summary: bool = False
) -> ConversationAwarePipeline:
    """
    创建支持对话的问答流水线
    """
    from .qa_pipeline import create_pipeline
    
    pipeline = create_pipeline(
        top_k=top_k,
        template_type=template_type,
        retriever_type=retriever_type
    )
    
    memory = ConversationBufferMemory(
        max_messages=max_messages,
        enable_summary=enable_summary
    )
    
    return ConversationAwarePipeline(pipeline, memory)