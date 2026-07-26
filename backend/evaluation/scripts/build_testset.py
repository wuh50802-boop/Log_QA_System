"""


设计思路：
- 8 类场景 × 3 难度，共 60 个问答对
- 每个问答对的「应引用日志」来自数据库中真实存在的日志条目
- 标准答案基于真实日志内容撰写，不依赖 LLM
- 输出 testset.json，供 RAGAS 评测脚本调用

场景分布：
  error_diagnosis   错误诊断  (12)
  service_health    服务健康  (8)
  user_activity     用户行为  (8)
  performance       性能问题  (10)
  security          安全问题  (8)
  resource          资源问题  (6)
  aggregation       统计聚合  (5)
  time_analysis     时间分析  (3)

难度分布：
  easy   25  单条直接查询
  medium 22  多条综合 / 简单推理
  hard   13  跨服务 / 聚合 / 根因
"""
import sqlite3
import os
import json
import re
from datetime import datetime
from collections import defaultdict, Counter

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'app.db')
OUT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'testset.json')


def fmt_log(row: tuple) -> str:
    """格式化日志为参考上下文字符串"""
    log_id, ts, level, service, ip, trace_id, message = row
    return (f"[ID:{log_id}] {service} / {level} / {ts} / "
            f"ip={ip} / trace={trace_id} / {message}")


def fetch_logs(cur, where: str = "", params: tuple = (), limit: int = 50) -> list:
    """查询日志并返回格式化后的列表"""
    sql = ("SELECT id, timestamp, level, service, ip, trace_id, message "
           "FROM logs")
    if where:
        sql += f" WHERE {where}"
    sql += f" ORDER BY id LIMIT {int(limit)}"
    cur.execute(sql, params)
    return [fmt_log(r) for r in cur.fetchall()]


def fetch_log_ids(cur, where: str = "", params: tuple = (), limit: int = 50) -> list:
    sql = "SELECT id FROM logs"
    if where:
        sql += f" WHERE {where}"
    sql += f" ORDER BY id LIMIT {int(limit)}"
    cur.execute(sql, params)
    return [r[0] for r in cur.fetchall()]


def fetch_count(cur, where: str = "", params: tuple = ()) -> int:
    sql = "SELECT COUNT(*) FROM logs"
    if where:
        sql += f" WHERE {where}"
    cur.execute(sql, params)
    return cur.fetchone()[0]


def fetch_group_counts(cur, select: str, where: str = "", params: tuple = ()) -> list:
    """GROUP BY 查询，返回 [(key, count), ...]"""
    sql = f"SELECT {select}, COUNT(*) FROM logs"
    if where:
        sql += f" WHERE {where}"
    sql += f" GROUP BY {select} ORDER BY COUNT(*) DESC, {select} ASC"
    cur.execute(sql, params)
    return cur.fetchall()


# ============================================================
# QA 规格定义
# 每条 spec 是一个 dict，build 函数会用它去 DB 取真实日志
# ============================================================

# 字段说明：
#   id, scenario, difficulty, user_input, reference（标准答案）
#   find: 一个函数 (cur) -> (log_ids, contexts, extra_tags)
#         用于从 DB 取真实日志作为 reference_contexts
QA_SPECS = []


def spec(sid, scenario, difficulty, question, answer, find_fn):
    QA_SPECS.append({
        "id": sid,
        "scenario": scenario,
        "difficulty": difficulty,
        "user_input": question,
        "reference": answer,
        "find": find_fn,
    })


# ------------------ 错误诊断（12 条） ------------------

spec("qa_001", "error_diagnosis", "easy",
     "auth-service 出现过 ERROR 级别的 NullPointerException 吗？请列出相关日志。",
     "是，auth-service 出现过 ERROR 级别的 NullPointerException in UserService 日志。这些日志说明 UserService 模块发生了空指针异常，建议检查 UserService 的对象初始化与外部依赖注入。",
     lambda cur: (
         fetch_log_ids(cur, "service=? AND level=? AND message LIKE ?", ("auth-service", "ERROR", "%NullPointerException%"), 5),
         fetch_logs(cur, "service=? AND level=? AND message LIKE ?", ("auth-service", "ERROR", "%NullPointerException%"), 5),
         {"services": ["auth-service"], "levels": ["ERROR"], "keywords": ["NullPointerException"]}
     ))

spec("qa_002", "error_diagnosis", "easy",
     "找出 payment-service 中所有 SSL handshake failed 的日志。",
     "payment-service 中存在 SSL handshake failed 的 ERROR 日志，说明支付服务在与外部 HTTPS 端点建立连接时 SSL 握手失败，常见原因是证书过期/不受信任或 TLS 版本不匹配。",
     lambda cur: (
         fetch_log_ids(cur, "service=? AND message LIKE ?", ("payment-service", "%SSL handshake failed%"), 5),
         fetch_logs(cur, "service=? AND message LIKE ?", ("payment-service", "%SSL handshake failed%"), 5),
         {"services": ["payment-service"], "levels": ["ERROR"], "keywords": ["SSL handshake failed"]}
     ))

spec("qa_003", "error_diagnosis", "easy",
     "哪些日志记录了 OutOfMemoryError: Java heap space？",
     "存在 OutOfMemoryError: Java heap space 的 ERROR 日志，说明 JVM 堆内存耗尽。建议检查堆内存配置（-Xmx）以及是否存在内存泄漏。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ?", ("%OutOfMemoryError: Java heap space%",), 5),
         fetch_logs(cur, "message LIKE ?", ("%OutOfMemoryError: Java heap space%",), 5),
         {"services": ["notification-service"], "levels": ["ERROR"], "keywords": ["OutOfMemoryError"]}
     ))

spec("qa_004", "error_diagnosis", "easy",
     "找出所有 Transaction rollback due to deadlock 的日志。",
     "存在 Transaction rollback due to deadlock 的 ERROR 日志，说明数据库事务因死锁被回滚。常见原因是多个事务以不同顺序获取同一组锁。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ?", ("%Transaction rollback due to deadlock%",), 5),
         fetch_logs(cur, "message LIKE ?", ("%Transaction rollback due to deadlock%",), 5),
         {"services": ["auth-service", "notification-service", "order-service"], "levels": ["ERROR"], "keywords": ["deadlock"]}
     ))

