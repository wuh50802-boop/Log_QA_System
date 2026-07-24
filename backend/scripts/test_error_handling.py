"""测试异常处理功能"""

import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.error_handler import (
    ErrorHandler,
    RobustQAPipeline,
    create_robust_pipeline,
    handle_errors
)
from services.exceptions import (
    NoSearchResultsError,
    LLMTimeoutError,
    InvalidQueryError,
    RateLimitError
)


def test_error_handler():
    """测试错误处理器"""
    print("=" * 70)
    print("错误处理器测试")
    print("=" * 70)
    
    handler = ErrorHandler()
    
    # 测试各种错误
    test_errors = [
        NoSearchResultsError("数据库连接超时", filters={"level": "ERROR"}),
        LLMTimeoutError(30),
        InvalidQueryError(""),
        RateLimitError(60),
        Exception("未知错误")
    ]
    
    for error in test_errors:
        print(f"\n📌 错误类型: {type(error).__name__}")
        print("-" * 40)
        response = handler.handle(error)
        print(f"错误码: {response.error_code}")
        print(f"消息: {response.message}")
        print(f"建议: {response.suggestions}")
    
    print("\n" + "=" * 70)
    stats = handler.get_stats()
    print(f"错误统计: {stats['total_errors']} 个")


def test_robust_pipeline():
    """测试健壮的 Pipeline"""
    print("\n" + "=" * 70)
    print("健壮 Pipeline 测试")
    print("=" * 70)
    
    # 创建健壮的 pipeline
    pipeline = create_robust_pipeline(
        top_k=5,
        retriever_type="hybrid"
    )
    
    test_cases = [
        ("正常查询", "auth-service 有什么异常？"),
        ("空查询", ""),
        ("无结果查询", "xyzabc123 不存在"),
        ("超长查询", "a" * 2000),  # 测试超长查询的处理
    ]
    
    for name, query in test_cases:
        print(f"\n📌 {name}: '{query[:50]}...'")
        print("-" * 40)
        
        result = pipeline.ask(query)
        
        print(f"回答预览: {result.answer[:200]}...")
        print(f"来源数: {len(result.sources)}")
        print(f"置信度: {result.confidence}")
        
        # 检查是否包含友好提示
        if result.confidence == "低" and not result.sources:
            print("✅ 返回了友好提示")


def test_error_decorator():
    """测试错误处理装饰器"""
    print("\n" + "=" * 70)
    print("错误处理装饰器测试")
    print("=" * 70)
    
    @handle_errors(fallback_message="测试函数失败")
    def risky_function(success: bool = True):
        if not success:
            raise ValueError("测试异常")
        return "成功返回"
    
    # 正常调用
    result = risky_function(success=True)
    print(f"正常调用: {result}")
    
    # 异常调用
    result = risky_function(success=False)
    print(f"异常调用: {result}")
    
    # 检查结果类型
    from services.error_handler import ErrorResponse
    print(f"返回类型: {type(result)}")
    print(f"是 ErrorResponse: {isinstance(result, ErrorResponse)}")


def test_timeout_simulation():
    """测试超时处理"""
    print("\n" + "=" * 70)
    print("超时处理测试")
    print("=" * 70)
    
    from services.qa_pipeline import create_pipeline
    
    # 创建普通 pipeline
    base_pipeline = create_pipeline(top_k=5, retriever_type="hybrid")
    robust_pipeline = RobustQAPipeline(base_pipeline)
    
    # 模拟超时（通过设置极短超时时间）
    print("模拟超时查询...")
    start_time = time.time()
    result = robust_pipeline.ask("test query", timeout=0.001)  # 1ms超时
    elapsed = time.time() - start_time
    
    print(f"实际耗时: {elapsed:.3f}s")
    print(f"回答预览: {result.answer[:200]}...")
    
    # 检查是否包含超时提示
    if "超时" in result.answer:
        print("✅ 正确返回了超时提示")


if __name__ == "__main__":
    test_error_handler()
    test_robust_pipeline()
    test_error_decorator()
    test_timeout_simulation()