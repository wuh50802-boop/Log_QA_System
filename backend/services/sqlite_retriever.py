"""
SQLite 精确匹配检索器

从自然语言查询中提取技术标识符（如 blk_123、IP 地址、十六进制串），
直接用 LIKE 在数据库 logs 表中做精确子串匹配。

定位：作为向量检索（语义）和 BM25（关键词）的补充，专门处理具体标识符查询。
当 BM25 因模板去重漏掉同模板日志时，本检索器仍能精确找到包含目标标识符的日志。
"""
import re
import logging
from typing import List, Dict, Any, Optional

from sqlalchemy import or_
from models import Log

logger = logging.getLogger(__name__)


# ============ 标识符提取 ============
# 提取查询中可精确匹配的技术标识符
# 顺序有讲究：先匹配长模式，避免被短模式截断
_IDENTIFIER_PATTERNS = [
    re.compile(r'blk_[-]?\d+'),                  # HDFS block id: blk_123 / blk_-123
    re.compile(r'(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?'),  # IP[:port]: 10.250.19.102:8080
    re.compile(r'0x[0-9a-fA-F]+'),                # 十六进制: 0x1a2b
    re.compile(r'[0-9a-fA-F]{8,}'),               # 长十六进制串（UUID/哈希）
    re.compile(r'[A-Za-z_][A-Za-z0-9_\-\.]{4,}'), # 技术标识符（含字母、数字、._-）
]

# 过滤掉的自然语言词（不作为 LIKE 查询条件）
_STOP_WORDS = {
    'the', 'and', 'for', 'with', 'from', 'that', 'this', 'have', 'has',
    'was', 'were', 'are', 'been', 'being', 'will', 'would', 'could',
    'should', 'may', 'might', 'must', 'can', 'what', 'which', 'when',
    'where', 'why', 'how', 'who', 'error', 'warning', 'info', 'debug',
    'log', 'logs', 'find', 'search', 'query', 'show', 'list', 'get',
    'all', 'any', 'some', 'about', 'into', 'than', 'then', 'them',
    'these', 'those', 'their', 'there', 'here', 'they', 'you', 'your',
    'recent', 'latest', 'last', 'first', 'most', 'more', 'less', 'very',
    'errors', 'warnings', 'infos', 'debugs', 'failure', 'fail', 'failed',
    'timeout', 'connection', 'server', 'client', 'service', 'system',
    '的', '了', '是', '在', '有', '和', '与', '或', '及', '等', '中',
    '问题', '异常', '错误', '警告', '日志', '查询', '查找', '搜索',
    '最近', '最新', '前面', '前面', '后面', '所有', '哪些', '什么',
}


def extract_identifiers(query: str) -> List[str]:
    """
    从自然语言查询中提取可精确匹配的技术标识符。

    规则：
        - 匹配 blk_xxx、IP、十六进制串、含字母数字的技术词
        - 过滤停用词（如 error、查询、问题 等通用词）
        - 过滤过短的词（< 4 字符）
        - 去重保序

    Examples:
        >>> extract_identifiers("blk_222 的 timeout 问题")
        ['blk_222']
        >>> extract_identifiers("10.250.19.102 连接失败")
        ['10.250.19.102']
    """
    identifiers = []
    seen = set()

    for pattern in _IDENTIFIER_PATTERNS:
        for match in pattern.findall(query):
            match_lower = match.lower()
            # 过滤停用词、过短词
            if match_lower in _STOP_WORDS:
                continue
            if len(match) < 4:
                continue
            if match_lower in seen:
                continue
            seen.add(match_lower)
            identifiers.append(match)

    return identifiers


class SQLiteRetriever:
    """
    SQLite 精确匹配检索器。

    与 BM25/向量检索的区别：
        - BM25：基于词频统计的关键词匹配（模板去重后会漏同模板日志）
        - 向量：基于语义相似度（无法精确匹配具体标识符）
        - SQLite：直接 LIKE '%标识符%' 子串匹配（一定能找到包含该串的日志）

    评分：
        SQLite 无相关性评分，按时间倒序返回，score = 1/rank。
        这样 RRF 融合时 rank 越靠前贡献越大，和 BM25/向量同量级。
    """

    def __init__(self):
        # 延迟导入避免循环依赖
        from core.database import SessionLocal
        self._SessionLocal = SessionLocal
        logger.info("✅ SQLiteRetriever 初始化完成")

    def search(
        self,
        query: str,
        top_k: int = 10,
        filter_params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        从查询中提取标识符，用 LIKE 精确匹配数据库。

        Args:
            query: 用户查询文本
            top_k: 返回结果数
            filter_params: 过滤条件（level, service）

        Returns:
            [{'log_id': int, 'payload': {...}, 'score': float}, ...]
            如果查询中无标识符，返回空列表（不拖慢通用查询）。
        """
        identifiers = extract_identifiers(query)
        if not identifiers:
            logger.debug("SQLite 检索：查询中无可识别标识符，跳过")
            return []

        logger.info(f"SQLite 检索：提取到标识符 {identifiers}")

        try:
            with self._SessionLocal() as session:
                q = session.query(Log)

                # 应用过滤条件
                if filter_params:
                    if filter_params.get('level'):
                        q = q.filter(Log.level == filter_params['level'])
                    if filter_params.get('service'):
                        q = q.filter(Log.service == filter_params['service'])

                # OR 条件匹配任一标识符
                conditions = [Log.message.like(f'%{ident}%') for ident in identifiers]
                q = q.filter(or_(*conditions))

                # 按时间倒序，取 top_k
                q = q.order_by(Log.timestamp.desc()).limit(top_k)

                logs = q.all()

                results = []
                for rank, log in enumerate(logs, 1):
                    payload = {
                        'log_id': log.id,
                        'level': log.level,
                        'service': log.service,
                        'timestamp': str(log.timestamp),
                        'chunk_text': log.message,
                        'source': log.service,  # SQLite 表无 source 字段，用 service 兜底
                    }
                    # 评分：1/rank，rank 越靠前分数越高
                    results.append({
                        'log_id': log.id,
                        'payload': payload,
                        'score': 1.0 / rank,
                    })

                logger.info(f"SQLite 检索完成，返回 {len(results)} 条结果")
                return results

        except Exception as e:
            logger.error(f"SQLite 检索失败: {e}")
            return []


# ============ 模块级单例 ============
_sqlite_retriever: Optional[SQLiteRetriever] = None


def get_sqlite_retriever() -> SQLiteRetriever:
    """获取 SQLiteRetriever 单例"""
    global _sqlite_retriever
    if _sqlite_retriever is None:
        _sqlite_retriever = SQLiteRetriever()
    return _sqlite_retriever


def sqlite_search(
    query: str,
    top_k: int = 10,
    filter_params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """便捷调用函数"""
    return get_sqlite_retriever().search(query, top_k, filter_params)
