"""
NL2SQL 模块 - 聚合类问题的 SQL 路由路径

流程：
1. 意图识别：判断是否为聚合/统计类问题（关键词 + LLM 兜底）
2. SQL 生成：用 DeepSeek 把自然语言转 SQL（带 schema 提示与安全约束）
3. SQL 校验：禁止 DROP/DELETE/UPDATE/INSERT 等写操作，强制带 LIMIT
4. SQL 执行：在 app.db 的 logs 表上执行
5. 结果格式化：转为 QAResult.answer（自然语言 + 表格 Markdown）

复用：
- LLM: services.llm_client.DeepSeekClient
- DB: core.database.engine
- QAResult: services.qa_pipeline.QAResult
"""
import logging
import re
import time
import sqlite3
from typing import List, Dict, Any, Optional, Literal

from services.llm_client import DeepSeekClient, ChatMessage
from services.qa_pipeline import QAResult

logger = logging.getLogger("nl2sql")

# ============================================================
# 常量
# ============================================================

# logs 表 schema（提供给 LLM 的提示）
SCHEMA_HINT = """表名: logs
字段:
- id (INTEGER, 主键)
- timestamp (DATETIME, 日志时间，格式 'YYYY-MM-DD HH:MM:SS')
- level (VARCHAR(10), 日志级别: INFO / WARNING / ERROR / DEBUG)
- service (VARCHAR(50), 服务名: auth-service / order-service / payment-service / user-service / notification-service)
- ip (VARCHAR(15), 来源 IP)
- message (TEXT, 日志消息内容)
- trace_id (VARCHAR(8), 链路追踪 ID)
- created_at (DATETIME, 入库时间)
索引: level, service, trace_id, (timestamp, level), (service, timestamp)
数据库: SQLite (app.db)"""

# 意图识别关键词（命中任一即认为是聚合类）
AGGREGATION_KEYWORDS = [
    "统计", "数量", "分布", "占比", "比例", "排名", "排行", "Top N", "TopN",
    "最常见", "最频繁", "最多", "最少", "几个", "多少条", "多少个", "共有",
    "各服务", "各级别", "每个服务", "每个级别", "交叉统计", "按服务", "按级别",
    "时间范围", "时间分布", "按天", "按小时", "趋势",
    "对比", "比较", "差异", "vs",
]

# SQL 安全校验：禁止写操作
FORBIDDEN_PATTERNS = [
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|CREATE|TRUNCATE|ATTACH|DETACH|PRAGMA)\b",
    r";\s*\w",  # 多语句
    r"--",       # SQL 注释
    r"/\*",
]


# ============================================================
# 1. 意图识别
# ============================================================

def detect_intent(question: str) -> Literal["nl2sql", "rag"]:
    """
    判断问题意图：聚合/统计类 → nl2sql，其他 → rag

    采用关键词匹配（快速、零成本），覆盖大部分场景。
    命中任一聚合关键词即路由到 NL2SQL。
    """
    q = question.lower()
    for kw in AGGREGATION_KEYWORDS:
        if kw.lower() in q:
            return "nl2sql"
    return "rag"


# ============================================================
# 2. SQL 生成（LLM）
# ============================================================

SQL_SYSTEM_PROMPT = f"""你是日志分析 SQL 生成器。根据用户问题生成 SQLite 查询 SQL。

{SCHEMA_HINT}

规则（必须严格遵守）：
1. 只生成 SELECT 语句，禁止任何写操作（DROP/DELETE/UPDATE/INSERT 等）
2. 必须返回聚合结果，不要返回原始日志行（除非用户明确要求"列出/找出具体日志"）
3. 统计类问题用 COUNT(*) + GROUP BY
4. Top N 类问题用 ORDER BY ... LIMIT N
5. 时间范围问题用 MIN/MAX(timestamp) 或 GROUP BY date(timestamp)
6. 服务名/级别过滤用 WHERE service=... / level=...
7. 默认加 LIMIT 100 防止结果过大
8. 只输出 SQL，不要解释，不要 markdown 代码块标记

示例：
- 问: "每个服务各有多少条日志？" → SELECT service, COUNT(*) AS cnt FROM logs GROUP BY service ORDER BY cnt DESC LIMIT 100
- 问: "统计 INFO/WARNING/ERROR/DEBUG 各多少条" → SELECT level, COUNT(*) AS cnt FROM logs GROUP BY level ORDER BY cnt DESC LIMIT 100
- 问: "找出最常见的 5 类错误" → SELECT message, COUNT(*) AS cnt FROM logs WHERE level='ERROR' GROUP BY message ORDER BY cnt DESC LIMIT 5
- 问: "日志的时间范围" → SELECT MIN(timestamp) AS start, MAX(timestamp) AS end FROM logs
- 问: "按天统计日志数量" → SELECT date(timestamp) AS day, COUNT(*) AS cnt FROM logs GROUP BY day ORDER BY day LIMIT 100
"""


