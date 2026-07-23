import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()


class Settings:
    """应用配置类"""
    
    # ===== DeepSeek 配置 =====
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    
    # ===== Qdrant 配置 =====
    QDRANT_URL: str = os.getenv("QDRANT_URL", "")
    QDRANT_API_KEY: str = os.getenv("QDRANT_API_KEY", "")
    QDRANT_COLLECTION_NAME: str = os.getenv("QDRANT_COLLECTION_NAME", "log_knowledge")

    # ===== RAG检索配置 =====
    RETRIEVER_TOP_K: int = 10
    RETRIEVER_SCORE_THRESHOLD: float = 0.0
    
    # ===== JWT 配置 =====
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key")
    ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    
    # ===== RAG切片配置 =====
    LOG_CHUNK_SIZE: int = int(os.getenv("LOG_CHUNK_SIZE", "500"))
    LOG_CHUNK_OVERLAP: int = int(os.getenv("LOG_CHUNK_OVERLAP", "50"))
    
    # ===== 检查关键配置是否完整 =====
    @classmethod
    def check_config(cls) -> bool:
        """检查必要配置是否已填写"""
        issues = []
        
        if not cls.DEEPSEEK_API_KEY or cls.DEEPSEEK_API_KEY == "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx":
            issues.append("❌ DEEPSEEK_API_KEY 未配置，请填写真实API Key")
        
        if not cls.QDRANT_URL or "xxxxxxxx" in cls.QDRANT_URL:
            issues.append("❌ QDRANT_URL 未配置，请填写真实Qdrant集群地址")
        
        if not cls.QDRANT_API_KEY or "xxxxxxxx" in cls.QDRANT_API_KEY:
            issues.append("❌ QDRANT_API_KEY 未配置，请填写真实API Key")
        
        if issues:
            print("\n" + "=" * 60)
            print("⚠️ 配置检查发现以下问题：")
            print("=" * 60)
            for issue in issues:
                print(f"  {issue}")
            print("=" * 60)
            print("请编辑 backend/.env 文件完成配置")
            return False
        
        print("✅ 所有配置项完整")
        return True


# 全局配置实例
settings = Settings()