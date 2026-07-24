"""
DeepSeek API 快速测试脚本
运行: python scripts/test_llm.py
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.llm_client import get_simple_response, stream_response


def main():
    print("=" * 60)
    print("DeepSeek API 快速测试")
    print("=" * 60)

    # 测试1：同步调用
    print("\n[1] 测试同步调用...")
    try:
        result = get_simple_response("用一句话解释什么是日志分析")
        print(f"    回答: {result}")
        print("    [通过]")
    except Exception as e:
        print(f"    [失败] {e}")
        return 1

    # 测试2：流式调用
    print("\n[2] 测试流式调用...")
    try:
        print("    回答: ", end="")
        for chunk in stream_response("什么是 404 错误？简单回答"):
            print(chunk, end="", flush=True)
        print("\n    [通过]")
    except Exception as e:
        print(f"\n    [失败] {e}")
        return 1

    print("\n" + "=" * 60)
    print("✅ 所有测试通过！")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())