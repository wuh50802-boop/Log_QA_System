import sqlite3

conn = sqlite3.connect('logs.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()

print("数据库中的表:")
for t in tables:
    print(f"  - {t[0]}")

conn.close()

"""
区别对比
维度	backend/scripts/test_retrieval.py	backend/tests/test_retriever.py
用途	手动功能验证/演示	                    自动化单元测试
运行方式	手动执行 python test_retrieval.py	pytest 框架自动运行
断言	无断言，只打印输出	                    有 assert 断言验证
输出	详细的格式化输出，供人阅读	                简洁的测试报告
环境	开发/演示环境	                        CI/CD 测试环境
数据依赖	依赖真实数据	                    可用测试数据/Mock
是否阻塞	非阻塞，只是展示	                失败会阻塞部署
"""