spec("qa_005", "error_diagnosis", "easy",
     "找出 File not found: /var/log/app.log 的 ERROR 日志。",
     "存在 File not found: /var/log/app.log 的 ERROR 日志，说明应用尝试访问 /var/log/app.log 文件但文件不存在。应检查文件路径配置或文件是否被误删。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ?", ("%File not found: /var/log/app.log%",), 5),
         fetch_logs(cur, "message LIKE ?", ("%File not found: /var/log/app.log%",), 5),
         {"services": ["user-service", "notification-service"], "levels": ["ERROR"], "keywords": ["File not found"]}
     ))

spec("qa_006", "error_diagnosis", "easy",
     "哪些日志记录了 Network unreachable？",
     "存在 Network unreachable 的 ERROR 日志，说明服务无法访问外部网络。可能是网卡故障、DNS 解析失败或路由配置问题。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ?", ("%Network unreachable%",), 5),
         fetch_logs(cur, "message LIKE ?", ("%Network unreachable%",), 5),
         {"services": ["order-service", "payment-service"], "levels": ["ERROR"], "keywords": ["Network unreachable"]}
     ))

spec("qa_007", "error_diagnosis", "medium",
     "auth-service 的 ERROR 日志中最常见的错误类型是什么？请结合具体日志说明。",
     "auth-service 的 ERROR 日志主要包含 NullPointerException in UserService、Rate limit exceeded、Invalid token provided、Connection timeout to database、Transaction rollback due to deadlock 等类型。其中 NullPointerException in UserService 和 Rate limit exceeded 出现频次较高，建议重点排查 UserService 代码以及限流策略。",
     lambda cur: (
         fetch_log_ids(cur, "service=? AND level=?", ("auth-service", "ERROR"), 8),
         fetch_logs(cur, "service=? AND level=?", ("auth-service", "ERROR"), 8),
         {"services": ["auth-service"], "levels": ["ERROR"], "keywords": ["NullPointerException", "Rate limit", "Invalid token"]}
     ))

spec("qa_008", "error_diagnosis", "medium",
     "notification-service 出现 OutOfMemoryError 时涉及哪些日志？可能原因是什么？",
     "notification-service 出现 OutOfMemoryError: Java heap space 的 ERROR 日志，表明 JVM 堆内存不足。可能原因包括：1) 堆内存配置过小（-Xmx）；2) 处理大批量通知时存在内存泄漏；3) 大对象未及时释放。建议增大堆内存并排查通知批量处理的代码路径。",
     lambda cur: (
         fetch_log_ids(cur, "service=? AND message LIKE ?", ("notification-service", "%OutOfMemoryError%"), 5),
         fetch_logs(cur, "service=? AND message LIKE ?", ("notification-service", "%OutOfMemoryError%"), 5),
         {"services": ["notification-service"], "levels": ["ERROR"], "keywords": ["OutOfMemoryError"]}
     ))

spec("qa_009", "error_diagnosis", "medium",
     "payment-service 的 ERROR 日志有哪几类？请分类列出。",
     "payment-service 的 ERROR 日志主要包括：NullPointerException in UserService、Network unreachable、Invalid token provided、Rate limit exceeded、SSL handshake failed、Connection timeout to database 等类型。可分为代码缺陷（NullPointerException）、外部依赖（Network/SSL/Connection timeout）、限流（Rate limit）和安全（Invalid token）四类。",
     lambda cur: (
         fetch_log_ids(cur, "service=? AND level=?", ("payment-service", "ERROR"), 10),
         fetch_logs(cur, "service=? AND level=?", ("payment-service", "ERROR"), 10),
         {"services": ["payment-service"], "levels": ["ERROR"], "keywords": ["NullPointerException", "Network", "SSL", "Invalid token"]}
     ))

spec("qa_010", "error_diagnosis", "hard",
     "统计每个服务出现的 ERROR 日志数量并找出错误最多的服务。",
     "按服务统计 ERROR 日志数量：user-service、notification-service、auth-service、payment-service、order-service 均有较多 ERROR 日志，其中 user-service 的 ERROR 数量最多，其次是 notification-service。建议优先排查 user-service 的稳定性问题。",
     lambda cur: (
         [],
         [f"{svc} / ERROR: {cnt} 条" for svc, cnt in fetch_group_counts(cur, "service", "level='ERROR'")],
         {"levels": ["ERROR"], "keywords": ["aggregation"]}
     ))

spec("qa_011", "error_diagnosis", "hard",
     "分析所有 NullPointerException 日志，说明涉及哪些服务和级别。",
     "NullPointerException in UserService 同时出现在 ERROR 和 WARNING（带 retry in 5s 后缀）两种级别中，覆盖 order-service、notification-service、user-service、payment-service、auth-service 等多个服务，说明 UserService 模块存在跨服务的共性缺陷，应作为高优先级问题修复。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ?", ("%NullPointerException%",), 10),
         fetch_logs(cur, "message LIKE ?", ("%NullPointerException%",), 10),
         {"services": ["order-service", "notification-service", "user-service", "payment-service", "auth-service"],
          "levels": ["ERROR", "WARNING"], "keywords": ["NullPointerException"]}
     ))

spec("qa_012", "error_diagnosis", "hard",
     "统计每种 ERROR 消息在所有服务中出现的次数，找出最频繁的错误。",
     "主要 ERROR 消息包括：NullPointerException in UserService、File not found: /var/log/app.log、Network unreachable、Invalid token provided、Rate limit exceeded、Connection timeout to database、SSL handshake failed、Transaction rollback due to deadlock、OutOfMemoryError: Java heap space 等。其中 NullPointerException 和 File not found 出现频次较高。",
     lambda cur: (
         [],
         [f"{msg}: {cnt} 条" for msg, cnt in fetch_group_counts(cur, "message", "level='ERROR'", )],
         {"levels": ["ERROR"], "keywords": ["aggregation"]}
     ))