def generate_sql(question: str, llm_client: Optional[DeepSeekClient] = None) -> str:
    """用 LLM 把自然语言转 SQL"""
    client = llm_client or DeepSeekClient()

    messages = [
        ChatMessage(role="system", content=SQL_SYSTEM_PROMPT),
        ChatMessage(role="user", content=question),
    ]

    resp = client.chat(messages, temperature=0.0, max_tokens=500)
    sql = resp.content.strip()

    # 清理可能的 markdown 标记
    sql = re.sub(r"^```(?:sql)?\s*", "", sql)
    sql = re.sub(r"\s*```$", "", sql)
    sql = sql.strip()

    # 只取第一条语句（防多语句）
    if ";" in sql:
        sql = sql.split(";")[0].strip()

    # 强制加 LIMIT（若没有）
    if not re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        sql = f"{sql} LIMIT 100"

    return sql, resp.total_tokens


# ============================================================
# 3. SQL 校验
# ============================================================

def validate_sql(sql: str) -> tuple[bool, str]:
    """
    SQL 安全校验
    返回 (is_valid, error_message)
    """
    sql_upper = sql.upper()
    # 必须是 SELECT
    if not sql_upper.strip().startswith("SELECT"):
        return False, "非 SELECT 语句"
    # 检查禁止模式
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, sql_upper):
            return False, f"包含禁止操作: {pattern}"
    return True, ""


# ============================================================
# 4. SQL 执行
# ============================================================

def execute_sql(sql: str, db_path: str = "app.db") -> Dict[str, Any]:
    """
    执行 SQL，返回结构化结果

    Returns:
        {
            "columns": [...],
            "rows": [[...], ...],
            "row_count": int,
            "execution_time": float,
            "error": Optional[str]
        }
    """
    t0 = time.time()
    result = {
        "columns": [],
        "rows": [],
        "row_count": 0,
        "execution_time": 0.0,
        "error": None,
    }
    try:
        # 用只读模式打开，双重保险
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        result["columns"] = [desc[0] for desc in cur.description] if cur.description else []
        result["rows"] = [list(r) for r in rows]
        result["row_count"] = len(rows)
        conn.close()
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"SQL 执行失败: {sql}\n错误: {e}")
    result["execution_time"] = round(time.time() - t0, 3)
    return result


# ============================================================
# 5. 结果格式化
# ============================================================

def format_sql_result(question: str, sql: str, result: Dict[str, Any]) -> str:
    """把 SQL 结果格式化为 QAResult.answer（与 evidence_chain 模板风格一致）"""
    if result["error"]:
        return f"""【问题理解】{question}

【关键证据】SQL 查询失败：{result['error']}

【分析推断】SQL 生成或执行出错，无法获取统计数据。

【结论建议】请改用自然语言重新描述问题，或拆分为更简单的查询。

【置信度】低"""

    cols = result["columns"]
    rows = result["rows"]
    n = result["row_count"]

    # 表格 Markdown
    if n == 0:
        table_md = "（无匹配数据）"
    else:
        header = "| " + " | ".join(str(c) for c in cols) + " |"
        separator = "| " + " | ".join("---" for _ in cols) + " |"
        body_lines = []
        for r in rows[:20]:  # 最多展示 20 行
            body_lines.append("| " + " | ".join(str(v) for v in r) + " |")
        table_md = header + "\n" + separator + "\n" + "\n".join(body_lines)
        if n > 20:
            table_md += f"\n\n（共 {n} 行，仅展示前 20 行）"

    # 自然语言总结
    summary = _generate_summary(question, cols, rows, n)

    return f"""【问题理解】{question}

【关键证据】
SQL 查询：
```sql
{sql}
```
查询结果（{n} 行）：
{table_md}

【分析推断】{summary}

【结论建议】基于以上统计数据，可针对性排查异常服务/级别/时间段的日志模式。

【置信度】高"""


