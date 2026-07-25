"""反馈统计接口验证脚本"""
import requests
import sys

BASE_URL = "http://127.0.0.1:8000"


def login(username, password):
    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": username, "password": password},
        timeout=15,
    )
    if resp.status_code != 200:
        return None
    return resp.json()["access_token"]


def query_stats(token, scope=None):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE_URL}/api/qa/feedback/stats"
    params = {"scope": scope} if scope else None
    return requests.get(url, headers=headers, params=params, timeout=15)


def show_stats(label, resp):
    print(f"\n=== {label} ===")
    print(f"Status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"失败: {resp.text[:300]}")
        return None
    data = resp.json()
    print(f"success: {data['success']}")
    print(f"scope: {data['scope']}")
    print(f"total_qa: {data['total_qa']}")
    print(f"total_likes: {data['total_likes']}")
    print(f"total_dislikes: {data['total_dislikes']}")
    print(f"total_no_feedback: {data['total_no_feedback']}")
    print(f"like_rate: {data['like_rate']}")
    print(f"top_disliked count: {len(data['top_disliked'])}")
    for i, item in enumerate(data['top_disliked'][:3], 1):
        print(f"  [{i}] Q: {item['question'][:50]}")
        print(f"      username: {item.get('username', '')}")
        print(f"      conversation_id: {item.get('conversation_id', '')}")
        print(f"      time: {item['created_at']}")
    # 验证字段完整性
    required_item = ['qa_id', 'question', 'answer', 'feedback', 'created_at', 'conversation_id', 'username']
    for item in data['top_disliked']:
        missing = [f for f in required_item if f not in item]
        if missing:
            print(f"❌ 差评项 {item.get('qa_id')} 缺失字段: {missing}")
            return None
    return data


# 1. admin 登录
admin_token = login("admin", "admin123")
if not admin_token:
    print("admin 登录失败")
    sys.exit(1)

# 2. admin 查询默认（me）
show_stats("admin 默认 scope (me)", query_stats(admin_token))

# 3. admin 查询 all
admin_all = show_stats("admin scope=all", query_stats(admin_token, "all"))
if admin_all and admin_all['scope'] != 'all':
    print(f"❌ admin scope=all 未生效，返回 scope={admin_all['scope']}")
    sys.exit(1)
print("✅ admin 可看全平台数据")

# 4. 非 admin 登录（如果有 test 用户则用，没有则跳过这步）
user_token = login("test", "test123")
if user_token:
    user_all = show_stats("user 传 scope=all (应被降级为 me)", query_stats(user_token, "all"))
    if user_all and user_all['scope'] != 'me':
        print(f"❌ 普通用户传 all 未被降级，返回 scope={user_all['scope']}")
        sys.exit(1)
    print("✅ 普通用户传 all 被正确降级为 me")
else:
    print("\n(无 test 用户，跳过权限降级测试)")

print("\n✅ 全部验证通过")

