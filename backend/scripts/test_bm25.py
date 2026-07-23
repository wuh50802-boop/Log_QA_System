#!/usr/bin/env python
"""
测试 BM25 关键词检索功能
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.bm25_retriever import bm25_search, get_bm25_retriever
from services.qdrant_client import get_qdrant_client
import time
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


def build_index_from_qdrant():
    """从 Qdrant 构建 BM25 索引"""
    try:
        client = get_qdrant_client()
        
        # 获取所有数据
        scroll_result = client.client.scroll(
            collection_name="log_vectors",
            limit=10000,
            with_payload=True,
            with_vectors=False,
        )
        
        points = scroll_result[0]
        corpus = []
        for point in points:
            payload = point.payload
            if payload:
                corpus.append({
                    'log_id': payload.get('log_id'),
                    'chunk_text': payload.get('chunk_text', ''),
                    'level': payload.get('level', ''),
                    'service': payload.get('service', ''),
                    'timestamp': payload.get('timestamp', ''),
                    'source': payload.get('source', ''),
                })
        
        if not corpus:
            print("   ⚠️ 没有数据")
            return False
        
        # 构建索引
        retriever = get_bm25_retriever(corpus=corpus)
        print(f"   ✅ BM25 索引构建完成，文档数: {retriever.get_document_count()}")
        return True
        
    except Exception as e:
        print(f"   ❌ 构建索引失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_bm25_basic():
    """测试基础 BM25 检索"""
    print("=" * 70)
    print("🔍 BM25 关键词检索测试")
    print("=" * 70)
    
    # 1. 从 Qdrant 获取数据构建索引
    print("\n1. 加载数据并构建 BM25 索引...")
    
    success = build_index_from_qdrant()
    if not success:
        print("   ❌ 构建索引失败，退出测试")
        return
    
    # 2. 测试检索
    print("\n2. 测试 BM25 检索:")
    
    test_queries = [
        ("timeout", "英文关键词"),
        ("database", "英文关键词"),
        ("error", "英文关键词"),
        ("nullpointer", "英文关键词"),
        ("connection", "英文关键词"),
    ]
    
    for query, desc in test_queries:
        print(f"\n   🔍 查询: '{query}' ({desc})")
        
        start_time = time.time()
        results = bm25_search(query, top_k=3)
        elapsed = (time.time() - start_time) * 1000
        
        print(f"      ⏱️  耗时: {elapsed:.2f}ms")
        print(f"      📊 结果数: {len(results)}")
        
        if results:
            print("      📋 结果:")
            for i, r in enumerate(results[:3], 1):
                print(f"         {i}. [score={r['score']:.2f}]")
                print(f"            log_id: {r['log_id']}")
                print(f"            level: {r['payload'].get('level')}")
                print(f"            service: {r['payload'].get('service')}")
                print(f"            message: {r['payload'].get('chunk_text', '')[:60]}...")
        else:
            print("      ⚠️  无结果")


def test_bm25_with_filters():
    """测试带过滤条件的 BM25 检索"""
    print("\n" + "=" * 70)
    print("🔍 BM25 带过滤条件测试")
    print("=" * 70)
    
    query = "error"
    
    print(f"\n📌 查询: {query}")
    
    # 测试不同过滤条件
    filters = [
        ("全部", {}),
        ("仅 ERROR", {"level": "ERROR"}),
        ("仅 WARNING", {"level": "WARNING"}),
        ("仅 auth-service", {"service": "auth-service"}),
        ("ERROR + auth-service", {"level": "ERROR", "service": "auth-service"}),
    ]
    
    for desc, filter_params in filters:
        print(f"\n   📌 过滤: {desc}")
        
        start_time = time.time()
        results = bm25_search(
            query=query,
            top_k=5,
            level=filter_params.get('level'),
            service=filter_params.get('service'),
        )
        elapsed = (time.time() - start_time) * 1000
        
        print(f"      ⏱️  耗时: {elapsed:.2f}ms")
        print(f"      📊 结果数: {len(results)}")
        
        if results:
            for r in results[:3]:
                print(f"         - {r['payload'].get('level')} | {r['payload'].get('service')} | score={r['score']:.2f}")
                print(f"           {r['payload'].get('chunk_text', '')[:40]}...")


def test_bm25_performance():
    """测试 BM25 性能"""
    print("\n" + "=" * 70)
    print("⚡ BM25 性能测试")
    print("=" * 70)
    
    query = "timeout database"
    times = []
    
    for i in range(10):
        start_time = time.time()
        bm25_search(query, top_k=5)
        elapsed = (time.time() - start_time) * 1000
        times.append(elapsed)
    
    avg_time = sum(times) / len(times)
    max_time = max(times)
    min_time = min(times)
    
    print(f"\n📊 10次检索统计:")
    print(f"   平均耗时: {avg_time:.2f}ms")
    print(f"   最快: {min_time:.2f}ms")
    print(f"   最慢: {max_time:.2f}ms")
    print(f"   ✅ 目标: < 100ms")
    
    if avg_time < 100:
        print("   ✅ 性能达标!")
    else:
        print(f"   ⚠️ 性能超目标 {(avg_time-100):.2f}ms")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("🚀 开始 BM25 检索测试")
    print("=" * 70)
    
    test_bm25_basic()
    test_bm25_with_filters()
    test_bm25_performance()
    
    print("\n" + "=" * 70)
    print("✅ 测试完成")
    print("=" * 70)