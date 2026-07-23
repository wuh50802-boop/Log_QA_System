"""
BGE 嵌入模型加载服务
使用 BAAI/bge-base-zh-v1.5 模型生成文本向量（768维）
"""

import logging
from typing import List, Optional, Union
from sentence_transformers import SentenceTransformer
import torch
import numpy as np
import logging
# 屏蔽modelscope下载冗余日志
logging.getLogger("modelscope_hub.download").setLevel(logging.ERROR)
logging.getLogger("modelscope").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class BGEEmbedder:
    """
    BGE 嵌入模型封装
    支持批量编码和单条编码
    """
    
    # 模型名称（中文优化）
    MODEL_NAME = "BAAI/bge-base-zh-v1.5"
    
    # 向量维度
    VECTOR_SIZE = 768
    
    # 最大批次大小（避免内存溢出）
    MAX_BATCH_SIZE = 32
    
    def __init__(self, model_name: Optional[str] = None, device: Optional[str] = None):
        self.model_name = model_name or self.MODEL_NAME

        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        logger.info(f"使用设备: {self.device}")
        logger.info(f"正在加载 BGE 模型: {self.model_name}")

        try:
            from modelscope.hub.snapshot_download import snapshot_download
            import os

            # 定义本地模型快照路径
            model_local_root = os.path.join("./models_cache", "models", "AI-ModelScope--bge-base-zh-v1.5", "snapshots", "master")
            model_dir = ""

            # 判断本地是否已完整存在模型文件
            if os.path.exists(os.path.join(model_local_root, "config.json")):
                logger.info("本地模型文件已存在，跳过远端校验下载")
                model_dir = model_local_root
            else:
                logger.info("本地无完整模型，执行下载")
                model_dir = snapshot_download(
                    'AI-ModelScope/bge-base-zh-v1.5',
                    cache_dir='./models_cache'
                )
                logger.info(f"模型已下载到: {model_dir}")

            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(
                model_dir,
                device=self.device
            )
            self.model.to(self.device)

            logger.info(f"✅ BGE 模型加载成功！向量维度: {self.VECTOR_SIZE}")
            if self.device == "cuda":
                logger.info(f"   🚀 模型已在 GPU 上运行")

        except Exception as e:
            logger.error(f"❌ BGE 模型加载失败: {e}")
            raise
    
    def encode(
        self, 
        texts: Union[str, List[str]], 
        normalize: bool = True,
        show_progress: bool = False
    ) -> np.ndarray:
        """
        将文本编码为向量
        
        Args:
            texts: 单条文本或文本列表
            normalize: 是否归一化向量（余弦相似度需要）
            show_progress: 是否显示进度条
        
        Returns:
            numpy.ndarray: 向量数组，shape = (n, 768)
        """
        # 统一为列表
        if isinstance(texts, str):
            texts = [texts]
        
        if not texts:
            logger.warning("输入文本为空，返回空向量")
            return np.array([])
        
        # 检查文本长度
        total_chars = sum(len(t) for t in texts)
        logger.debug(f"编码 {len(texts)} 条文本，总字符数: {total_chars}")
        
        try:
            # 编码
            embeddings = self.model.encode(
                texts,
                normalize_embeddings=normalize,
                show_progress_bar=show_progress,
                batch_size=self.MAX_BATCH_SIZE,
                convert_to_numpy=True
            )
            
            logger.debug(f"✅ 编码完成，向量维度: {embeddings.shape}")
            return embeddings
            
        except Exception as e:
            logger.error(f"❌ 编码失败: {e}")
            raise
    
    def encode_single(self, text: str, normalize: bool = True) -> np.ndarray:
        """
        编码单条文本
        
        Args:
            text: 单条文本
            normalize: 是否归一化
        
        Returns:
            numpy.ndarray: 一维向量，shape = (768,)
        """
        result = self.encode([text], normalize=normalize)
        vector = result[0]
        
        # 确保是一维向量
        if hasattr(vector, 'shape') and len(vector.shape) == 2:
            vector = vector.flatten()
        
        return vector
    
    def encode_batch(
        self, 
        texts: List[str], 
        batch_size: int = 32,
        normalize: bool = True,
        show_progress: bool = True
    ) -> np.ndarray:
        """
        分批编码大量文本（内存友好）
        
        Args:
            texts: 文本列表
            batch_size: 每批数量
            normalize: 是否归一化
            show_progress: 是否显示进度
        
        Returns:
            numpy.ndarray: 所有向量
        """
        if not texts:
            return np.array([])
        
        all_embeddings = []
        total_batches = (len(texts) + batch_size - 1) // batch_size
        
        logger.info(f"开始分批编码 {len(texts)} 条文本，批次大小: {batch_size}")
        
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            embeddings = self.encode(batch, normalize=normalize, show_progress=False)
            all_embeddings.append(embeddings)
            
            if show_progress:
                progress = min(i + batch_size, len(texts))
                logger.info(f"编码进度: {progress}/{len(texts)}")
        
        return np.vstack(all_embeddings)
    
    def get_vector_size(self) -> int:
        """获取向量维度"""
        return self.VECTOR_SIZE
    
    def is_available(self) -> bool:
        """检查模型是否可用"""
        return self.model is not None
    
    def __repr__(self) -> str:
        return f"BGEEmbedder(model={self.model_name}, device={self.device})"


# ============ 单例模式（全局共享） ============
_embedder_instance: Optional[BGEEmbedder] = None


def get_embedder() -> BGEEmbedder:
    """
    获取全局嵌入模型实例（单例）
    
    Returns:
        BGEEmbedder: 嵌入模型实例
    """
    global _embedder_instance
    if _embedder_instance is None:
        _embedder_instance = BGEEmbedder()
    return _embedder_instance


# ============ 测试函数 ============
def test_embedder():
    """测试嵌入模型是否正常工作"""
    logger.info("=" * 50)
    logger.info("开始测试 BGE 嵌入模型")
    
    # 1. 初始化
    embedder = get_embedder()
    
    # 2. 测试单条编码
    test_text = "这是一条测试日志消息"
    logger.info(f"测试单条编码: {test_text}")
    vector = embedder.encode_single(test_text)
    logger.info(f"  向量类型: {type(vector)}")
    logger.info(f"  向量形状: {vector.shape}")
    logger.info(f"  向量维度: {len(vector)}")
    logger.info(f"  是否一维: {len(vector.shape) == 1}")
    
    # 3. 测试批量编码
    test_texts = [
        "用户登录失败，密码错误",
        "数据库连接超时，请检查网络",
        "系统启动完成，服务正常运行"
    ]
    
    logger.info(f"\n测试批量编码: {len(test_texts)} 条")
    embeddings = embedder.encode(test_texts)
    logger.info(f"  向量形状: {embeddings.shape}")
    logger.info(f"  是否归一化: {np.allclose(np.linalg.norm(embeddings[0]), 1.0)}")
    
    # 4. 测试返回格式（重要！）
    logger.info(f"\n检查 encode_single 返回格式:")
    single_vector = embedder.encode_single("测试")
    logger.info(f"  类型: {type(single_vector)}")
    logger.info(f"  形状: {single_vector.shape}")
    logger.info(f"  长度: {len(single_vector)}")
    logger.info(f"  是否是一维: {len(single_vector.shape) == 1}")
    
    logger.info("✅ BGE 嵌入模型测试通过！")
    logger.info("=" * 50)
    
    return embedder


if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    test_embedder()