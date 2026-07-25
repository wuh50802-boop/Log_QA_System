"""
DeepSeek API 客户端封装
支持同步和流式调用，包含错误处理和重试机制
"""

import os
import json
import time
from typing import Optional, Dict, Any, Generator, List
from dataclasses import dataclass, field

import httpx
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()


@dataclass
class DeepSeekConfig:
    """DeepSeek API 配置"""
    api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    max_retries: int = 3
    retry_delay: float = 1.0
    timeout: float = 30.0  # 降低超时时间
    max_tokens: int = 600  # 降低默认值，日志回答通常不需要太长
    temperature: float = 0.3  # 降低温度，更确定性


@dataclass
class ChatMessage:
    """聊天消息"""
    role: str  # system, user, assistant
    content: str

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class ChatResponse:
    """聊天响应"""
    id: str
    content: str
    model: str
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str
    usage: Dict[str, int]

    @classmethod
    def from_api_response(cls, response: Dict[str, Any]) -> "ChatResponse":
        """从 API 原始响应构建"""
        choice = response.get("choices", [{}])[0]
        message = choice.get("message", {})
        usage = response.get("usage", {})

        return cls(
            id=response.get("id", ""),
            content=message.get("content", ""),
            model=response.get("model", ""),
            total_tokens=usage.get("total_tokens", 0),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            finish_reason=choice.get("finish_reason", ""),
            usage=usage,
        )


class DeepSeekClient:
    """DeepSeek API 客户端"""

    def __init__(self, config: Optional[DeepSeekConfig] = None):
        self.config = config or DeepSeekConfig()
        self._validate_config()
        self._client = None

    def _validate_config(self):
        """验证配置是否完整"""
        if not self.config.api_key:
            raise ValueError(
                "DEEPSEEK_API_KEY 未设置，请检查 .env 文件或环境变量"
            )

    def _get_client(self) -> httpx.Client:
        """获取或创建 HTTP 客户端"""
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.config.timeout,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._client

    def _build_request_body(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """构建请求体"""
        body = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "temperature": kwargs.get("temperature", self.config.temperature),
            "stream": stream,
        }
        # 可选参数
        if "top_p" in kwargs:
            body["top_p"] = kwargs["top_p"]
        if "frequency_penalty" in kwargs:
            body["frequency_penalty"] = kwargs["frequency_penalty"]
        if "presence_penalty" in kwargs:
            body["presence_penalty"] = kwargs["presence_penalty"]
        return body

    def _handle_api_error(self, error: Exception, attempt: int) -> bool:
        """处理 API 错误，返回是否应该重试"""
        if isinstance(error, (httpx.TimeoutException, httpx.ConnectError)):
            return True

        if isinstance(error, httpx.HTTPStatusError):
            status_code = error.response.status_code
            if status_code in [429, 500, 502, 503, 504]:
                return True
            return False

        return False

    def chat(
        self,
        messages: List[ChatMessage],
        **kwargs
    ) -> ChatResponse:
        """
        同步聊天接口
        
        Args:
            messages: 消息列表
            **kwargs: 可覆盖 temperature, max_tokens, top_p 等
        """
        msg_dicts = [msg.to_dict() for msg in messages]
        body = self._build_request_body(msg_dicts, stream=False, **kwargs)

        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                response = self._get_client().post(
                    f"{self.config.base_url}/chat/completions",
                    json=body,
                )
                response.raise_for_status()
                return ChatResponse.from_api_response(response.json())

            except Exception as e:
                last_error = e
                if not self._handle_api_error(e, attempt):
                    raise
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay * (2 ** attempt))

        raise last_error or Exception("API 调用失败")

    def chat_stream(self, messages: List[ChatMessage], **kwargs) -> Generator[str, None, None]:
        """
        流式聊天接口
        
        Args:
            messages: 消息列表
            **kwargs: 可覆盖 temperature, max_tokens, top_p 等
        """
        msg_dicts = [msg.to_dict() for msg in messages]
        body = self._build_request_body(msg_dicts, stream=True, **kwargs)

        for attempt in range(self.config.max_retries):
            try:
                with self._get_client().stream(
                    "POST",
                    f"{self.config.base_url}/chat/completions",
                    json=body,
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        # 统一转为 bytes 处理（兼容 str 和 bytes）
                        if isinstance(line, str):
                            line = line.encode("utf-8")
                        
                        if line.startswith(b"data: "):
                            data_str = line[6:].decode("utf-8")
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                continue
                break

            except Exception as e:
                if not self._handle_api_error(e, attempt):
                    raise
                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay * (2 ** attempt))
                    continue
                raise

    def close(self):
        """关闭 HTTP 客户端"""
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ========== 便捷函数 ==========

def get_simple_response(
    prompt: str,
    system_prompt: str = "你是日志分析助手，基于证据回答。",
    max_tokens: int = 400,
    temperature: float = 0.3,
    **kwargs
) -> str:
    """快速获取简单回答"""
    client = DeepSeekClient()
    try:
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=prompt),
        ]
        response = client.chat(
            messages, 
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )
        return response.content
    finally:
        client.close()


def stream_response(
    prompt: str,
    system_prompt: str = "你是日志分析助手，基于证据回答。",
    max_tokens: int = 400,
    temperature: float = 0.3,
    **kwargs
) -> Generator[str, None, None]:
    """快速获取流式回答"""
    client = DeepSeekClient()
    try:
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=prompt),
        ]
        for chunk in client.chat_stream(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        ):
            yield chunk
    finally:
        client.close()