# scripts/test_conversation.py
"""测试多轮对话功能"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.conversation import create_conversation_pipeline


def test_conversation():
    """测试多轮对话"""
    print("=" * 70)
    print("多轮对话测试")
    print("=" * 70)
    
    # 创建 pipeline
    pipeline = create_conversation_pipeline(
        top_k=5,
        retriever_type="hybrid",
        max_messages=10
    )
    
    print(f"\n对话ID: {pipeline.conversation_id}")
    
    # 第一轮
    print("\n[第1轮] 问题: auth-service 报错是什么原因？")
    result1 = pipeline.ask("auth-service 报错是什么原因？")
    print(f"回答: {result1.answer[:200]}...")
    print(f"Token: {result1.total_tokens}")
    
    # 第二轮（上下文）
    print("\n[第2轮] 问题: 具体是哪个日志文件？")
    result2 = pipeline.ask("具体是哪个日志文件？")
    print(f"回答: {result2.answer[:200]}...")
    
    # 第三轮
    print("\n[第3轮] 问题: 怎么修复这个问题？")
    result3 = pipeline.ask("怎么修复这个问题？")
    print(f"回答: {result3.answer[:200]}...")
    
    # 查看历史
    print("\n" + "=" * 70)
    print("对话历史:")
    print("=" * 70)
    history = pipeline.get_history()
    for i, msg in enumerate(history, 1):
        role = "👤 用户" if msg["role"] == "user" else "🤖 助手"
        content = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
        print(f"{i}. {role}: {content}")
    
    # 统计
    print("\n" + "=" * 70)
    print(f"总消息数: {len(history)}")
    
    # 清空测试
    print("\n清空对话...")
    pipeline.clear()
    history = pipeline.get_history()
    print(f"清空后消息数: {len(history)}")


if __name__ == "__main__":
    test_conversation()