# ------------------ 服务健康（8 条） ------------------

spec("qa_013", "service_health", "easy",
     "order-service 的 Health check passed 日志有哪些？",
     "order-service 存在 Health check passed 的 INFO 日志，说明健康检查探针在该时间点通过了健康检查，服务运行正常。",
     lambda cur: (
         fetch_log_ids(cur, "service=? AND message=?", ("order-service", "Health check passed"), 5),
         fetch_logs(cur, "service=? AND message=?", ("order-service", "Health check passed"), 5),
         {"services": ["order-service"], "levels": ["INFO"], "keywords": ["Health check"]}
     ))

spec("qa_014", "service_health", "easy",
     "auth-service 的 Configuration loaded successfully 日志有哪些？",
     "auth-service 存在 Configuration loaded successfully 的 INFO 日志，说明配置加载成功，服务在对应时间点完成了配置初始化。",
     lambda cur: (
         fetch_log_ids(cur, "service=? AND message=?", ("auth-service", "Configuration loaded successfully"), 5),
         fetch_logs(cur, "service=? AND message=?", ("auth-service", "Configuration loaded successfully"), 5),
         {"services": ["auth-service"], "levels": ["INFO"], "keywords": ["Configuration loaded"]}
     ))

spec("qa_015", "service_health", "easy",
     "user-service 的 Cache refreshed 日志有哪些？",
     "user-service 存在 Cache refreshed 的 INFO 日志，说明缓存刷新成功，本地缓存与数据源已完成同步。",
     lambda cur: (
         fetch_log_ids(cur, "service=? AND message=?", ("user-service", "Cache refreshed"), 5),
         fetch_logs(cur, "service=? AND message=?", ("user-service", "Cache refreshed"), 5),
         {"services": ["user-service"], "levels": ["INFO"], "keywords": ["Cache refreshed"]}
     ))

spec("qa_016", "service_health", "easy",
     "notification-service 的 Scheduled job completed 日志有哪些？",
     "notification-service 存在 Scheduled job completed 的 INFO 日志，说明定时任务（如批量通知发送）执行完成。",
     lambda cur: (
         fetch_log_ids(cur, "service=? AND message=?", ("notification-service", "Scheduled job completed"), 5),
         fetch_logs(cur, "service=? AND message=?", ("notification-service", "Scheduled job completed"), 5),
         {"services": ["notification-service"], "levels": ["INFO"], "keywords": ["Scheduled job"]}
     ))

spec("qa_017", "service_health", "medium",
     "比较各服务的 Health check passed 日志数量。",
     "所有 5 个服务（order-service、payment-service、user-service、auth-service、notification-service）都有 Health check passed 的 INFO 日志，分布相对均匀，每个服务约 80-110 条。说明健康检查机制在各服务上运行正常。",
     lambda cur: (
         [],
         [f"{svc}: {cnt} 条" for svc, cnt in fetch_group_counts(cur, "service", "message='Health check passed'")],
         {"services": ["order-service", "payment-service", "user-service", "auth-service", "notification-service"],
          "levels": ["INFO"], "keywords": ["Health check", "aggregation"]}
     ))

spec("qa_018", "service_health", "medium",
     "payment-service 最近一次 Configuration loaded successfully 是什么时候？服务状态如何？",
     "payment-service 在数据库中存在多条 Configuration loaded successfully 的 INFO 日志。配合 Health check passed 日志可以确认服务处于正常运行状态。最新记录可通过按时间倒序查询获取。",
     lambda cur: (
         fetch_log_ids(cur, "service=? AND message=?", ("payment-service", "Configuration loaded successfully"), 3),
         fetch_logs(cur, "service=? AND message=?", ("payment-service", "Configuration loaded successfully"), 3),
         {"services": ["payment-service"], "levels": ["INFO"], "keywords": ["Configuration loaded"]}
     ))

spec("qa_019", "service_health", "medium",
     "哪些服务出现了 Cache refreshed 日志？",
     "Cache refreshed 的 INFO 日志覆盖所有 5 个服务：order-service、auth-service、user-service、notification-service、payment-service。说明各服务都启用了缓存刷新机制并定期同步。",
     lambda cur: (
         fetch_log_ids(cur, "message=?", ("Cache refreshed",), 5),
         fetch_logs(cur, "message=?", ("Cache refreshed",), 5),
         {"services": ["order-service", "auth-service", "user-service", "notification-service", "payment-service"],
          "levels": ["INFO"], "keywords": ["Cache refreshed"]}
     ))

spec("qa_020", "service_health", "hard",
     "分析系统在 2026-07-21 的整体健康状况，结合 INFO 与 ERROR 日志说明。",
     "2026-07-21 当日既有大量 INFO 级别的正常日志（Health check passed、User login successful、Order created successfully 等），也存在若干 ERROR 日志（OutOfMemoryError、SSL handshake failed、File not found 等）。总体看服务可用但存在零星异常，建议关注 notification-service 的内存问题和 payment-service 的 SSL 配置。",
     lambda cur: (
         fetch_log_ids(cur, "timestamp LIKE ?", ("2026-07-21%",), 8),
         fetch_logs(cur, "timestamp LIKE ?", ("2026-07-21%",), 8),
         {"services": ["all"], "levels": ["INFO", "ERROR"], "keywords": ["health", "2026-07-21"]}
     ))


# ------------------ 用户行为（8 条） ------------------

spec("qa_021", "user_activity", "easy",
     "哪些日志记录了 User login successful？",
     "存在多条 User login successful 的 INFO 日志，分布在所有 5 个服务中，说明用户登录功能正常工作。",
     lambda cur: (
         fetch_log_ids(cur, "message=?", ("User login successful",), 5),
         fetch_logs(cur, "message=?", ("User login successful",), 5),
         {"services": ["order-service", "auth-service", "payment-service", "notification-service", "user-service"],
          "levels": ["INFO", "DEBUG"], "keywords": ["User login"]}
     ))

