"""
pytest 配置文件
自动添加项目根目录到 Python 路径，并提供测试 fixtures
"""
import sys
import os
import pytest

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 设置测试环境变量
os.environ.setdefault("TESTING", "true")


# ============ Pytest Fixtures ============

@pytest.fixture(scope="session")
def embedder():
    """提供嵌入模型实例（会话级别，复用）"""
    from services.embedder import BGEEmbedder
    return BGEEmbedder()


@pytest.fixture(scope="session")
def qdrant_client():
    """提供 Qdrant 客户端实例（会话级别，复用）"""
    from services.qdrant_client import get_qdrant_client
    return get_qdrant_client()


@pytest.fixture(scope="function")
def retriever():
    """提供检索器实例（函数级别，每次新建）"""
    from services.retriever import LogRetriever
    return LogRetriever(top_k=5, score_threshold=0.3)


@pytest.fixture(scope="session")
def sample_logs():
    """提供示例日志数据"""
    return [
        {
            "log_id": 1,
            "level": "ERROR",
            "service": "auth-service",
            "timestamp": "2026-07-23 10:00:00",
            "chunk_text": "Database connection timeout",
            "source": "auth-service"
        },
        {
            "log_id": 2,
            "level": "WARNING",
            "service": "api-gateway",
            "timestamp": "2026-07-23 10:05:00",
            "chunk_text": "Connection pool exhausted",
            "source": "api-gateway"
        },
        {
            "log_id": 3,
            "level": "ERROR",
            "service": "user-service",
            "timestamp": "2026-07-23 10:10:00",
            "chunk_text": "User authentication failed",
            "source": "user-service"
        },
    ]


@pytest.fixture(scope="session")
def test_queries():
    """提供测试查询列表"""
    return [
        "数据库连接失败",
        "API请求超时",
        "内存使用率过高",
        "用户登录异常",
        "服务不可用",
    ]


# ============ Pytest 钩子（保留） ============

# 移除 pytest_configure，因为标记已在 pytest.ini 中定义
# 但保留其他钩子

def pytest_collection_modifyitems(config, items):
    """修改测试收集时的行为"""
    for item in items:
        # 如果标记了 integration 且没有设置 INTEGRATION_TEST 环境变量，则跳过
        if "integration" in item.keywords:
            if not os.environ.get("INTEGRATION_TEST", "").lower() == "true":
                item.add_marker(
                    pytest.mark.skip(
                        reason="需要设置环境变量 INTEGRATION_TEST=true 来运行集成测试"
                    )
                )
        
        # 如果标记了 slow 且没有设置 RUN_SLOW_TESTS 环境变量，则跳过
        if "slow" in item.keywords:
            if not os.environ.get("RUN_SLOW_TESTS", "").lower() == "true":
                item.add_marker(
                    pytest.mark.skip(
                        reason="需要设置环境变量 RUN_SLOW_TESTS=true 来运行慢速测试"
                    )
                )


def pytest_sessionstart(session):
    """测试会话开始时的打印信息"""
    print("\n" + "=" * 70)
    print("🧪 开始运行检索模块测试")
    print("=" * 70)
    print(f"📁 项目根目录: {project_root}")
    print(f"🐍 Python 路径: {sys.path[0]}")
    print("=" * 70 + "\n")


def pytest_sessionfinish(session, exitstatus):
    """测试会话结束时的打印信息"""
    print("\n" + "=" * 70)
    if exitstatus == 0:
        print("✅ 所有测试通过！")
    else:
        print(f"❌ 测试失败，退出码: {exitstatus}")
    print("=" * 70 + "\n")