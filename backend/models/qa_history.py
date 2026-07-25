from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Enum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from core.database import Base
from datetime import datetime

class FeedbackType(str, enum.Enum):
    """反馈类型枚举"""
    LIKE = "like"
    DISLIKE = "dislike"
    NONE = "none"


class QAHistory(Base):
    """问答历史表"""
    __tablename__ = "qa_history"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True, comment="提问用户ID")
    question = Column(Text, nullable=False, comment="用户问题")
    answer = Column(Text, nullable=False, comment="系统回答")
    sources = Column(Text, nullable=True, comment="引用的日志来源（JSON格式）")
    feedback = Column(Enum(FeedbackType), default=FeedbackType.NONE, comment="用户反馈: like/dislike/none")
    created_at = Column(DateTime, default=datetime.now, comment="提问时间")
    # 多轮对话：同一 conversation_id 下的多条 Q&A 组成一个会话
    conversation_id = Column(String(64), nullable=True, index=True, comment="会话ID，同一会话的多条记录共享此ID")
    # 质量自检结果（JSON 字符串：{passed,score,issues,warnings,suggestions}），NULL 表示未执行
    quality_check = Column(Text, nullable=True, comment="回答质量自检结果（JSON格式）")
    # 关联用户（ORM关系，方便联表查询）
    user = relationship("User", backref="qa_histories")

    def __repr__(self):
        return f"<QAHistory(id={self.id}, user_id={self.user_id}, conversation_id='{self.conversation_id}', created_at='{self.created_at}')>"
    """
    字段	            类型	        说明
    id	                Integer	    主键，自增
    user_id	            Integer	    外键→users.id，记录谁提的问题
    question	        Text	    用户原始问题
    answer	            Text	    系统生成的回答
    sources	            Text	    引用的日志来源（存JSON字符串）
    feedback	        Enum	    用户反馈：like / dislike / none
    created_at	        DateTime	提问时间（自动生成）
    conversation_id	    String	    会话ID，同一会话的多条 Q&A 共享；NULL 表示旧数据或独立问答
    """