spec("qa_022", "user_activity", "easy",
     "找出 User registered successfully 的日志。",
     "存在多条 User registered successfully 的 INFO 日志，说明用户注册流程正常运行。这些日志覆盖多个服务，因为注册事件会在多个服务间同步。",
     lambda cur: (
         fetch_log_ids(cur, "message=?", ("User registered successfully",), 5),
         fetch_logs(cur, "message=?", ("User registered successfully",), 5),
         {"services": ["order-service", "auth-service", "user-service", "payment-service", "notification-service"],
          "levels": ["INFO", "DEBUG"], "keywords": ["User registered"]}
     ))

spec("qa_023", "user_activity", "easy",
     "哪些日志记录了 Order created successfully？",
     "存在多条 Order created successfully 的 INFO 日志，覆盖所有 5 个服务，说明订单创建流程在各服务间正常流转。",
     lambda cur: (
         fetch_log_ids(cur, "message=?", ("Order created successfully",), 5),
         fetch_logs(cur, "message=?", ("Order created successfully",), 5),
         {"services": ["order-service", "auth-service", "user-service", "payment-service", "notification-service"],
          "levels": ["INFO"], "keywords": ["Order created"]}
     ))

spec("qa_024", "user_activity", "easy",
     "找出 Payment processed successfully 的日志。",
     "存在多条 Payment processed successfully 的 INFO 日志，覆盖多个服务，说明支付处理流程正常完成。",
     lambda cur: (
         fetch_log_ids(cur, "message=?", ("Payment processed successfully",), 5),
         fetch_logs(cur, "message=?", ("Payment processed successfully",), 5),
         {"services": ["auth-service", "user-service", "payment-service", "notification-service", "order-service"],
          "levels": ["INFO"], "keywords": ["Payment processed"]}
     ))

spec("qa_025", "user_activity", "medium",
     "DEBUG 级别的 User login successful 日志有哪些？和 INFO 级别有何区别？",
     "存在 DEBUG 级别的 User login successful 日志，主要出现在 auth-service。与 INFO 级别相比，DEBUG 级别通常包含更详细的诊断信息，用于开发调试，生产环境默认不输出。两类日志都表明登录成功。",
     lambda cur: (
         fetch_log_ids(cur, "level=? AND message=?", ("DEBUG", "User login successful"), 5),
         fetch_logs(cur, "level=? AND message=?", ("DEBUG", "User login successful"), 5),
         {"services": ["auth-service"], "levels": ["DEBUG"], "keywords": ["User login", "DEBUG"]}
     ))

spec("qa_026", "user_activity", "medium",
     "统计各服务 User registered successfully 的数量分布。",
     "User registered successfully 日志覆盖所有 5 个服务，分布相对均匀，每个服务约 80-100 条，说明注册事件在服务间正确同步。",
     lambda cur: (
         [],
         [f"{svc}: {cnt} 条" for svc, cnt in fetch_group_counts(cur, "service", "message='User registered successfully'")],
         {"services": ["all"], "levels": ["INFO"], "keywords": ["User registered", "aggregation"]}
     ))

spec("qa_027", "user_activity", "medium",
     "比较 User login successful 在 INFO 和 DEBUG 中的差异。",
     "User login successful 同时出现在 INFO 和 DEBUG 两种级别中。INFO 级别覆盖所有 5 个服务，用于生产环境记录登录事件；DEBUG 级别数量较少，主要用于开发期诊断，包含更细粒度的调用链信息。",
     lambda cur: (
         fetch_log_ids(cur, "message=?", ("User login successful",), 8),
         fetch_logs(cur, "message=?", ("User login successful",), 8),
         {"services": ["all"], "levels": ["INFO", "DEBUG"], "keywords": ["User login"]}
     ))

spec("qa_028", "user_activity", "hard",
     "分析订单与支付流程相关日志，说明业务链路状态。",
     "Order created successfully 和 Payment processed successfully 的 INFO 日志在所有 5 个服务中均有记录，分布均匀。说明订单创建与支付处理流程在服务间正常流转，业务链路整体健康。",
     lambda cur: (
         fetch_log_ids(cur, "message IN (?, ?)", ("Order created successfully", "Payment processed successfully"), 8),
         fetch_logs(cur, "message IN (?, ?)", ("Order created successfully", "Payment processed successfully"), 8),
         {"services": ["all"], "levels": ["INFO"], "keywords": ["Order created", "Payment processed"]}
     ))


# ------------------ 性能问题（10 条） ------------------

spec("qa_029", "performance", "easy",
     "找出 Connection timeout to database 的 WARNING 日志。",
     "存在多条 Connection timeout to database 的 WARNING 日志（带 retry in 5s 后缀），说明数据库连接超时但系统会自动重试。常见原因是数据库负载过高或网络延迟。",
     lambda cur: (
         fetch_log_ids(cur, "level=? AND message LIKE ?", ("WARNING", "%Connection timeout to database%"), 5),
         fetch_logs(cur, "level=? AND message LIKE ?", ("WARNING", "%Connection timeout to database%"), 5),
         {"services": ["all"], "levels": ["WARNING"], "keywords": ["Connection timeout"]}
     ))

spec("qa_030", "performance", "easy",
     "哪些日志记录了 Rate limit exceeded？",
     "Rate limit exceeded 日志同时出现在 WARNING（带 retry in 5s）和 ERROR 两种级别中。WARNING 表示系统触发限流但会自动重试，ERROR 表示限流导致请求失败。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ?", ("%Rate limit exceeded%",), 5),
         fetch_logs(cur, "message LIKE ?", ("%Rate limit exceeded%",), 5),
         {"services": ["all"], "levels": ["WARNING", "ERROR"], "keywords": ["Rate limit"]}
     ))

spec("qa_031", "performance", "easy",
     "找出 Payment gateway unavailable 的 WARNING 日志。",
     "存在多条 Payment gateway unavailable 的 WARNING 日志（带 retry in 5s），说明支付网关暂时不可用但系统会重试。可能原因是支付渠道维护或网络抖动。",
     lambda cur: (
         fetch_log_ids(cur, "level=? AND message LIKE ?", ("WARNING", "%Payment gateway unavailable%"), 5),
         fetch_logs(cur, "level=? AND message LIKE ?", ("WARNING", "%Payment gateway unavailable%"), 5),
         {"services": ["order-service", "notification-service", "payment-service", "auth-service"],
          "levels": ["WARNING"], "keywords": ["Payment gateway"]}
     ))

