"""
RAGAS 评估配置

将项目已有的 DeepSeek LLM 和 BGE Embedder 适配为 RAGAS 可用的 Evaluator。
不引入额外的 OpenAI 依赖，保持评估器与生产 LLM 一致。
"""

import logging
import os
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings

load_dotenv()

logger = logging.getLogger(__name__)


# ============================================================
# Evaluator LLM：DeepSeek（通过 OpenAI 兼容协议接入）
# ============================================================

class DeepSeekEvaluatorConfig:
    """DeepSeek 评估器配置（从 .env 读取，与生产 LLM 保持一致）"""

    api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    # 评估时温度降到 0，提高打分稳定性
    temperature: float = 0.0
    # 评估通常需要较长输出（理由 + 打分）
    max_tokens: int = 1024
    timeout: float = 60.0


@lru_cache(maxsize=1)
def get_evaluator_llm() -> BaseChatModel:
    """
    获取评估器 LLM（DeepSeek，通过 langchain_openai.ChatOpenAI 接入）。

    使用 langchain_openai 而非项目自研的 DeepSeekClient，是因为 RAGAS
    内部依赖 LangChain 的 BaseChatModel 抽象（function calling、
    结构化输出等），自研客户端无法满足。

    Returns:
        BaseChatModel: LangChain 兼容的聊天模型实例
    """
    cfg = DeepSeekEvaluatorConfig
    if not cfg.api_key:
        raise ValueError(
            "DEEPSEEK_API_KEY 未设置，无法初始化评估器 LLM。"
            "请在 backend/.env 中配置。"
        )

    logger.info(f"初始化 RAGAS 评估器 LLM: {cfg.model} @ {cfg.base_url}")
    return ChatOpenAI(
        model=cfg.model,
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        temperature=cfg.temperature,
        max_tokens=cfg.max_tokens,
        timeout=cfg.timeout,
    )


# ============================================================
# Evaluator Embeddings：复用项目 BGE 模型
# ============================================================

class BGEEmbeddingsAdapter(Embeddings):
    """
    将项目自研的 BGEEmbedder 适配为 LangChain Embeddings 接口。

    RAGAS 的 answer_relevancy 指标需要 embeddings 来计算语义相似度。
    复用项目已有的 BGE bge-base-zh-v1.5 模型，避免引入 OpenAI embeddings
    的额外费用，同时保持中英文语义评估的一致性。
    """

    def __init__(self):
        # 延迟导入，避免在模块加载时就触发 BGE 模型加载（耗时）
        from services.embedder import get_embedder
        self._embedder = get_embedder()
        logger.info("RAGAS 评估器 Embeddings: BGE bge-base-zh-v1.5 (768维)")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """嵌入多条文档（用于 context / answer 的批量化）"""
        vectors = self._embedder.encode(texts, normalize=True)
        # numpy ndarray → list[list[float]]
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        """嵌入单条查询（用于 question）"""
        vector = self._embedder.encode_single(text, normalize=True)
        return vector.tolist()


@lru_cache(maxsize=1)
def get_evaluator_embeddings() -> Embeddings:
    """获取评估器 Embeddings（BGE 单例）"""
    return BGEEmbeddingsAdapter()


# ============================================================
# RAGAS Wrapper 组装
# ============================================================

@lru_cache(maxsize=1)
def get_ragas_llm_wrapper():
    """获取 RAGAS LLM Wrapper"""
    from ragas.llms import LangchainLLMWrapper
    return LangchainLLMWrapper(get_evaluator_llm())


@lru_cache(maxsize=1)
def get_ragas_embeddings_wrapper():
    """获取 RAGAS Embeddings Wrapper"""
    from ragas.embeddings import LangchainEmbeddingsWrapper
    return LangchainEmbeddingsWrapper(get_evaluator_embeddings())


def get_default_metrics():
    """
    构建 RAGAS 默认 4 个核心指标，已注入 DeepSeek LLM 和 BGE Embeddings。

    RAGAS 0.2 API：指标实例自己持有 LLM/Embeddings 引用，
    通过构造函数参数注入，而非 .score() 调用时传参。

    Returns:
        list: [faithfulness, answer_relevancy, context_precision, context_recall]
    """
    from ragas.metrics import (
        Faithfulness,
        AnswerRelevancy,
        ContextPrecision,
        ContextRecall,
    )

    llm_wrapper = get_ragas_llm_wrapper()
    emb_wrapper = get_ragas_embeddings_wrapper()

    return [
        Faithfulness(llm=llm_wrapper),
        AnswerRelevancy(llm=llm_wrapper, embeddings=emb_wrapper),
        ContextPrecision(llm=llm_wrapper),
        ContextRecall(llm=llm_wrapper),
    ]
