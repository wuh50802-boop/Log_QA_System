from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func
from core.database import Base
from datetime import datetime

class AuditLog(Base):
    """审计日志表（记录敏感操作）"""
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, nullable=True, index=True, comment="操作用户ID（未登录为NULL）")
    username = Column(String(50), nullable=True, comment="操作用户名")
    action = Column(String(50), nullable=False, comment="操作类型: login/ask/feedback/delete等")
    resource = Column(String(100), nullable=True, comment="操作资源")
    details = Column(Text, nullable=True, comment="操作详情（JSON格式）")
    ip_address = Column(String(45), nullable=True, comment="客户端IP")
    
    created_at = Column(DateTime, default=datetime.now, comment="操作时间")
    def __repr__(self):
        return f"<AuditLog(id={self.id}, action='{self.action}', username='{self.username}')>"