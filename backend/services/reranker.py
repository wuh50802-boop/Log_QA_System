"""
Cross-Encoder 重排序器
使用 BAAI/bge-reranker-base 对检索结果做精排

工作原理：
- 双塔检索（BGE 向量）将 query 和 doc 分别编码后做点积，速度快但精度有限
- Cross-Encoder 将 [query, doc] 拼接后联合编码，能捕捉细粒度交互，精度更高
- 实际用法：先用双塔/BM25 取 Top-N（N=20），再用 Cross-Encoder 重排到 Top-K（K=5）

模型：BAAI/bge-reranker-base（中文优化，约 1.1GB）
"""
import logging
import os
from typing import List, Dict, Any, Optional

import torch
import numpy as np

logger = logging.getLogger(__name__)
# 屏蔽 modelscope 下载冗余日志
logging.getLogger("modelscope_hub.download").setLevel(logging.ERROR)
logging.getLogger("modelscope").setLevel(logging.WARNING)


class Reranker:
    """Cross-Encoder 重排序器"""

    MODEL_NAME = "BAAI/bge-reranker-base"
    LOCAL_MODEL_ROOT = os.path.join(
        ".", "models_cache", "models", "BAAI--bge-reranker-base",
        "snapshots", "master"
    )

    def __init__(self, model_name: Optional[str] = None, device: Optional[str] = None):
        self.model_name = model_name or self.MODEL_NAME

        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        logger.info(f"使用设备: {self.device}")
        logger.info(f"正在加载 Cross-Encoder 重排序模型: {self.model_name}")

        try:
            from modelscope.hub.snapshot_download import snapshot_download

            # 优先使用本地快照，避免重复下载
            if os.path.exists(os.path.join(self.LOCAL_MODEL_ROOT, "config.json")):
                logger.info("本地重排序模型已存在，跳过远端下载")
                model_dir = self.LOCAL_MODEL_ROOT
            else:
                logger.info("本地无完整模型，执行下载")
                model_dir = snapshot_download(
                    self.MODEL_NAME,
                    cache_dir="./models_cache"
                )
                logger.info(f"模型已下载到: {model_dir}")

            from sentence_transformers import CrossEncoder
            self.model = CrossEncoder(model_dir, device=self.device)
            logger.info("✅ Cross-Encoder 重排序模型加载成功")

        except Exception as e:
            logger.error(f"❌ 重排序模型加载失败: {e}")
            raise

    def rerank(
        self,
        query: str,
        docs: List[Dict[str, Any]],
        top_k: int = 5,
        content_field: str = "content"
    ) -> List[Dict[str, Any]]:
        """
        对检索结果重排序

        Args:
            query: 用户查询
            docs: 检索到的文档列表（每个 dict 含 log_id/content/service/level 等）
            top_k: 重排后返回的 Top-K 数量
            content_field: 文档中作为内容的字段名

        Returns:
            重排后的 Top-K 文档列表，每个 doc 增加 rerank_score 字段
        """
        if not docs:
            return []

        # 构造 [query, doc] 对
        pairs = []
        for doc in docs:
            content = doc.get(content_field, "") or doc.get("chunk_text", "") or ""
            # 拼接服务/级别作为上下文，提升重排质量
            service = doc.get("service", "")
            level = doc.get("level", "")
            doc_text = f"{service} {level} {content}".strip()
            pairs.append((query, doc_text))

        # Cross-Encoder 打分
        try:
            scores = self.model.predict(pairs, convert_to_numpy=True)
        except Exception as e:
            logger.warning(f"重排序打分失败，返回原始顺序: {e}")
            return docs[:top_k]

        # 按分数降序排序
        scored = list(zip(docs, scores))
        scored.sort(key=lambda x: float(x[1]), reverse=True)

        # 取 Top-K 并注入 rerank_score
        ranked = []
        for doc, score in scored[:top_k]:
            doc_copy = dict(doc)
            doc_copy["rerank_score"] = float(score)
            # 保留原始检索分数用于对比
            doc_copy.setdefault("original_score", doc.get("score", 0.0))
            ranked.append(doc_copy)

        logger.info(
            f"重排序完成: 输入 {len(docs)} 条 -> 输出 {len(ranked)} 条, "
            f"top1_score={ranked[0]['rerank_score']:.4f}"
        )
        return ranked

    def is_available(self) -> bool:
        return self.model is not None

    def __repr__(self) -> str:
        return f"Reranker(model={self.model_name}, device={self.device})"


# ============ 单例 ============
_reranker_instance: Optional[Reranker] = None


def get_reranker() -> Reranker:
    """获取全局 Reranker 实例（单例）"""
    global _reranker_instance
    if _reranker_instance is None:
        _reranker_instance = Reranker()
    return _reranker_instance


# ============ 测试 ============
def test_reranker():
    """简单测试重排序器是否工作"""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logger.info("=" * 50)
    logger.info("测试 Cross-Encoder 重排序器")

    reranker = get_reranker()

    query = "auth-service 登录失败的原因"
    docs = [
        {"log_id": 1, "service": "auth", "level": "ERROR",
         "content": "用户登录失败，密码错误"},
        {"log_id": 2, "service": "order", "level": "INFO",
         "content": "订单创建成功"},
        {"log_id": 3, "service": "auth", "level": "WARN",
         "content": "登录重试次数过多"},
    ]

    ranked = reranker.rerank(query, docs, top_k=2)
    logger.info(f"Top-2 结果:")
    for d in ranked:
        logger.info(f"  log_id={d['log_id']} score={d['rerank_score']:.4f} "
                    f"content={d['content']}")

    logger.info("✅ 重排序器测试通过")
    logger.info("=" * 50)


if __name__ == "__main__":
    test_reranker()