spec("qa_032", "performance", "easy",
     "找出 Connection timeout to database 的 ERROR 日志。",
     "存在 Connection timeout to database 的 ERROR 日志（不带 retry 后缀），说明数据库连接超时且未自动重试，可能导致请求失败。应重点排查数据库连接池配置与数据库负载。",
     lambda cur: (
         fetch_log_ids(cur, "level=? AND message=?", ("ERROR", "Connection timeout to database"), 5),
         fetch_logs(cur, "level=? AND message=?", ("ERROR", "Connection timeout to database"), 5),
         {"services": ["all"], "levels": ["ERROR"], "keywords": ["Connection timeout"]}
     ))

spec("qa_033", "performance", "medium",
     "Rate limit exceeded 在 ERROR 和 WARNING 中分别是什么含义？",
     "Rate limit exceeded 在 WARNING 级别带 'retry in 5s' 后缀，表示触发限流但系统会自动重试；在 ERROR 级别则不带重试后缀，表示限流导致请求最终失败。前者是可恢复的瞬时压力，后者是需要介入的持续过载。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ?", ("%Rate limit exceeded%",), 8),
         fetch_logs(cur, "message LIKE ?", ("%Rate limit exceeded%",), 8),
         {"services": ["all"], "levels": ["WARNING", "ERROR"], "keywords": ["Rate limit"]}
     ))

spec("qa_034", "performance", "medium",
     "找出 auth-service 在 2026-07-14 19:12:59 发生的 Rate limit 事件并说明。",
     "auth-service 在 2026-07-14 19:12:59 出现 Rate limit exceeded (retry in 5s) 的 WARNING 日志（trace_id=bc0c8ea5，IP=192.168.73.92）。说明该时刻 auth-service 触发了限流，系统将在 5 秒后重试。",
     lambda cur: (
         fetch_log_ids(cur, "service=? AND timestamp LIKE ? AND message LIKE ?",
                       ("auth-service", "2026-07-14 19:12:59%", "%Rate limit%"), 3),
         fetch_logs(cur, "service=? AND timestamp LIKE ? AND message LIKE ?",
                    ("auth-service", "2026-07-14 19:12:59%", "%Rate limit%"), 3),
         {"services": ["auth-service"], "levels": ["WARNING"], "keywords": ["Rate limit", "2026-07-14"]}
     ))

spec("qa_035", "performance", "medium",
     "order-service 出现 Payment gateway unavailable 的次数？涉及哪些服务？",
     "Payment gateway unavailable 的 WARNING 日志覆盖 order-service、notification-service、payment-service、auth-service 四个服务，其中 order-service 出现频次较高。说明支付网关问题影响了多个依赖支付的服务。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ?", ("%Payment gateway unavailable%",), 8),
         fetch_logs(cur, "message LIKE ?", ("%Payment gateway unavailable%",), 8),
         {"services": ["order-service", "notification-service", "payment-service", "auth-service"],
          "levels": ["WARNING"], "keywords": ["Payment gateway"]}
     ))

spec("qa_036", "performance", "medium",
     "找出所有数据库连接超时日志，分析涉及的服务和级别。",
     "Connection timeout to database 日志出现在 ERROR 和 WARNING 两种级别：WARNING 带 retry in 5s，覆盖所有 5 个服务；ERROR 不带重试，说明超时已达到失败阈值。所有服务都受影响，建议检查数据库整体负载。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ?", ("%Connection timeout to database%",), 8),
         fetch_logs(cur, "message LIKE ?", ("%Connection timeout to database%",), 8),
         {"services": ["all"], "levels": ["WARNING", "ERROR"], "keywords": ["Connection timeout"]}
     ))

spec("qa_037", "performance", "hard",
     "统计每个服务出现的 WARNING 日志数量并排序。",
     "按服务统计 WARNING 日志数量：order-service、notification-service、user-service、payment-service、auth-service 均有较多 WARNING 日志（约 460-530 条），其中 order-service 数量最多。建议关注 order-service 的限流与支付网关问题。",
     lambda cur: (
         [],
         [f"{svc}: {cnt} 条" for svc, cnt in fetch_group_counts(cur, "service", "level='WARNING'")],
         {"levels": ["WARNING"], "keywords": ["aggregation"]}
     ))

spec("qa_038", "performance", "hard",
     "找出所有 retry in 5s 相关的 WARNING 日志并按消息类型分类。",
     "带 'retry in 5s' 后缀的 WARNING 日志可分为 5 类：Rate limit exceeded、Invalid token provided、Connection timeout to database、Payment gateway unavailable、NullPointerException in UserService。其中 Rate limit exceeded 和 NullPointerException in UserService 出现频次最高。",
     lambda cur: (
         fetch_log_ids(cur, "level=? AND message LIKE ?", ("WARNING", "%retry in 5s%"), 10),
         fetch_logs(cur, "level=? AND message LIKE ?", ("WARNING", "%retry in 5s%"), 10),
         {"services": ["all"], "levels": ["WARNING"], "keywords": ["retry", "aggregation"]}
     ))


# ------------------ 安全问题（8 条） ------------------

spec("qa_039", "security", "easy",
     "找出所有 Invalid token provided 的 ERROR 日志。",
     "存在 Invalid token provided 的 ERROR 日志（不带 retry），说明客户端提供了无效的认证令牌，请求被拒绝。可能是令牌过期、伪造或格式错误。",
     lambda cur: (
         fetch_log_ids(cur, "level=? AND message=?", ("ERROR", "Invalid token provided"), 5),
         fetch_logs(cur, "level=? AND message=?", ("ERROR", "Invalid token provided"), 5),
         {"services": ["all"], "levels": ["ERROR"], "keywords": ["Invalid token"]}
     ))

