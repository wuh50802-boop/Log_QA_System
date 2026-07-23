#!/usr/bin/env python
"""
测试检索结果格式化
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.retriever import search_logs
from services.formatter import ResultFormatter, format_retrieval_results, format_for_llm
import json


def test_formatter():
    """测试格式化功能"""
    print("=" * 70)
    print("📊 测试检索结果格式化")
    print("=" * 70)
    
    # 1. 执行检索
    print("\n1. 执行检索...")
    query = "数据库连接失败"
    raw_results = search_logs(query, top_k=3, score_threshold=0.0)
    
    print(f"   原始结果数: {len(raw_results)}")
    
    # 2. 转换为格式化结果
    print("\n2. 格式化结果:")
    for i, r in enumerate(raw_results, 1):
        print(f"   {i}. log_id={r['log_id']}, score={r['score']:.4f}")
        print(f"      level={r['level']}, service={r['service']}")
        print(f"      message={r['message'][:60]}...")
    
    # 3. 测试批量格式化
    print("\n3. 测试批量格式化 (format_retrieval_results):")
    
    # 需要获取原始搜索结果
    from services.retriever import get_retriever
    retriever = get_retriever()
    # 用 retriever.search 获取原始结果
    # 注意：这里需要获取原始 (score, payload) 格式
    # 为了演示，我们使用 mock 数据
    mock_results = [
        (0.85, {
            "log_id": 123,
            "level": "ERROR",
            "service": "auth-service",
            "timestamp": "2026-07-23 10:00:00",
            "chunk_text": "Database connection timeout",
            "source": "auth-service"
        }),
        (0.72, {
            "log_id": 456,
            "level": "WARNING",
            "service": "api-gateway",
            "timestamp": "2026-07-23 10:05:00",
            "chunk_text": "Connection pool exhausted",
            "source": "api-gateway"
        }),
    ]
    
    formatted = format_retrieval_results(
        mock_results,
        include_summary=True,
        include_evidence=True,
        include_markdown=True
    )
    
    print(f"   日志数: {formatted['count']}")
    print(f"   摘要: {json.dumps(formatted['summary'], indent=2, ensure_ascii=False)}")
    print(f"\n   证据文本:\n{formatted['evidence']}")
    print(f"\n   Markdown:\n{formatted['markdown']}")
    
    # 4. 测试 LLM 格式化
    print("\n4. 测试 LLM 格式化 (format_for_llm):")
    llm_format = format_for_llm(mock_results)
    print(f"   证据文本:\n{llm_format['evidence']}")
    print(f"   摘要: {llm_format['summary']}")


if __name__ == "__main__":
    test_formatter()