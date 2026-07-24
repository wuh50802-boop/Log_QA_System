"""
问答 Pipeline 测试脚本
运行: python scripts/test_qa_pipeline.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.qa_pipeline import QAPipeline, create_pipeline, QAResult, StreamChunk


def print_result(result: QAResult):
    """打印问答结果"""
    print("\n" + "-" * 50)
    print(f"检索器: {result.retriever_type}")
    print(f"问题: {result.question}")
    answer_preview = result.answer[:200] + "..." if len(result.answer) > 200 else result.answer
    print(f"回答: {answer_preview}")
    print(f"置信度: {result.confidence}")
    print(f"来源数: {len(result.sources)}")
    print(f"Token: {result.total_tokens}")
    print(f"检索耗时: {result.retrieval_time:.3f}s")
    print(f"LLM耗时: {result.llm_time:.3f}s")
    print(f"总耗时: {result.total_time:.3f}s")
    
    if result.sources:
        print("\n来源日志:")
        for i, source in enumerate(result.sources[:3], 1):
            print(f"  {i}. [ID:{source.get('log_id')}] {source.get('service')} "
                  f"{source.get('timestamp')}")
            content = source.get('content', '')[:80]
            print(f"     {content}...")
    print("-" * 50)


def main():
    print("=" * 70)
    print("问答 Pipeline 测试")
    print("=" * 70)

    passed = 0
    failed = 0

    # ============================================================
    # 测试1：向量检索 Pipeline
    # ============================================================
    print("\n[1] 测试向量检索 Pipeline...")
    try:
        pipeline = create_pipeline(top_k=5, retriever_type="vector")
        result = pipeline.ask("数据库连接失败是什么原因？")
        
        assert result.answer is not None
        assert len(result.answer) > 0
        assert result.retriever_type == "vector"
        passed += 1
        print("    ✅ 通过")
        print(f"    检索耗时: {result.retrieval_time:.3f}s")
        print(f"    来源数: {len(result.sources)}")
    except Exception as e:
        failed += 1
        print(f"    ❌ 失败: {e}")

    # ============================================================
    # 测试2：关键词检索 Pipeline (BM25)
    # ============================================================
    print("\n[2] 测试关键词检索 Pipeline (BM25)...")
    try:
        pipeline = create_pipeline(top_k=5, retriever_type="bm25")
        result = pipeline.ask("数据库连接超时")
        
        assert result.answer is not None
        assert len(result.answer) > 0
        assert result.retriever_type == "bm25"
        passed += 1
        print("    ✅ 通过")
        print(f"    检索耗时: {result.retrieval_time:.3f}s")
        print(f"    来源数: {len(result.sources)}")
    except Exception as e:
        failed += 1
        print(f"    ❌ 失败: {e}")

    # ============================================================
    # 测试3：混合检索 Pipeline
    # ============================================================
    print("\n[3] 测试混合检索 Pipeline...")
    try:
        pipeline = create_pipeline(top_k=5, retriever_type="hybrid")
        result = pipeline.ask("用户登录失败")
        
        assert result.question == "用户登录失败"
        assert result.answer is not None
        assert len(result.answer) > 0
        assert result.retriever_type == "hybrid"
        passed += 1
        print("    ✅ 通过")
        print_result(result)
    except Exception as e:
        failed += 1
        print(f"    ❌ 失败: {e}")

    # ============================================================
    # 测试4：三种检索器对比
    # ============================================================
    print("\n[4] 三种检索器对比测试...")
    
    question = "auth-service 报错是什么原因？"
    print(f"问题: {question}")
    print("-" * 50)
    
    retriever_types = ["vector", "bm25", "hybrid"]
    results = {}
    
    for retriever_type in retriever_types:
        try:
            print(f"\n[检索器: {retriever_type}]")
            pipeline = create_pipeline(top_k=5, retriever_type=retriever_type)
            result = pipeline.ask(question)
            results[retriever_type] = result
            
            print(f"  来源数: {len(result.sources)}")
            print(f"  检索耗时: {result.retrieval_time:.3f}s")
            print(f"  置信度: {result.confidence}")
            
            if result.sources:
                first_source = result.sources[0]
                print(f"  最高分来源: {first_source.get('service')} "
                      f"score={first_source.get('score', 0):.3f}")
                print(f"  内容: {first_source.get('content', '')[:50]}...")
            
        except Exception as e:
            print(f"  ❌ {retriever_type} 检索失败: {e}")
    
    if results:
        passed += 1
        print("\n    ✅ 通过")
    else:
        failed += 1
        print("    ❌ 失败")

    # ============================================================
    # 测试5：带过滤条件的问答
    # ============================================================
    print("\n[5] 测试带过滤条件的问答...")
    try:
        pipeline = create_pipeline(top_k=5, retriever_type="hybrid")
        result = pipeline.ask(
            "有什么异常？",
            filters={"level": "ERROR"}
        )
        assert result.answer is not None
        assert len(result.answer) > 0
        passed += 1
        print("    ✅ 通过")
        print(f"    来源数: {len(result.sources)}")
    except Exception as e:
        failed += 1
        print(f"    ❌ 失败: {e}")

    # ============================================================
    # 测试6：流式问答
    # ============================================================
    print("\n[6] 测试流式问答...")
    try:
        pipeline = create_pipeline(top_k=5, retriever_type="hybrid")
        chunks = []
        for chunk in pipeline.ask_stream("系统有什么警告？"):
            chunks.append(chunk)
            if chunk.type == "source":
                print(f"    [来源] {chunk.content}")
        
        assert len(chunks) > 0
        passed += 1
        print("    ✅ 通过")
    except Exception as e:
        failed += 1
        print(f"    ❌ 失败: {e}")

    # ============================================================
    # 测试7：基于上下文问答（跳过检索）
    # ============================================================
    print("\n[7] 测试基于上下文问答...")
    try:
        sample_logs = [
            {
                "log_id": 1001,
                "service": "auth-service",
                "timestamp": "2026-07-24 10:05:23",
                "level": "ERROR",
                "content": "Database connection timeout"
            }
        ]
        pipeline = create_pipeline(retriever_type="hybrid")
        answer = pipeline.ask_with_context(
            "这个日志说明了什么？",
            logs=sample_logs
        )
        assert answer is not None
        assert len(answer) > 0
        passed += 1
        print("    ✅ 通过")
        print(f"    回答: {answer[:100]}...")
    except Exception as e:
        failed += 1
        print(f"    ❌ 失败: {e}")

    # ============================================================
    # 测试8：对话历史
    # ============================================================
    print("\n[8] 测试对话历史...")
    try:
        pipeline = create_pipeline(retriever_type="hybrid")
        pipeline.ask("第一个问题")
        pipeline.ask("第二个问题")
        
        history = pipeline.get_history()
        assert len(history) == 4
        passed += 1
        print(f"    ✅ 通过（历史长度: {len(history)}）")
        for msg in history:
            role = "用户" if msg["role"] == "user" else "助手"
            content = msg["content"][:30] + "..." if len(msg["content"]) > 30 else msg["content"]
            print(f"    {role}: {content}")
    except Exception as e:
        failed += 1
        print(f"    ❌ 失败: {e}")

    # ============================================================
    # 测试9：清空历史
    # ============================================================
    print("\n[9] 测试清空历史...")
    try:
        pipeline = create_pipeline(retriever_type="hybrid")
        pipeline.ask("测试问题")
        pipeline.clear_history()
        history = pipeline.get_history()
        assert len(history) == 0
        passed += 1
        print("    ✅ 通过")
    except Exception as e:
        failed += 1
        print(f"    ❌ 失败: {e}")

    # ============================================================
    # 测试10：QAResult 数据类
    # ============================================================
    print("\n[10] 测试 QAResult 数据类...")
    try:
        result = QAResult(
            question="测试",
            answer="测试回答",
            sources=[],
            confidence="高",
            total_tokens=100,
            retriever_type="hybrid"
        )
        assert result.question == "测试"
        assert result.retriever_type == "hybrid"
        passed += 1
        print("    ✅ 通过")
    except Exception as e:
        failed += 1
        print(f"    ❌ 失败: {e}")

    # 输出结果
    print("\n" + "=" * 70)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    if failed == 0:
        print("✅ 所有测试通过！")
    else:
        print(f"❌ {failed} 个测试失败")
    print("=" * 70)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())