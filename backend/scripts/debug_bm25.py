#!/usr/bin/env python
"""
调试 BM25 分词和匹配问题
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jieba
from services.bm25_retriever import get_bm25_retriever
from services.qdrant_client import get_qdrant_client


def debug_tokenization():
    """调试分词效果"""
    print("=" * 70)
    print("🔍 调试 BM25 分词")
    print("=" * 70)
    
    # 1. 获取一些样本数据
    client = get_qdrant_client()
    scroll_result = client.client.scroll(
        collection_name="log_vectors",
        limit=10,
        with_payload=True,
        with_vectors=False,
    )
    
    points = scroll_result[0]
    
    print("\n1. 样本日志内容:")
    for i, point in enumerate(points[:5]):
        payload = point.payload
        text = payload.get('chunk_text', '')
        print(f"   {i+1}. {text}")
    
    # 2. 测试分词
    print("\n2. 分词效果测试:")
    
    sample_texts = [
        "Connection timeout to database",
        "OutOfMemoryError: Java heap space",
        "File not found: /var/log/app.log",
        "数据库连接失败",
        "内存溢出",
    ]
    
    for text in sample_texts:
        tokens = jieba.lcut(text)
        print(f"\n   原文: {text}")
        print(f"   分词: {tokens}")
        print(f"   词数: {len(tokens)}")
    
    # 3. 检查 BM25 索引中的文档
    print("\n3. 检查 BM25 索引中的文档:")
    retriever = get_bm25_retriever()
    
    if retriever.documents:
        print(f"   文档数: {len(retriever.documents)}")
        print(f"\n   前3个文档的分词结果:")
        for i in range(min(3, len(retriever.tokenized_corpus))):
            tokens = retriever.tokenized_corpus[i]
            print(f"   {i+1}. {tokens[:10]}...")
    else:
        print("   ❌ 没有文档")


def test_search_debug():
    """调试检索过程"""
    print("\n" + "=" * 70)
    print("🔍 调试 BM25 检索")
    print("=" * 70)
    
    retriever = get_bm25_retriever()
    
    # 测试不同的查询
    test_queries = [
        ("timeout", "英文关键词"),
        ("database", "英文关键词"),
        ("连接", "中文关键词"),
        ("数据库", "中文关键词"),
        ("timeout database", "英文组合"),
        ("数据库连接", "中文组合"),
    ]
    
    for query, desc in test_queries:
        print(f"\n📌 查询: '{query}' ({desc})")
        
        # 手动分词
        tokens = jieba.lcut(query)
        print(f"   分词: {tokens}")
        
        # 执行检索
        results = retriever.search(query, top_k=3)
        print(f"   结果数: {len(results)}")
        
        if results:
            for r in results[:2]:
                print(f"   - score={r.score:.2f}, log_id={r.log_id}")
                print(f"     text: {r.payload.get('chunk_text', '')[:50]}...")


if __name__ == "__main__":
    debug_tokenization()
    test_search_debug()