import os
import logging
import time
from typing import List, Dict, Any, Optional, Tuple
from functools import wraps

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue,
    PayloadIndexInfo,
)
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ============ 异常分类 ============
class QdrantRetryableError(Exception):
    """可重试异常（网络超时、连接中断等）"""
    pass


class QdrantFatalError(Exception):
    """致命异常（配置错误、认证失败等）"""
    pass


# ============ 重试装饰器 ============
def retry_on_failure(max_retries=3, delay=2, backoff=2):
    """
    自动重试装饰器，支持指数退避
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except QdrantRetryableError as e:
                    last_exception = e
                    wait_time = delay * (backoff ** attempt)
                    logger.warning(f"⏳ Qdrant 重试 {attempt+1}/{max_retries}，等待 {wait_time:.1f}s: {e}")
                    time.sleep(wait_time)
                except QdrantFatalError as e:
                    logger.error(f"❌ Qdrant 致命错误，停止重试: {e}")
                    raise
                except Exception as e:
                    # 未知异常，当作可重试处理
                    logger.warning(f"⚠️ Qdrant 未知异常 (尝试 {attempt+1}/{max_retries}): {e}")
                    if attempt == max_retries - 1:
                        raise QdrantRetryableError(f"重试耗尽: {e}")
                    time.sleep(delay * (backoff ** attempt))
            raise last_exception
        return wrapper
    return decorator


def fix_vector_format(vector):
    """
    修复向量格式，确保是一维列表
    
    Args:
        vector: 输入的向量（可能是 numpy 数组、二维列表等）
    
    Returns:
        List[float]: 一维向量列表
    """
    # 如果是 numpy 数组，转换为 list
    if isinstance(vector, np.ndarray):
        if len(vector.shape) == 2:
            vector = vector.flatten()
        vector = vector.tolist()
    
    # 如果是二维列表 [[...]]，展平为一维
    if isinstance(vector, list) and len(vector) > 0:
        if isinstance(vector[0], list):
            # 取第一个元素（如果是二维的）
            vector = vector[0]
        elif isinstance(vector[0], np.ndarray):
            # 如果是 numpy 数组在列表中，展平
            vector = np.array(vector).flatten().tolist()
    
    # 确保是 list
    if not isinstance(vector, list):
        vector = list(vector)
    
    # 确保每个元素是 float
    vector = [float(x) for x in vector]
    
    # 验证维度
    if len(vector) != 768:
        logger.warning(f"向量维度异常: {len(vector)}，期望 768")
        if len(vector) > 768:
            vector = vector[:768]
        elif len(vector) < 768:
            # 补零
            vector = vector + [0.0] * (768 - len(vector))
    
    return vector


class QdrantClientWrapper:
    """Qdrant 客户端封装，支持连接、集合管理、向量操作、索引管理"""

    def __init__(self):
        self.url = os.getenv("QDRANT_URL")
        self.api_key = os.getenv("QDRANT_API_KEY")
        self.collection_name = os.getenv("COLLECTION_NAME", "log_vectors")
        self.vector_size = int(os.getenv("VECTOR_SIZE", 768))

        if not self.url:
            raise QdrantFatalError("QDRANT_URL must be set in .env")

        # 本地部署（localhost / 127.0.0.1）不需要 API_KEY
        # 云端部署必须提供 API_KEY
        is_local = "localhost" in self.url or "127.0.0.1" in self.url
        if not is_local and not self.api_key:
            raise QdrantFatalError("QDRANT_API_KEY must be set for cloud deployment")

        self.client = QdrantClient(
            url=self.url,
            api_key=self.api_key if not is_local else None,
            timeout=120,          # 增加超时
            prefer_grpc=True,     # 启用 gRPC 提升性能
        )
        logger.info(f"✅ Qdrant client initialized for {self.url} ({'local' if is_local else 'cloud'})")

    @retry_on_failure(max_retries=3, delay=2, backoff=2)
    def health_check(self) -> bool:
        """检查连接是否正常"""
        try:
            self.client.get_collections()
            logger.info("✅ Qdrant health check passed")
            return True
        except Exception as e:
            logger.error(f"❌ Qdrant health check failed: {e}")
            raise QdrantRetryableError(f"Health check failed: {e}")

    @retry_on_failure(max_retries=2, delay=1, backoff=2)
    def create_collection(self, recreate: bool = False) -> bool:
        """
        创建向量集合（如果不存在），配置 HNSW 索引和所有字段的 Payload 索引
        """
        try:
            collections = self.client.get_collections().collections
            exists = any(c.name == self.collection_name for c in collections)

            if exists and recreate:
                logger.warning(f"🗑️ 删除现有 Collection: {self.collection_name}")
                self.client.delete_collection(self.collection_name)
                exists = False
                time.sleep(2)

            if not exists:
                logger.info(f"📦 创建 Collection: {self.collection_name}")

                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.vector_size,
                        distance=Distance.COSINE,
                    ),
                    hnsw_config={
                        "m": 16,
                        "ef_construct": 100,
                        "full_scan_threshold": 10000,
                        "on_disk": False,
                    },
                    optimizers_config={
                        "default_segment_number": 2,
                        "indexing_threshold": 10000,
                        "flush_interval_sec": 5,
                    },
                )
                logger.info(f"✅ Collection {self.collection_name} 创建完成")
                logger.info(f"   - 向量维度: {self.vector_size}")
                logger.info(f"   - HNSW: m=16, ef_construct=100")
                logger.info(f"   - 索引阈值: 10000 点")
                
                self._create_payload_indexes()
                return True
            else:
                logger.info(f"📊 Collection {self.collection_name} 已存在")
                info = self.client.get_collection(self.collection_name)
                # 兼容不同版本的属性名
                vectors_count = getattr(info, 'vectors_count', getattr(info, 'points_count', 0))
                indexed_count = getattr(info, 'indexed_vectors_count', getattr(info, 'indexed_points_count', 0))
                logger.info(f"   - 向量数: {vectors_count}")
                logger.info(f"   - 已索引: {indexed_count}/{vectors_count}")
                self._create_payload_indexes()
                return True
                
        except Exception as e:
            logger.error(f"❌ 创建 Collection 失败: {e}")
            raise QdrantRetryableError(f"Create collection failed: {e}")

    def _create_payload_indexes(self):
        """
        为所有日志字段创建 Payload 索引，加速过滤查询
        """
        fields = [
            ("log_id", "integer"),
            ("level", "keyword"),
            ("service", "keyword"),
            ("timestamp", "datetime"),
            ("chunk_text", "text"),
            ("source", "keyword"),
        ]
        
        for field_name, field_type in fields:
            try:
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field_name,
                    field_type=field_type,
                )
                logger.info(f"   ✅ 创建索引: {field_name} ({field_type})")
            except Exception as e:
                # 索引可能已存在
                logger.debug(f"   ℹ️ 索引 {field_name} 已存在: {e}")

    @retry_on_failure(max_retries=3, delay=2, backoff=2)
    def upsert_vectors(
        self,
        points: List[PointStruct],
        batch_size: int = 64,
        wait: bool = True,
    ) -> bool:
        """
        批量插入向量点（带重试）

        Args:
            batch_size: 单次 upsert 请求的 point 数（默认 64）。
                768 维向量 + payload ≈ 3.5KB/point，64 个 ≈ 224KB/请求，
                远低于 Qdrant 默认 payload 限制；wait=False 下失败重试代价可控。
            wait: 是否等待服务端写入完成。
                批量导入时设 wait=False 可大幅提升吞吐（跳过每批的确认往返）。
        """
        if not points:
            return True

        total = len(points)
        for i in range(0, total, batch_size):
            batch = points[i:i+batch_size]
            try:
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=batch,
                    wait=wait,
                )
                logger.debug(f"   ✅ 已入库 {i+len(batch)}/{total}")
            except Exception as e:
                logger.error(f"❌ 入库失败 (批次 {i//batch_size}): {e}")
                raise QdrantRetryableError(f"Upsert failed: {e}")

        logger.info(f"✅ 成功入库 {total} 个向量 (wait={wait})")
        return True

    def update_indexing_threshold(self, threshold: int) -> bool:
        """
        更新 indexing_threshold，用于批量导入时关闭后台索引、导入后再触发索引构建。

        - threshold 取较大值（如 10**9）：导入阶段不构建 HNSW 索引，写入更快
        - threshold 恢复正常值（如 10000）：触发已写入段的后台索引构建
        """
        try:
            from qdrant_client.http.models import OptimizersConfigDiff
            self.client.update_collection(
                collection_name=self.collection_name,
                optimizer_config=OptimizersConfigDiff(
                    indexing_threshold=threshold,
                ),
            )
            logger.info(f"✅ 更新 indexing_threshold = {threshold}")
            return True
        except Exception as e:
            logger.error(f"❌ 更新 indexing_threshold 失败: {e}")
            return False

    def wait_for_indexing(self, timeout: int = 3600) -> bool:
        """
        轮询等待后台索引构建完成（indexed_count 达到 vectors_count 并稳定）。

        用于批量导入完成后等待 Qdrant 把刚写入的向量构建成 HNSW 索引。

        分两阶段：
            1. 等待优化器启动（indexed > 0 或 status 变为 yellow/green），最多 120s
            2. 等待索引构建完成，连续 6 次（60s）无变化才认为稳定

        千万级向量 HNSW 构建可能需要 20-60 分钟，timeout 默认 1 小时。
        """
        # 显式设置优化线程数，激活后台优化器
        # （Qdrant 默认 max_optimization_threads=None 时可能不主动启动优化）
        try:
            from qdrant_client.http.models import OptimizersConfigDiff
            self.client.update_collection(
                collection_name=self.collection_name,
                optimizer_config=OptimizersConfigDiff(
                    indexing_threshold=10000,
                    max_optimization_threads=2,
                ),
            )
            logger.info("🔧 已设置 max_optimization_threads=2，激活后台索引构建")
        except Exception as e:
            logger.warning(f"设置优化线程失败（不影响索引构建）: {e}")

        start = time.time()
        last_indexed = -1
        stable_count = 0
        optimizer_started = False
        last_log_time = 0

        # 阶段 1：等待优化器启动（最多 120 秒）
        logger.info("⏳ 等待优化器启动...")
        while time.time() - start < min(120, timeout):
            try:
                info = self.client.get_collection(self.collection_name)
                vectors_count = getattr(info, 'vectors_count', getattr(info, 'points_count', 0)) or 0
                indexed_count = getattr(info, 'indexed_vectors_count', getattr(info, 'indexed_points_count', 0)) or 0
                status = str(getattr(info, 'status', ''))

                if indexed_count > 0 or status in ('yellow', 'green'):
                    optimizer_started = True
                    logger.info(f"✅ 优化器已启动 (indexed={indexed_count:,}, status={status})")
                    break
            except Exception as e:
                logger.warning(f"查询索引状态失败: {e}")
            time.sleep(5)

        if not optimizer_started:
            # 120 秒内优化器未启动，但数据量可能很小（已建完），检查一次
            info = self.client.get_collection(self.collection_name)
            vectors_count = getattr(info, 'vectors_count', getattr(info, 'points_count', 0)) or 0
            indexed_count = getattr(info, 'indexed_vectors_count', getattr(info, 'indexed_points_count', 0)) or 0
            if indexed_count >= vectors_count and vectors_count > 0:
                logger.info("✅ 索引已就绪（数据量小，构建瞬间完成）")
                return True
            logger.warning("⚠️ 优化器 120s 内未启动，继续等待...")

        # 阶段 2：等待索引构建完成
        logger.info(f"⏳ 等待索引构建完成（超时 {timeout}s）...")
        last_indexed = -1
        stable_count = 0
        phase2_start = time.time()

        while time.time() - start < timeout:
            try:
                info = self.client.get_collection(self.collection_name)
                vectors_count = getattr(info, 'vectors_count', getattr(info, 'points_count', 0)) or 0
                indexed_count = getattr(info, 'indexed_vectors_count', getattr(info, 'indexed_points_count', 0)) or 0
                status = str(getattr(info, 'status', ''))

                # 完成条件：indexed >= total 且状态为 green
                if vectors_count > 0 and indexed_count >= vectors_count and status == 'green':
                    logger.info(f"✅ HNSW 索引构建完成: {indexed_count:,}/{vectors_count:,}")
                    return True

                # 每 30 秒打印一次进度（避免日志刷屏）
                now = time.time()
                if now - last_log_time >= 30:
                    pct = indexed_count / vectors_count * 100 if vectors_count > 0 else 0
                    speed = (indexed_count - last_indexed) / (now - phase2_start) if last_indexed >= 0 and now > phase2_start else 0
                    logger.info(
                        f"⏳ 索引进度: {indexed_count:,}/{vectors_count:,} ({pct:.1f}%) "
                        f"| status={status} | speed≈{speed:,.0f}/s"
                    )
                    last_log_time = now

                # 稳定性判断：连续 6 次（60 秒）无变化才认为停止
                # 必须在优化器已启动且 indexed > 0 之后才开始计数，
                # 避免优化器还没开始就被误判为"完成"
                if indexed_count == last_indexed and indexed_count > 0:
                    stable_count += 1
                    if stable_count >= 6:
                        if indexed_count >= vectors_count:
                            logger.info(f"✅ 索引构建完成（稳定）: {indexed_count:,}/{vectors_count:,}")
                            return True
                        else:
                            logger.warning(
                                f"⚠️ 索引数连续 60s 未变化 ({indexed_count:,}/{vectors_count:,})，"
                                f"可能部分 segment 未达阈值，停止等待"
                            )
                            return True
                else:
                    stable_count = 0
                last_indexed = indexed_count
            except Exception as e:
                logger.warning(f"查询索引状态失败: {e}")
            time.sleep(10)

        logger.warning(f"⚠️ 等待索引超时 ({timeout}s)，索引可能仍在后台构建")
        return False

    @retry_on_failure(max_retries=2, delay=1, backoff=2)
    def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        score_threshold: Optional[float] = None,
        filter_conditions: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[float, Dict[str, Any]]]:
        """
        向量检索 - 直接执行数据库检索，不处理向量格式
        
        Args:
            query_vector: 一维向量列表 (768维)
            top_k: 返回结果数量
            score_threshold: 相似度阈值
            filter_conditions: 过滤条件字典
        
        Returns:
            List[Tuple[float, Dict[str, Any]]]: (相似度分数, payload) 列表
        """
        try:
            search_filter = None
            if filter_conditions:
                search_filter = Filter(**filter_conditions)
            
            # 方法1: 使用 query_points (qdrant-client 1.7+)
            try:
                result = self.client.query_points(
                    collection_name=self.collection_name,
                    query=query_vector,
                    limit=top_k,
                    score_threshold=score_threshold,
                    query_filter=search_filter,
                    with_payload=True,
                )
                return [(hit.score, hit.payload) for hit in result.points]
            except AttributeError:
                # 方法2: 使用 search (旧版本)
                results = self.client.search(
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    limit=top_k,
                    score_threshold=score_threshold,
                    query_filter=search_filter,
                    with_payload=True,
                )
                return [(hit.score, hit.payload) for hit in results]
                
        except Exception as e:
            logger.error(f"❌ 检索失败: {e}")
            raise QdrantRetryableError(f"Search failed: {e}")

    @retry_on_failure(max_retries=2, delay=1, backoff=2)
    def count(self) -> int:
        """统计集合中向量总数"""
        try:
            result = self.client.count(
                collection_name=self.collection_name,
                exact=True,
            )
            return result.count
        except Exception as e:
            logger.error(f"❌ 统计失败: {e}")
            raise QdrantRetryableError(f"Count failed: {e}")

    def delete_collection(self) -> bool:
        """删除整个集合"""
        try:
            self.client.delete_collection(self.collection_name)
            logger.warning(f"🗑️ Collection {self.collection_name} 已删除")
            return True
        except Exception as e:
            logger.error(f"❌ 删除失败: {e}")
            return False

    def get_collection_info(self) -> Dict[str, Any]:
        """获取集合详细信息"""
        try:
            info = self.client.get_collection(self.collection_name)
            return {
                "status": getattr(info, 'status', 'unknown'),
                "vectors_count": getattr(info, 'vectors_count', getattr(info, 'points_count', 0)),
                "indexed_vectors_count": getattr(info, 'indexed_vectors_count', getattr(info, 'indexed_points_count', 0)),
                "segments_count": len(info.segments) if hasattr(info, 'segments') else 0,
            }
        except Exception as e:
            logger.error(f"❌ 获取信息失败: {e}")
            return {}


# ============ 单例 ============
_qdrant_wrapper = None

def get_qdrant_client() -> QdrantClientWrapper:
    global _qdrant_wrapper
    if _qdrant_wrapper is None:
        _qdrant_wrapper = QdrantClientWrapper()
    return _qdrant_wrapper