spec("qa_040", "security", "easy",
     "找出 Invalid token provided 的 WARNING 日志（带 retry）。",
     "存在 Invalid token provided (retry in 5s) 的 WARNING 日志，说明系统检测到无效令牌但会自动重试。这可能是临时性的令牌刷新过程。",
     lambda cur: (
         fetch_log_ids(cur, "level=? AND message LIKE ?", ("WARNING", "%Invalid token provided%"), 5),
         fetch_logs(cur, "level=? AND message LIKE ?", ("WARNING", "%Invalid token provided%"), 5),
         {"services": ["all"], "levels": ["WARNING"], "keywords": ["Invalid token"]}
     ))

spec("qa_041", "security", "easy",
     "找出 SSL handshake failed 的 ERROR 日志。",
     "存在 SSL handshake failed 的 ERROR 日志，覆盖 user-service、payment-service、notification-service 等服务。说明 SSL/TLS 握手失败，常见原因是证书过期、不受信任或 TLS 版本不兼容。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ?", ("%SSL handshake failed%",), 5),
         fetch_logs(cur, "message LIKE ?", ("%SSL handshake failed%",), 5),
         {"services": ["user-service", "payment-service", "notification-service"],
          "levels": ["ERROR"], "keywords": ["SSL handshake"]}
     ))

spec("qa_042", "security", "medium",
     "Invalid token provided 日志分布在哪些服务和级别？",
     "Invalid token provided 同时出现在 WARNING（带 retry in 5s）和 ERROR 两种级别，覆盖所有 5 个服务。WARNING 表示可重试的瞬时问题，ERROR 表示请求被拒绝。多个服务同时出现说明可能是统一的鉴权服务存在问题。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ?", ("%Invalid token provided%",), 8),
         fetch_logs(cur, "message LIKE ?", ("%Invalid token provided%",), 8),
         {"services": ["all"], "levels": ["WARNING", "ERROR"], "keywords": ["Invalid token"]}
     ))

spec("qa_043", "security", "medium",
     "找出所有 SSL handshake failed 日志并分析涉及的服务。",
     "SSL handshake failed 的 ERROR 日志出现在 user-service、payment-service、notification-service 等多个服务，说明存在共性的 SSL 配置问题，可能是 CA 证书链更新或 TLS 版本策略变更。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ?", ("%SSL handshake failed%",), 8),
         fetch_logs(cur, "message LIKE ?", ("%SSL handshake failed%",), 8),
         {"services": ["user-service", "payment-service", "notification-service"],
          "levels": ["ERROR"], "keywords": ["SSL handshake"]}
     ))

spec("qa_044", "security", "medium",
     "auth-service 在 2026-07-14 19:12:59 发生了什么安全问题？",
     "auth-service 在 2026-07-14 19:12:59 出现 Rate limit exceeded (retry in 5s) 的 WARNING 日志（trace_id=bc0c8ea5，IP=192.168.73.92）。虽然属于性能问题，但限流通常与安全防护相关——可能是异常高频请求触发了限流策略，需要排查是否存在恶意刷接口行为。",
     lambda cur: (
         fetch_log_ids(cur, "service=? AND timestamp LIKE ?", ("auth-service", "2026-07-14 19:12:59%"), 3),
         fetch_logs(cur, "service=? AND timestamp LIKE ?", ("auth-service", "2026-07-14 19:12:59%"), 3),
         {"services": ["auth-service"], "levels": ["WARNING"], "keywords": ["Rate limit", "2026-07-14"]}
     ))

spec("qa_045", "security", "hard",
     "分析系统中的认证失败模式，结合 Invalid token 和 Rate limit 日志说明。",
     "系统中认证失败主要表现为两类：1) Invalid token provided（ERROR 与 WARNING），表示令牌无效或过期；2) Rate limit exceeded（WARNING），表示请求频率超限，可能存在暴力破解或异常刷接口。建议结合 IP 维度做进一步分析，识别可疑来源。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ? OR message LIKE ?",
                       ("%Invalid token%", "%Rate limit%"), 10),
         fetch_logs(cur, "message LIKE ? OR message LIKE ?",
                    ("%Invalid token%", "%Rate limit%"), 10),
         {"services": ["all"], "levels": ["WARNING", "ERROR"], "keywords": ["Invalid token", "Rate limit"]}
     ))

spec("qa_046", "security", "hard",
     "统计每个服务 SSL handshake failed 出现的次数，分析证书问题的影响范围。",
     "SSL handshake failed 主要影响 user-service、payment-service、notification-service 等需要对外建立 HTTPS 连接的服务，order-service 与 auth-service 也可能出现。建议统一检查证书链与 TLS 配置。",
     lambda cur: (
         [],
         [f"{svc}: {cnt} 条" for svc, cnt in fetch_group_counts(cur, "service", "message='SSL handshake failed'")],
         {"services": ["all"], "levels": ["ERROR"], "keywords": ["SSL handshake", "aggregation"]}
     ))


# ------------------ 资源问题（6 条） ------------------

spec("qa_047", "resource", "easy",
     "找出所有 OutOfMemoryError: Java heap space 日志。",
     "存在 OutOfMemoryError: Java heap space 的 ERROR 日志，主要出现在 notification-service。说明 JVM 堆内存耗尽，需要增大 -Xmx 或排查内存泄漏。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ?", ("%OutOfMemoryError: Java heap space%",), 5),
         fetch_logs(cur, "message LIKE ?", ("%OutOfMemoryError: Java heap space%",), 5),
         {"services": ["notification-service"], "levels": ["ERROR"], "keywords": ["OutOfMemoryError"]}
     ))

spec("qa_048", "resource", "easy",
     "找出所有 Transaction rollback due to deadlock 日志。",
     "存在 Transaction rollback due to deadlock 的 ERROR 日志，覆盖 auth-service、notification-service、order-service。说明数据库存在死锁，多个事务以不一致的顺序获取锁。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ?", ("%Transaction rollback due to deadlock%",), 5),
         fetch_logs(cur, "message LIKE ?", ("%Transaction rollback due to deadlock%",), 5),
         {"services": ["auth-service", "notification-service", "order-service"],
          "levels": ["ERROR"], "keywords": ["deadlock"]}
     ))

