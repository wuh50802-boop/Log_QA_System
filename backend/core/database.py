from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import os
from typing import Generator

# 数据库文件路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'app.db')}"

# 创建数据库引擎
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}  # SQLite 多线程支持
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 创建基类
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """依赖注入：获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库：创建所有表"""
    from models import user, log, qa_history, audit_log
    Base.metadata.create_all(bind=engine)
    _ensure_schema_migrations()
    print("✅ 数据库表创建完成")


def _ensure_schema_migrations():
    """
    轻量级迁移：为已存在的表补充新字段。
    SQLite 的 CREATE TABLE IF NOT EXISTS 不会添加新列，所以需要 ALTER TABLE。
    幂等：列已存在时跳过。
    """
    from sqlalchemy import text, inspect

    inspector = inspect(engine)

    if "qa_history" in inspector.get_table_names():
        existing_columns = {col["name"] for col in inspector.get_columns("qa_history")}
        if "conversation_id" not in existing_columns:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE qa_history ADD COLUMN conversation_id VARCHAR(64)"
                    )
                )
                # SQLite 不支持 CREATE INDEX IF NOT EXISTS 之前的 ALTER，单独建索引
                conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_qa_history_conversation_id "
                        "ON qa_history (conversation_id)"
                    )
                )
            print("✅ 已迁移 qa_history 表：新增 conversation_id 列")
        if "quality_check" not in existing_columns:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE qa_history ADD COLUMN quality_check TEXT"
                    )
                )
            print("✅ 已迁移 qa_history 表：新增 quality_check 列")