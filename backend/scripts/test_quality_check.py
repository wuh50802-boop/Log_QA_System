"""测试回答质量自检功能"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.quality_checker import (
    QualityChecker, 
    QualityAwarePipeline,
    create_quality_pipeline,
    calculate_self_check_pass_rate
)


def test_quality_checker():
    """测试质量检查器"""
    print("=" * 70)
    print("回答质量自检测试")
    print("=" * 70)
    
    checker = QualityChecker()
    
    # 测试用例
    test_cases = [
        {
            "name": "高质量回答",
            "answer": """【问题理解】用户询问 auth-service 的异常情况。
【关键证据】根据日志 [ID:6792]，auth-service 在 2026-07-18 01:20:38 发生了 NullPointerException。
【分析推断】从日志 [ID:6792] 可以看出，错误发生在 UserService 中，可能是空指针调用导致。
【结论建议】建议检查 UserService 的初始化逻辑。
【置信度】高""",
            "sources": [{"log_id": 6792}, {"log_id": 231}]
        },
        {
            "name": "缺少引用",
            "answer": """【问题理解】用户询问 auth-service 的异常情况。
【关键证据】auth-service 发生了 NullPointerException。
【分析推断】可能是空指针调用导致。
【结论建议】建议检查代码。
【置信度】高""",
            "sources": [{"log_id": 6792}]
        },
        {
            "name": "包含幻觉",
            "answer": """【问题理解】用户询问系统状态。
【关键证据】根据我的经验，系统通常会有这个问题。
【分析推断】可能和网络有关。
【结论建议】重启服务。
【置信度】高""",
            "sources": [{"log_id": 123}]
        },
        {
            "name": "证据不足但宣称高置信度",
            "answer": """【问题理解】用户询问问题原因。
【关键证据】无。
【分析推断】可能是配置问题。
【结论建议】检查配置。
【置信度】高""",
            "sources": []
        },
        {
            "name": "自相矛盾",
            "answer": """【问题理解】用户询问系统状态。
【关键证据】日志显示没有错误。
【分析推断】系统运行正常，但出现了异常。
【结论建议】建议检查。
【置信度】中""",
            "sources": [{"log_id": 123}]
        }
    ]
    
    results = []
    for case in test_cases:
        print(f"\n📌 {case['name']}")
        print("-" * 40)
        result = checker.check(
            answer=case['answer'],
            sources=case['sources']
        )
        results.append(result)
        
        print(f"通过: {result.passed}")
        print(f"得分: {result.score:.1f}/100")
        if result.issues:
            print(f"问题: {len(result.issues)} 个")
            for issue in result.issues:
                print(f"  - {issue.get('message', '')}")
        if result.warnings:
            print(f"警告: {len(result.warnings)} 个")
            for warning in result.warnings:
                print(f"  - {warning}")
        if result.suggestions:
            print(f"建议: {result.suggestions[0]}")
    
    # 统计
    print("\n" + "=" * 70)
    print("📊 质量检查统计")
    print("=" * 70)
    stats = calculate_self_check_pass_rate(results)
    print(f"通过率: {stats['pass_rate']:.1f}%")
    print(f"平均得分: {stats['avg_score']:.1f}/100")
    print(f"通过: {stats['passed']}/{stats['total']}")
    
    return results


def test_quality_pipeline():
    """测试集成质量检查的 Pipeline"""
    print("\n" + "=" * 70)
    print("集成质量检查 Pipeline 测试")
    print("=" * 70)
    
    # 创建支持质量检查的 pipeline
    pipeline = create_quality_pipeline(
        top_k=5,
        retriever_type="hybrid"
    )
    
    # 测试多轮问答的质量检查
    questions = [
        "auth-service 有什么异常？",
        "这个错误是什么原因？",
        "怎么修复？"
    ]
    
    results = []
    for question in questions:
        print(f"\n📌 问题: {question}")
        print("-" * 40)
        
        result = pipeline.ask(question)
        
        print(f"回答预览: {result.answer[:150]}...")
        print(f"来源数: {len(result.sources)}")
        print(f"置信度: {result.confidence}")
        
        # 质量检查结果
        check = pipeline.get_last_check()
        print(f"质量检查: {'✅ 通过' if check.passed else '❌ 未通过'}")
        print(f"质量得分: {check.score:.1f}/100")
        if check.issues:
            print(f"问题: {check.issues[0].get('message', '')}")
        
        results.append(check)
    
    # 统计
    print("\n" + "=" * 70)
    print("📊 质量检查统计")
    print("=" * 70)
    stats = pipeline.get_check_stats()
    print(f"通过率: {stats['pass_rate']:.1f}%")
    print(f"平均得分: {stats['avg_score']:.1f}/100")
    print(f"通过: {stats['passed']}/{stats['total']}")


if __name__ == "__main__":
    # 运行测试
    test_quality_checker()
    test_quality_pipeline()