spec("qa_049", "resource", "medium",
     "OutOfMemoryError 出现在哪些服务？分析内存问题的影响范围。",
     "OutOfMemoryError: Java heap space 的 ERROR 日志集中在 notification-service，说明该服务的 JVM 堆内存不足。由于通知服务通常需要批量处理消息，可能存在大对象未及时释放或批量大小过大。其他服务暂未出现 OOM。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ?", ("%OutOfMemoryError%",), 5),
         fetch_logs(cur, "message LIKE ?", ("%OutOfMemoryError%",), 5),
         {"services": ["notification-service"], "levels": ["ERROR"], "keywords": ["OutOfMemoryError"]}
     ))

spec("qa_050", "resource", "medium",
     "File not found: /var/log/app.log 出现在哪些服务？",
     "File not found: /var/log/app.log 的 ERROR 日志出现在 user-service、notification-service 等服务，说明这些服务尝试写入或读取日志文件时文件不存在，可能是日志目录未创建或文件被误删。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ?", ("%File not found: /var/log/app.log%",), 5),
         fetch_logs(cur, "message LIKE ?", ("%File not found: /var/log/app.log%",), 5),
         {"services": ["user-service", "notification-service"], "levels": ["ERROR"], "keywords": ["File not found"]}
     ))

spec("qa_051", "resource", "medium",
     "Transaction rollback due to deadlock 涉及哪些服务？",
     "Transaction rollback due to deadlock 的 ERROR 日志覆盖 auth-service、notification-service、order-service，说明这些服务在并发事务中出现了死锁。建议统一规范事务内资源获取顺序，并在数据库层开启死锁检测。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ?", ("%Transaction rollback due to deadlock%",), 5),
         fetch_logs(cur, "message LIKE ?", ("%Transaction rollback due to deadlock%",), 5),
         {"services": ["auth-service", "notification-service", "order-service"],
          "levels": ["ERROR"], "keywords": ["deadlock"]}
     ))

spec("qa_052", "resource", "hard",
     "分析系统资源类问题（内存/磁盘/死锁）的整体分布。",
     "系统资源类问题主要有三类：1) OutOfMemoryError: Java heap space（集中在 notification-service，JVM 堆内存不足）；2) File not found: /var/log/app.log（user-service、notification-service，日志文件缺失）；3) Transaction rollback due to deadlock（auth-service、notification-service、order-service，数据库死锁）。建议分别从 JVM 配置、日志目录管理、事务设计三个维度优化。",
     lambda cur: (
         fetch_log_ids(cur, "message LIKE ? OR message LIKE ? OR message LIKE ?",
                       ("%OutOfMemoryError%", "%File not found%", "%deadlock%"), 10),
         fetch_logs(cur, "message LIKE ? OR message LIKE ? OR message LIKE ?",
                    ("%OutOfMemoryError%", "%File not found%", "%deadlock%"), 10),
         {"services": ["notification-service", "user-service", "auth-service", "order-service"],
          "levels": ["ERROR"], "keywords": ["OutOfMemoryError", "File not found", "deadlock"]}
     ))


# ------------------ 统计聚合（5 条） ------------------

spec("qa_053", "aggregation", "medium",
     "统计系统中 INFO、WARNING、ERROR、DEBUG 日志各有多少条？",
     "按级别统计：INFO 约 3800 条（最多），ERROR 约 2480 条，WARNING 约 2470 条，DEBUG 约 1250 条（最少）。INFO 占比约 38%，ERROR 与 WARNING 数量接近，DEBUG 仅在调试场景输出。",
     lambda cur: (
         [],
         [f"{lvl}: {cnt} 条" for lvl, cnt in fetch_group_counts(cur, "level")],
         {"levels": ["INFO", "WARNING", "ERROR", "DEBUG"], "keywords": ["aggregation"]}
     ))

spec("qa_054", "aggregation", "medium",
     "每个服务各有多少条日志？",
     "按服务统计：order-service、notification-service、auth-service、user-service、payment-service 各约 1970-2030 条日志，分布相对均匀。order-service 数量最多，符合其作为核心业务服务的定位。",
     lambda cur: (
         [],
         [f"{svc}: {cnt} 条" for svc, cnt in fetch_group_counts(cur, "service")],
         {"services": ["all"], "keywords": ["aggregation"]}
     ))

spec("qa_055", "aggregation", "hard",
     "按服务×级别交叉统计日志数量，找出分布特征。",
     "5 个服务的日志级别分布非常均匀：每个服务 INFO 约 750-780 条，WARNING 约 460-530 条，ERROR 约 470-520 条，DEBUG 约 240-250 条。说明日志是按模板生成的测试数据，业务上反映出各服务的运行特征相近。",
     lambda cur: (
         [],
         [f"{svc}/{lvl}: {cnt}" for svc, lvl, cnt in fetch_group_counts(cur, "service, level")[:20]],
         {"services": ["all"], "levels": ["all"], "keywords": ["aggregation"]}
     ))

spec("qa_056", "aggregation", "hard",
     "统计最常见的 5 类日志消息及其数量。",
     "Top 5 消息模板：1) NullPointerException in UserService (retry in 5s) - 约 420 条；2) Rate limit exceeded (retry in 5s) - 约 440 条；3) Scheduled job completed - 约 480 条；4) Configuration loaded successfully - 约 510 条；5) Health check passed - 约 460 条。NULL 指针异常和限流是出现频次最高的异常模板。",
     lambda cur: (
         [],
         [f"{msg[:80]}: {cnt} 条" for msg, cnt in fetch_group_counts(cur, "message")[:10]],
         {"services": ["all"], "levels": ["all"], "keywords": ["aggregation"]}
     ))

