from sqlalchemy import Column, Integer, String, DateTime, Text, Index
from sqlalchemy.sql import func
from core.database import Base
from datetime import datetime

class Log(Base):
    """日志表（存储清洗后的日志）"""
    __tablename__ = "logs"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, comment="日志时间")
    level = Column(String(10), nullable=False, index=True, comment="日志级别: INFO/WARNING/ERROR/DEBUG")
    service = Column(String(50), nullable=False, index=True, comment="服务名称")
    ip = Column(String(15), comment="来源IP地址")
    message = Column(Text, nullable=False, comment="日志消息内容")
    trace_id = Column(String(8), index=True, comment="链路追踪ID")
    
    created_at = Column(DateTime, default=datetime.now, comment="入库时间")
    # 复合索引（加速按时间和级别查询）
    __table_args__ = (
        Index('idx_logs_time_level', 'timestamp', 'level'),
        Index('idx_logs_service_time', 'service', 'timestamp'),
    )
    
    def __repr__(self):
        return f"<Log(id={self.id}, level='{self.level}', service='{self.service}', timestamp='{self.timestamp}')>"
    
    """
    字段	    类型	    说明
    id	        Integer	    主键，自增
    timestamp	DateTime	日志发生时间（解析自日志内容）
    level	    String(10)	日志级别（索引，加速过滤查询）
    service	    String(50)	服务名（索引）
    ip	        String(15)	来源IP（清洗时校验格式）
    message	    Text	    日志消息（可能较长，使用Text类型）
    trace_id	String(8)	链路追踪ID（索引）
    created_at	DateTime	入库时间（自动生成）
    """