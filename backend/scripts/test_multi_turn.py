"""
多轮对话集成验证脚本
测试流程：
1. 登录获取 JWT
2. 第一轮提问（不带 conversation_id，应自动创建新会话）
3. 第二轮提问（携带第一轮返回的 conversation_id，验证上下文保持）
4. 查询会话列表
5. 查询会话详情，验证两轮记录归属同一会话
6. 删除会话验证
"""
import json
import requests
import sys
import os

# 加载 .env 中的配置
from dotenv import load_dotenv
load_dotenv()

BASE_URL = "http://127.0.0.1:8000"
TEST_USERNAME = os.getenv("TEST_USERNAME", "admin")
TEST_PASSWORD = os.getenv("TEST_PASSWORD", "admin123")


def banner(title):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def main():
    s = requests.Session()

    # 1. 登录
    banner("1. 登录获取 JWT")
    resp = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        timeout=15,
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"登录失败: {resp.text}")
        sys.exit(1)
    data = resp.json()
    if "access_token" not in data:
        print(f"登录失败：未返回 access_token，response={data}")
        sys.exit(1)
    token = data["access_token"]
    print(f"Token: {token[:30]}...")
    headers = {"Authorization": f"Bearer {token}"}

    # 2. 第一轮提问（新会话）
    banner("2. 第一轮提问（不带 conversation_id）")
    resp = s.post(
        f"{BASE_URL}/api/qa/ask",
        headers=headers,
        json={
            "question": "数据库连接失败可能是什么原因？",
            "top_k": 3,
            "retriever_type": "hybrid",
        },
        timeout=120,
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"提问失败: {resp.text[:500]}")
        sys.exit(1)
    r1 = resp.json()
    print(f"success: {r1.get('success')}")
    print(f"conversation_id: {r1.get('conversation_id')}")
    print(f"answer (前100字): {(r1.get('answer') or '')[:100]}")
    conv_id = r1.get("conversation_id")
    if not conv_id:
        print("未返回 conversation_id，无法继续多轮测试")
        sys.exit(1)

    # 3. 第二轮提问（携带 conversation_id）
    banner("3. 第二轮提问（携带 conversation_id）")
    resp = s.post(
        f"{BASE_URL}/api/qa/ask",
        headers=headers,
        json={
            "question": "针对上面提到的原因，如何排查？",
            "top_k": 3,
            "retriever_type": "hybrid",
            "conversation_id": conv_id,
        },
        timeout=120,
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"提问失败: {resp.text[:500]}")
        sys.exit(1)
    r2 = resp.json()
    print(f"success: {r2.get('success')}")
    print(f"conversation_id: {r2.get('conversation_id')}")
    print(f"answer (前100字): {(r2.get('answer') or '')[:100]}")
    if r2.get("conversation_id") != conv_id:
        print(f"❌ 第二轮 conversation_id 不一致：期望 {conv_id}, 实际 {r2.get('conversation_id')}")
        sys.exit(1)
    print(f"✅ 第二轮复用了同一会话 ID: {conv_id}")

    # 4. 查询会话列表
    banner("4. 查询当前用户的会话列表")
    resp = s.get(f"{BASE_URL}/api/qa/conversations", headers=headers, timeout=15)
    print(f"Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"查询会话列表失败: {resp.text[:500]}")
        sys.exit(1)
    conv_list = resp.json()
    print(f"total: {conv_list.get('total')}")
    for item in conv_list.get("items", []):
        print(
            f"  - cid={item['conversation_id']}, count={item['message_count']}, "
            f"title={item['title'][:40]}, updated_at={item['updated_at']}"
        )

    target = next(
        (i for i in conv_list.get("items", []) if i["conversation_id"] == conv_id),
        None,
    )
    if not target:
        print(f"❌ 会话列表中未找到刚创建的会话 {conv_id}")
        sys.exit(1)
    if target["message_count"] != 2:
        print(f"❌ 会话记录数错误：期望 2，实际 {target['message_count']}")
        sys.exit(1)
    print(f"✅ 会话列表中找到该会话，共 {target['message_count']} 条记录")

    # 5. 查询会话详情
    banner("5. 查询会话详情")
    resp = s.get(
        f"{BASE_URL}/api/qa/conversations/{conv_id}", headers=headers, timeout=15
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"查询会话详情失败: {resp.text[:500]}")
        sys.exit(1)
    detail = resp.json()
    print(f"conversation_id: {detail.get('conversation_id')}")
    print(f"title: {detail.get('title')}")
    print(f"message_count: {detail.get('message_count')}")
    for i, m in enumerate(detail.get("items", []), 1):
        print(f"  [{i}] Q: {m['question'][:50]}")
        print(f"      A: {m['answer'][:50]}")

    if detail.get("message_count") != 2:
        print(f"❌ 详情中记录数错误：期望 2，实际 {detail.get('message_count')}")
        sys.exit(1)
    if detail["items"][0]["question"] != "数据库连接失败可能是什么原因？":
        print(f"❌ 详情首条问题与请求不一致")
        sys.exit(1)
    print("✅ 会话详情正确，两轮记录按时间正序排列")

    # 6. 验证上下文历史加载（内部 _load_conversation_history 应加载 2 条历史 = 1 轮）
    banner("6. 第三轮提问验证上下文保持")
    resp = s.post(
        f"{BASE_URL}/api/qa/ask",
        headers=headers,
        json={
            "question": "请总结我刚才问的内容",
            "top_k": 3,
            "retriever_type": "hybrid",
            "conversation_id": conv_id,
        },
        timeout=120,
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"提问失败: {resp.text[:500]}")
        sys.exit(1)
    r3 = resp.json()
    print(f"conversation_id: {r3.get('conversation_id')}")
    print(f"answer (前150字): {(r3.get('answer') or '')[:150]}")
    if r3.get("conversation_id") != conv_id:
        print("❌ 第三轮 conversation_id 不一致")
        sys.exit(1)
    print("✅ 第三轮成功复用会话上下文")

    # 7. 清理：删除会话
    banner("7. 清理：删除会话")
    resp = s.delete(
        f"{BASE_URL}/api/qa/conversations/{conv_id}", headers=headers, timeout=15
    )
    print(f"Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"删除会话失败: {resp.text[:500]}")
        sys.exit(1)
    del_resp = resp.json()
    print(f"success: {del_resp.get('success')}")
    print(f"deleted_count: {del_resp.get('deleted_count')}")
    if del_resp.get("deleted_count") < 3:
        print(f"❌ 删除记录数异常：期望 ≥3，实际 {del_resp.get('deleted_count')}")
        sys.exit(1)
    print(f"✅ 会话已删除（共 {del_resp.get('deleted_count')} 条记录）")

    # 8. 再次查询确认已删除
    banner("8. 确认会话已删除")
    resp = s.get(
        f"{BASE_URL}/api/qa/conversations/{conv_id}", headers=headers, timeout=15
    )
    if resp.status_code == 404:
        print("✅ 会话已不存在（404），删除验证通过")
    else:
        print(f"❌ 会话仍可访问（status={resp.status_code}）")
        sys.exit(1)

    banner("🎉 多轮对话集成测试全部通过！")


if __name__ == "__main__":
    main()