spec("qa_057", "aggregation", "hard",
     "统计 ERROR 级别中各消息类型的数量，找出 Top 3 错误。",
     "ERROR 级别 Top 3 消息：1) NullPointerException in UserService - 约 220 条；2) File not found: /var/log/app.log - 约 240 条；3) Network unreachable / OutOfMemoryError / SSL handshake failed 等紧随其后。建议优先修复 NullPointerException 和文件缺失问题。",
     lambda cur: (
         [],
         [f"{msg[:80]}: {cnt} 条" for msg, cnt in fetch_group_counts(cur, "message", "level='ERROR'")[:10]],
         {"levels": ["ERROR"], "keywords": ["aggregation"]}
     ))


# ------------------ 时间分析（3 条） ------------------

spec("qa_058", "time_analysis", "easy",
     "找出 2026-07-17 04:03:13 发生的 auth-service 错误日志。",
     "2026-07-17 04:03:13 auth-service 出现一条 Transaction rollback due to deadlock 的 ERROR 日志（ID:3，IP=192.168.8.254，trace_id=d3a910c4）。说明该时刻数据库发生死锁，事务被回滚。",
     lambda cur: (
         fetch_log_ids(cur, "service=? AND timestamp LIKE ? AND level=?",
                       ("auth-service", "2026-07-17 04:03:13%", "ERROR"), 3),
         fetch_logs(cur, "service=? AND timestamp LIKE ? AND level=?",
                    ("auth-service", "2026-07-17 04:03:13%", "ERROR"), 3),
         {"services": ["auth-service"], "levels": ["ERROR"], "keywords": ["deadlock", "2026-07-17"]}
     ))

spec("qa_059", "time_analysis", "medium",
     "找出 2026-07-21 02:16:19 前后 user-service 的错误并分析。",
     "2026-07-21 02:16:19 user-service 出现 SSL handshake failed 的 ERROR 日志（trace_id=ba5f5e63，IP=192.168.211.133）。说明该时刻 user-service 在与外部 HTTPS 端点建立连接时 SSL 握手失败，建议检查证书配置。",
     lambda cur: (
         fetch_log_ids(cur, "service=? AND timestamp LIKE ? AND level=?",
                       ("user-service", "2026-07-21 02:16%", "ERROR"), 3),
         fetch_logs(cur, "service=? AND timestamp LIKE ? AND level=?",
                    ("user-service", "2026-07-21 02:16%", "ERROR"), 3),
         {"services": ["user-service"], "levels": ["ERROR"], "keywords": ["SSL handshake", "2026-07-21"]}
     ))

spec("qa_060", "time_analysis", "hard",
     "分析日志的时间范围和整体时间分布特征。",
     "日志时间范围从 2026-07-14 17:13:07 到 2026-07-21 17:12:36，跨度约 7 天。各天日志分布相对均匀，覆盖 INFO/WARNING/ERROR/DEBUG 四个级别和 5 个服务。结合按天聚合可以识别出异常高峰时段。",
     lambda cur: (
         [],
         [
             f"起始时间: {fetch_min_ts(cur)}",
             f"结束时间: {fetch_max_ts(cur)}",
             f"总跨度: 7 天",
             f"按天分布: {fetch_by_day(cur)}",
         ],
         {"services": ["all"], "levels": ["all"], "keywords": ["time", "aggregation"]}
     ))


# 辅助：min/max timestamp / 按天聚合
def fetch_min_ts(cur):
    cur.execute("SELECT MIN(timestamp) FROM logs")
    return cur.fetchone()[0]

def fetch_max_ts(cur):
    cur.execute("SELECT MAX(timestamp) FROM logs")
    return cur.fetchone()[0]

def fetch_by_day(cur):
    cur.execute("SELECT substr(timestamp,1,10) d, COUNT(*) FROM logs GROUP BY d ORDER BY d")
    return ", ".join(f"{d}={c}" for d, c in cur.fetchall())


# ============================================================
# 构建测试集
# ============================================================

def build():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    items = []
    by_scenario = defaultdict(int)
    by_difficulty = defaultdict(int)
    for s in QA_SPECS:
        log_ids, contexts, tags = s["find"](cur)
        # 防御：如果 contexts 为空，至少给一个占位提示（不应发生）
        if not contexts:
            contexts = ["[未检索到匹配日志]"]
        item = {
            "id": s["id"],
            "scenario": s["scenario"],
            "difficulty": s["difficulty"],
            "user_input": s["user_input"],
            "reference": s["reference"],
            "reference_contexts": contexts,
            "reference_log_ids": log_ids,
            "tags": tags,
            "context_count": len(contexts),
        }
        items.append(item)
        by_scenario[s["scenario"]] += 1
        by_difficulty[s["difficulty"]] += 1

    conn.close()

    out = {
        "version": "1.0",
        "created_at": datetime.now().strftime("%Y-%m-%d"),
        "source_db": "backend/app.db",
        "source_table": "logs",
        "total": len(items),
        "stats": {
            "by_scenario": dict(by_scenario),
            "by_difficulty": dict(by_difficulty),
        },
        "schema": {
            "id": "问答对唯一 ID",
            "scenario": "场景分类: error_diagnosis|service_health|user_activity|performance|security|resource|aggregation|time_analysis",
            "difficulty": "难度: easy|medium|hard",
            "user_input": "用户问题",
            "reference": "标准答案（用于 context_recall / context_precision）",
            "reference_contexts": "应引用的日志列表（系统应在检索阶段返回这些日志）",
            "reference_log_ids": "应引用日志的数据库 ID（用于检索召回率评估）",
            "tags": "辅助标签（services/levels/keywords）",
            "context_count": "应引用日志条数",
        },
        "items": items,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # 打印构建结果
    print(f"✅ 测试集已生成: {OUT_PATH}")
    print(f"   总问答对: {out['total']}")
    print(f"   按场景: {out['stats']['by_scenario']}")
    print(f"   按难度: {out['stats']['by_difficulty']}")
    # 检查空 contexts
    empty = [i["id"] for i in items if i["context_count"] == 1 and "[未检索到" in i["reference_contexts"][0]]
    if empty:
        print(f"   ⚠️ 以下问答对的参考上下文为空: {empty}")
    else:
        print(f"   ✓ 所有问答对都有真实参考日志")


if __name__ == "__main__":
    build()
