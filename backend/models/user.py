from sqlalchemy import Column, Integer, String, DateTime, Enum
from sqlalchemy.sql import func
import enum
from core.database import Base


class UserRole(str, enum.Enum):
    """用户角色枚举"""
    ADMIN = "admin"
    USER = "user"


class User(Base):
    """用户表"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(50), unique=True, index=True, nullable=False, comment="用户名")
    password_hash = Column(String(255), nullable=False, comment="密码哈希（bcrypt加密）")
    role = Column(Enum(UserRole), default=UserRole.USER, nullable=False, comment="用户角色")
       
     # 🔧 修改这里：使用 DateTime 类型，default 使用 Python 的 datetime.now
    from datetime import datetime
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")
    
    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}')>"
    
    """
    字段	        类型	     说明
    id	I           nteger	    主键，自增
    username	    String(50)	用户名，唯一
    password_hash	String(255)	密码哈希（存储bcrypt加密后的密文）
    role	        Enum	    角色：admin / user
    created_at	    DateTime	创建时间（自动生成）
    updated_at	    DateTime	更新时间（自动更新）
    """