def _generate_summary(question: str, cols: List[str], rows: List[List[Any]], n: int) -> str:
    """从 SQL 结果生成简短自然语言总结"""
    if n == 0:
        return "查询未返回数据，可能无符合条件的日志。"

    # 单行单列（标量结果，如总数）
    if n == 1 and len(cols) == 1:
        return f"查询结果：{cols[0]} = {rows[0][0]}"

    # 单行多列（如 MIN/MAX 时间范围）
    if n == 1 and len(cols) > 1:
        parts = [f"{c}={r}" for c, r in zip(cols, rows[0])]
        return "查询结果：" + "，".join(parts)

    # 多行（GROUP BY 结果）
    if len(cols) >= 2:
        # 找计数列
        cnt_col_idx = None
        for i, c in enumerate(cols):
            if "cnt" in c.lower() or "count" in c.lower() or "数量" in c:
                cnt_col_idx = i
                break
        if cnt_col_idx is not None:
            # 找 Top 1
            try:
                top = max(rows, key=lambda r: r[cnt_col_idx] if r[cnt_col_idx] else 0)
                top_label = top[0] if len(top) > 0 else "?"
                top_cnt = top[cnt_col_idx]
                return f"共 {n} 组统计结果，最高的是 {top_label}（{top_cnt} 条）。详见上方表格。"
            except Exception:
                pass

    return f"共返回 {n} 行结果，详见上方表格。"


# ============================================================
# 6. 入口：ask
# ============================================================

def ask(question: str, db_path: str = "app.db") -> QAResult:
    """
    NL2SQL 路径入口：聚合类问题走 SQL 查询

    Args:
        question: 用户问题
        db_path: 数据库路径

    Returns:
        QAResult（retriever_type="nl2sql"）
    """
    t0 = time.time()

    # 1. 生成 SQL
    try:
        sql, tokens = generate_sql(question)
    except Exception as e:
        logger.error(f"SQL 生成失败: {e}")
        return QAResult(
            question=question,
            answer=f"【问题理解】{question}\n\n【关键证据】SQL 生成失败：{e}\n\n【置信度】低",
            confidence="低",
            retrieval_time=0.0,
            llm_time=round(time.time() - t0, 3),
            total_time=round(time.time() - t0, 3),
            retriever_type="nl2sql",
            total_tokens=0,
        )

    llm_time = round(time.time() - t0, 3)
    logger.info(f"NL2SQL 生成 SQL: {sql}")

    # 2. 校验 SQL
    is_valid, err = validate_sql(sql)
    if not is_valid:
        logger.warning(f"SQL 校验失败: {err} (sql={sql})")
        return QAResult(
            question=question,
            answer=f"【问题理解】{question}\n\n【关键证据】SQL 校验失败：{err}\n\n【置信度】低",
            confidence="低",
            retrieval_time=0.0,
            llm_time=llm_time,
            total_time=round(time.time() - t0, 3),
            retriever_type="nl2sql",
            total_tokens=tokens,
        )

    # 3. 执行 SQL
    t_sql = time.time()
    result = execute_sql(sql, db_path)
    retrieval_time = round(time.time() - t_sql, 3)

    # 4. 格式化结果
    answer = format_sql_result(question, sql, result)

    return QAResult(
        question=question,
        answer=answer,
        sources=[],  # NL2SQL 路径无日志来源
        source_refs=[],
        confidence="高",
        total_tokens=tokens,
        retrieval_time=retrieval_time,
        llm_time=llm_time,
        total_time=round(time.time() - t0, 3),
        retriever_type="nl2sql",
    )
