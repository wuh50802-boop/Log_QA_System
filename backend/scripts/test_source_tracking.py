"""测试来源溯源功能"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.qa_pipeline import create_pipeline


def test_source_tracking():
    """测试来源溯源"""
    print("=" * 70)
    print("来源溯源功能测试")
    print("=" * 70)
    
    pipeline = create_pipeline(
        top_k=5,
        retriever_type="hybrid",
        max_log_length=300
    )
    
    question = "user-service 有什么错误？"
    print(f"\n问题: {question}")
    print("-" * 70)
    
    result = pipeline.ask(question)
    
    print("\n📝 回答（带来源标注）:")
    print("-" * 70)
    print(result.answer)
    
    print("\n" + "=" * 70)
    print("📎 来源追溯")
    print("=" * 70)
    
    for ref in result.source_refs:
        print(f"\n{ref.ref_id} -> 日志ID: {ref.log_id}")
        print(f"  服务: {ref.service}")
        print(f"  时间: {ref.timestamp}")
        print(f"  级别: {ref.level}")
        print(f"  片段: {ref.snippet}")
    
    print("\n" + "=" * 70)
    print("📄 Markdown 格式输出")
    print("=" * 70)
    print(result.to_markdown())


def test_multi_turn_source_tracking():
    """测试多轮对话中的来源溯源"""
    print("\n" + "=" * 70)
    print("多轮对话 + 来源溯源测试")
    print("=" * 70)
    
    pipeline = create_pipeline(
        top_k=5,
        retriever_type="hybrid",
        max_log_length=300
    )
    
    print(f"\n📌 对话ID: {id(pipeline)}")
    
    # 第一轮
    print("\n" + "-" * 70)
    print("【第1轮】问题: auth-service 有什么异常？")
    print("-" * 70)
    
    result1 = pipeline.ask("auth-service 有什么异常？")
    print(f"\n回答:\n{result1.answer}")
    print(f"\n来源数: {len(result1.source_refs)}")
    if result1.source_refs:
        print(f"引用: {', '.join([r.ref_id for r in result1.source_refs])}")
    
    # 第二轮（追问具体错误）
    print("\n" + "-" * 70)
    print("【第2轮】追问: 这个错误是什么原因导致的？")
    print("-" * 70)
    
    result2 = pipeline.ask("这个错误是什么原因导致的？")
    print(f"\n回答:\n{result2.answer}")
    print(f"\n来源数: {len(result2.source_refs)}")
    if result2.source_refs:
        print(f"引用: {', '.join([r.ref_id for r in result2.source_refs])}")
    
    # 第三轮（询问修复方案）
    print("\n" + "-" * 70)
    print("【第3轮】追问: 怎么修复这个问题？")
    print("-" * 70)
    
    result3 = pipeline.ask("怎么修复这个问题？")
    print(f"\n回答:\n{result3.answer}")
    print(f"\n来源数: {len(result3.source_refs)}")
    if result3.source_refs:
        print(f"引用: {', '.join([r.ref_id for r in result3.source_refs])}")
    
    # 显示完整对话历史
    print("\n" + "=" * 70)
    print("📋 完整对话历史（带来源标注）")
    print("=" * 70)
    
    history = pipeline.get_history()
    for i, msg in enumerate(history, 1):
        role = "👤 用户" if msg["role"] == "user" else "🤖 助手"
        content = msg["content"][:300] + "..." if len(msg["content"]) > 300 else msg["content"]
        print(f"\n{i}. {role}:")
        print(f"   {content}")
    
    # 统计
    print("\n" + "=" * 70)
    print("📊 统计信息")
    print("=" * 70)
    print(f"总消息数: {len(history)}")
    print(f"第1轮 Token: {result1.total_tokens}")
    print(f"第2轮 Token: {result2.total_tokens}")
    print(f"第3轮 Token: {result3.total_tokens}")


def test_source_traceability():
    """测试来源的可追溯性"""
    print("\n" + "=" * 70)
    print("🔍 来源可追溯性测试")
    print("=" * 70)
    
    pipeline = create_pipeline(
        top_k=5,
        retriever_type="hybrid",
        max_log_length=300
    )
    
    question = "auth-service 报错是什么原因？"
    print(f"\n问题: {question}")
    print("-" * 70)
    
    result = pipeline.ask(question)
    
    print("\n📝 回答:")
    print("-" * 70)
    print(result.answer)
    
    print("\n" + "=" * 70)
    print("🔗 双向追溯测试")
    print("=" * 70)
    
    # 1. 从回答中的引用追溯到日志
    print("\n【正向追溯】回答中的引用 → 原始日志")
    print("-" * 40)
    
    for ref in result.source_refs:
        print(f"\n{ref.ref_id} 详情:")
        print(f"  → 日志ID: {ref.log_id}")
        print(f"  → 服务: {ref.service}")
        print(f"  → 时间: {ref.timestamp}")
        print(f"  → 级别: {ref.level}")
        print(f"  → 完整内容: {ref.content[:200]}...")
    
    # 2. 从日志ID查找引用
    if result.source_refs:
        print("\n【反向追溯】日志ID → 回答中的引用")
        print("-" * 40)
        
        test_log_id = result.source_refs[0].log_id
        print(f"\n查找日志ID: {test_log_id}")
        
        found_refs = result.get_source_by_log_id(test_log_id)
        for ref in found_refs:
            print(f"  → 引用: {ref.ref_id}")
            print(f"  → 服务: {ref.service}")
            print(f"  → 片段: {ref.snippet}")
    
    # 3. 按引用ID查找
    if result.source_refs:
        print("\n【按引用ID查找】")
        print("-" * 40)
        
        test_ref_id = result.source_refs[0].ref_id
        print(f"\n查找引用: {test_ref_id}")
        
        found = result.get_source_by_ref(test_ref_id)
        if found:
            print(f"  → 日志ID: {found.log_id}")
            print(f"  → 服务: {found.service}")
            print(f"  → 完整内容: {found.content[:150]}...")


def compare_source_formats():
    """比较不同来源格式输出"""
    print("\n" + "=" * 70)
    print("📄 来源输出格式对比")
    print("=" * 70)
    
    pipeline = create_pipeline(
        top_k=3,
        retriever_type="hybrid",
        max_log_length=300
    )
    
    result = pipeline.ask("user-service 有什么问题？")
    
    print("\n【格式1: 原始回答】")
    print("-" * 40)
    print(result.answer)
    
    print("\n【格式2: Markdown】")
    print("-" * 40)
    print(result.to_markdown())
    
    print("\n【格式3: 来源列表 (Dict)】")
    print("-" * 40)
    for ref_dict in result.get_sources_with_refs():
        print(f"  {ref_dict['ref_id']}: {ref_dict['service']} | {ref_dict['level']}")
        print(f"    内容: {ref_dict['content'][:80]}...")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("来源溯源功能测试套件")
    print("=" * 70)
    
    # 运行所有测试
    test_source_tracking()
    test_multi_turn_source_tracking()
    test_source_traceability()
    compare_source_formats()