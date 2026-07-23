#!/usr/bin/env python
"""
快速检索测试脚本 - 用于验证检索功能
适配 payload 结构: log_id, chunk_text, level, service, timestamp, source
"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.retriever import search_logs, get_retriever
from services.qdrant_client import get_qdrant_client
import time


def test_basic_retrieval():
    """测试基础检索"""
    print("=" * 70)
    print("📊 日志向量检索测试")
    print("=" * 70)
    
    # 先查看向量数量
    client = get_qdrant_client()
    try:
        count = client.count()
        print(f"📦 向量总数: {count}")
    except Exception as e:
        print(f"⚠️ 无法获取向量数量: {e}")
    
    print("\n" + "-" * 70)
    
    # 测试查询
    test_cases = [
        ("数据库连接失败", None, None, "全部日志"),
        ("用户登录异常", "ERROR", None, "ERROR级别"),
        ("服务超时", "WARNING", "api-gateway", "WARNING + api-gateway"),
        ("认证失败", "ERROR", "auth-service", "ERROR + auth-service"),
        ("内存溢出", "ERROR", None, "ERROR级别"),
    ]
    
    for query, level, service, desc in test_cases:
        print(f"\n🔍 查询: {query}")
        if desc:
            print(f"   📌 过滤: {desc}")
        
        start_time = time.time()
        results = search_logs(
            query=query,
            top_k=3,
            level=level,
            service=service,
            score_threshold=0.3
        )
        elapsed = (time.time() - start_time) * 1000
        
        print(f"   ⏱️  耗时: {elapsed:.2f}ms")
        print(f"   📊 结果数: {len(results)}")
        
        if results:
            print("   📋 结果:")
            for i, result in enumerate(results, 1):
                print(f"      {i}. [score={result['score']:.4f}]")
                print(f"         log_id: {result['log_id']}")
                print(f"         level: {result['level']} | service: {result['service']}")
                print(f"         time: {result['timestamp']}")
                print(f"         message: {result['message'][:80]}...")
                if result.get('source'):
                    print(f"         source: {result['source']}")
        else:
            print("   ⚠️  无结果（可能阈值过高或无匹配数据）")


def test_filter_combinations():
    """测试过滤条件组合"""
    print("\n" + "=" * 70)
    print("🔍 过滤条件组合测试")
    print("=" * 70)
    
    query = "服务异常"
    
    # 不同过滤组合
    filters = [
        ("仅ERROR", {"level": "ERROR"}),
        ("仅auth-service", {"service": "auth-service"}),
        ("ERROR + auth-service", {"level": "ERROR", "service": "auth-service"}),
        ("ERROR + api-gateway", {"level": "ERROR", "service": "api-gateway"}),
    ]
    
    retriever = get_retriever()
    
    for desc, filter_params in filters:
        print(f"\n📌 {desc}")
        results = retriever.search(
            query=query,
            top_k=3,
            filter_params=filter_params,
            score_threshold=0.3
        )
        print(f"   结果数: {len(results)}")
        for r in results[:2]:
            print(f"   - {r.payload.get('level')} | {r.payload.get('service')} | {r.payload.get('chunk_text', '')[:50]}...")


def test_time_filter():
    """测试时间过滤"""
    print("\n" + "=" * 70)
    print("⏰ 时间过滤测试")
    print("=" * 70)

    # 获取当前时间附近的时间
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    query = "服务异常"

    # 1. 查询今天之前的日志
    print(f"\n📌 今天之前的日志:")
    results = search_logs(
        query=query,
        top_k=3,
        timestamp_before=today_start.strftime("%Y-%m-%d %H:%M:%S")
    )
    print(f"   结果数: {len(results)}")
    for r in results[:2]:
        print(f"   - {r['timestamp']} | {r['level']} | {r['message'][:40]}...")

    # 2. 查询今天之后的日志
    print(f"\n📌 今天之后的日志:")
    results = search_logs(
        query=query,
        top_k=3,
        timestamp_after=today_end.strftime("%Y-%m-%d %H:%M:%S")
    )
    print(f"   结果数: {len(results)}")

    # 3. 查询今天一整天的日志
    print(f"\n📌 今天整天的日志:")
    results = search_logs(
        query=query,
        top_k=3,
        timestamp_between=(
            today_start.strftime("%Y-%m-%d %H:%M:%S"),
            today_end.strftime("%Y-%m-%d %H:%M:%S")
        )
    )
    print(f"   结果数: {len(results)}")
    for r in results[:2]:
        print(f"   - {r['timestamp']} | {r['level']} | {r['message'][:40]}...")


def test_performance():
    """测试性能"""
    print("\n" + "=" * 70)
    print("⚡ 性能测试")
    print("=" * 70)
    
    query = "数据库连接失败"
    retriever = get_retriever()
    
    times = []
    for i in range(10):
        start = time.time()
        retriever.search(query, top_k=5)
        elapsed = (time.time() - start) * 1000
        times.append(elapsed)
    
    avg_time = sum(times) / len(times)
    max_time = max(times)
    min_time = min(times)
    
    print(f"📊 10次检索统计:")
    print(f"   平均耗时: {avg_time:.2f}ms")
    print(f"   最快: {min_time:.2f}ms")
    print(f"   最慢: {max_time:.2f}ms")
    print(f"   ✅ 目标: < 300ms")
    
    if avg_time < 300:
        print("   ✅ 性能达标!")
    else:
        print(f"   ⚠️ 性能超目标 {(avg_time-300):.2f}ms")


if __name__ == "__main__":
    test_basic_retrieval()
    test_filter_combinations()
    test_time_filter()
    test_performance()  