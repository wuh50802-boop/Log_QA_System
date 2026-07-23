from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from api import auth

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============ 系统预热 ============
def warmup():
    """系统预热 - 加载所有模型和索引"""
    logger.info("🔥 系统预热中...")
    
    # 1. 预加载 jieba 词典
    try:
        import jieba
        jieba.lcut("预热测试")
        logger.info("   ✅ jieba 词典加载完成")
    except Exception as e:
        logger.warning(f"   ⚠️ jieba 加载失败: {e}")
    
    # 2. 预加载 BGE 模型
    try:
        from services.embedder import get_embedder
        embedder = get_embedder()
        embedder.encode_single("预热测试")
        logger.info("   ✅ BGE 模型加载完成")
    except Exception as e:
        logger.warning(f"   ⚠️ BGE 模型加载失败: {e}")
    
    # 3. 预加载 BM25 索引
    try:
        from services.bm25_retriever import get_bm25_retriever
        retriever = get_bm25_retriever()
        retriever.get_document_count()
        logger.info("   ✅ BM25 索引加载完成")
    except Exception as e:
        logger.warning(f"   ⚠️ BM25 加载失败: {e}")
    
    # 4. 预加载向量检索（触发 Qdrant 连接）
    try:
        from services.qdrant_client import get_qdrant_client
        client = get_qdrant_client()
        client.count()
        logger.info("   ✅ Qdrant 连接完成")
    except Exception as e:
        logger.warning(f"   ⚠️ Qdrant 连接失败: {e}")
    
    # 5. 预加载混合检索器（只初始化，不执行检索）
    try:
        from services.hybrid_retriever import get_hybrid_retriever_async
        retriever = get_hybrid_retriever_async()
        # 触发 BM25 和向量检索器初始化（通过访问属性）
        # 但不执行检索，避免 asyncio.run() 问题
        _ = retriever.vector_retriever
        _ = retriever.bm25_retriever
        logger.info("   ✅ 混合检索器初始化完成")
    except Exception as e:
        logger.warning(f"   ⚠️ 混合检索器初始化失败: {e}")
    
    logger.info("✅ 系统预热完成！")


# ============ 应用生命周期 ============
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("🚀 应用启动中...")
    warmup()
    logger.info("✅ 应用启动完成！")
    
    yield
    
    # 关闭时执行
    logger.info("🛑 应用关闭中...")
    try:
        from services.hybrid_retriever import get_hybrid_retriever_async
        retriever = get_hybrid_retriever_async()
        retriever.close()
        logger.info("   ✅ 混合检索器已关闭")
    except Exception as e:
        logger.warning(f"   ⚠️ 关闭混合检索器失败: {e}")
    logger.info("✅ 应用已关闭")


# ============ 创建应用 ============
app = FastAPI(
    title="日志智能问答系统 API",
    description="基于LLM的应用运行日志智能问答系统",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth.router, prefix="/api/auth", tags=["认证"])

# 健康检查
@app.get("/")
async def root():
    return {"message": "日志智能问答系统运行中", "status": "healthy"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}