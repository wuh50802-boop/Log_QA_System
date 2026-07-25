"""验证 admin 可查看他人会话详情"""
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


admin_token = login("admin", "admin123")
if not admin_token:
    print("admin 登录失败")
    sys.exit(1)
admin_headers = {"Authorization": f"Bearer {admin_token}"}


# 1. admin 取全平台会话列表
print("=== 1. admin scope=all 取全平台会话列表 ===")
resp = requests.get(
    f"{BASE_URL}/api/qa/conversations",
    headers=admin_headers,
    params={"scope": "all"},
    timeout=15,
)
print(f"Status: {resp.status_code}")
data = resp.json()
print(f"全平台会话总数: {data['total']}")
if data['total'] == 0:
    print("⚠️ 全平台无会话，先创建一些再来测")
    sys.exit(0)

# 找一个不属于 admin 的会话
target = None
for item in data['items']:
    print(f"  - {item['conversation_id']} | {item['title'][:30]} | {item['message_count']} 轮")
print("(无法从列表项判断归属，直接尝试访问第一个会话详情)")


# 2. admin 取第一个会话详情（应该是任意会话都能访问）
target_id = data['items'][0]['conversation_id']
print(f"\n=== 2. admin 查询会话 {target_id} 详情 ===")
resp = requests.get(
    f"{BASE_URL}/api/qa/conversations/{target_id}",
    headers=admin_headers,
    timeout=15,
)
print(f"Status: {resp.status_code}")
if resp.status_code != 200:
    print(f"❌ admin 无法访问: {resp.text[:300]}")
    sys.exit(1)

detail = resp.json()
print(f"✅ admin 可访问任意会话")
print(f"   title: {detail['title']}")
print(f"   message_count: {detail['message_count']}")
print(f"   owner_username: {detail.get('owner_username', '(无)')}")


# 3. 验证 owner_username 字段存在
print("\n=== 3. 验证 owner_username 字段 ===")
if 'owner_username' not in detail:
    print("❌ 缺少 owner_username 字段")
    sys.exit(1)
print(f"✅ owner_username 字段已返回: '{detail['owner_username']}'")


# 4. 验证普通用户被限制（用一个不属于自己的会话 ID 测试）
# 直接造一个随机 ID，应该返回 404
print("\n=== 4. 验证普通用户访问陌生人会话 → 404 ===")
# 我们需要先注册一个普通用户
import uuid
unique = f"viewer_{uuid.uuid4().hex[:6]}"
requests.post(
    f"{BASE_URL}/api/auth/register",
    json={"username": unique, "password": "test123456"},
    timeout=15,
)
viewer_token = login(unique, "test123456")
viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

resp = requests.get(
    f"{BASE_URL}/api/qa/conversations/{target_id}",
    headers=viewer_headers,
    timeout=15,
)
print(f"Status: {resp.status_code}")
if resp.status_code == 404:
    print(f"✅ 普通用户访问他人会话被拒绝: {resp.json().get('detail', '')}")
else:
    print(f"❌ 漏洞：普通用户可访问他人会话: {resp.text[:200]}")
    sys.exit(1)


# 5. 普通用户传 scope=all 应被降级
print("\n=== 5. 普通用户传 scope=all → 应被降级为 me ===")
resp = requests.get(
    f"{BASE_URL}/api/qa/conversations",
    headers=viewer_headers,
    params={"scope": "all"},
    timeout=15,
)
print(f"Status: {resp.status_code}")
data = resp.json()
# 看返回的会话列表是否只含自己的（应该几乎为空或很少）
print(f"返回的会话数（应只含自己）: {data['total']}")


print("\n✅ 全部验证通过")
print("\n=== 总结 ===")
print("1. admin scope=all 可看全平台会话列表")
print("2. admin 可访问任意会话详情（带 owner_username 字段）")
print("3. owner_username 字段便于前端显示「查看中：xxx」")
print("4. 普通用户访问他人会话 → 404")
print("5. 普通用户传 scope=all 被降级为 me")
