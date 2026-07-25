"""角色权限验证脚本

验证:
1. 注册接口不再接受 role 参数（强制 user）
2. 非 admin 调用 /users 与 /users/{id}/role 应被拒绝
3. admin 可调用 /users 列出用户
4. admin 可调用 /users/{id}/role 修改他人角色
5. admin 不可修改自己的角色
"""
import requests
import sys
import time
import uuid

BASE_URL = "http://127.0.0.1:8000"


def login(username, password):
    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": username, "password": password},
        timeout=15,
    )
    if resp.status_code != 200:
        return None, resp.text
    data = resp.json()
    return data["access_token"], data


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# 1. admin 登录
admin_token, admin_info = login("admin", "admin123")
if not admin_token:
    print(f"admin 登录失败: {admin_info}")
    sys.exit(1)
print(f"✅ admin 登录成功, role={admin_info['role']}")

# 从 /me 取 admin 的真实 user_id
resp = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers(admin_token), timeout=15)
admin_user_id = resp.json()['id']


# 2. 注册一个新用户（后端会忽略任何 role 字段，强制为 user）
unique = f"testuser_{uuid.uuid4().hex[:6]}"
print(f"\n=== 注册新用户 {unique}（尝试传 role=admin，应被忽略）===")
resp = requests.post(
    f"{BASE_URL}/api/auth/register",
    json={"username": unique, "password": "test123456", "role": "admin"},
    timeout=15,
)
print(f"Status: {resp.status_code}")
if resp.status_code != 200:
    print(f"❌ 注册失败: {resp.text}")
    sys.exit(1)
new_user = resp.json()
print(f"注册返回的 role: {new_user['role']}")
if new_user['role'] != 'user':
    print(f"❌ 漏洞未修复：传 role=admin 后用户角色变成了 {new_user['role']}")
    sys.exit(1)
print(f"✅ 漏洞已修复：即使传 role=admin，注册后角色仍为 user")
new_user_id = new_user['id']

# 用新用户登录，验证 token 的 role 也是 user
new_token, new_info = login(unique, "test123456")
if not new_token:
    print(f"❌ 新用户登录失败: {new_info}")
    sys.exit(1)
print(f"✅ 新用户登录成功, token 中 role={new_info['role']}")


# 3. 非 admin 调用 /users 应被拒绝（403）
print("\n=== 非 admin 调用 GET /api/auth/users（应返回 403）===")
resp = requests.get(f"{BASE_URL}/api/auth/users", headers=auth_headers(new_token), timeout=15)
print(f"Status: {resp.status_code}")
if resp.status_code == 403:
    print(f"✅ 权限隔离生效：{resp.json().get('detail', '')}")
else:
    print(f"❌ 漏洞：非 admin 可访问用户列表: {resp.text[:200]}")
    sys.exit(1)


# 4. 非 admin 调用 /users/{id}/role 应被拒绝（403）
print("\n=== 非 admin 调用 PATCH /api/auth/users/{id}/role（应返回 403）===")
resp = requests.patch(
    f"{BASE_URL}/api/auth/users/{new_user_id}/role",
    json={"role": "admin"},
    headers=auth_headers(new_token),
    timeout=15,
)
print(f"Status: {resp.status_code}")
if resp.status_code == 403:
    print(f"✅ 权限隔离生效：{resp.json().get('detail', '')}")
else:
    print(f"❌ 漏洞：非 admin 可修改角色: {resp.text[:200]}")
    sys.exit(1)


# 5. admin 调用 /users 列表（应成功）
print("\n=== admin 调用 GET /api/auth/users（应成功）===")
resp = requests.get(f"{BASE_URL}/api/auth/users", headers=auth_headers(admin_token), timeout=15)
print(f"Status: {resp.status_code}")
if resp.status_code != 200:
    print(f"❌ admin 无法列出用户: {resp.text[:200]}")
    sys.exit(1)
users_data = resp.json()
print(f"✅ admin 列出 {users_data['total']} 个用户")
for u in users_data['items'][:3]:
    print(f"  - id={u['id']} username={u['username']} role={u['role']}")


# 6. admin 把刚注册的用户提升为 admin
print(f"\n=== admin 把 {unique} (id={new_user_id}) 提升为 admin ===")
resp = requests.patch(
    f"{BASE_URL}/api/auth/users/{new_user_id}/role",
    json={"role": "admin"},
    headers=auth_headers(admin_token),
    timeout=15,
)
print(f"Status: {resp.status_code}")
if resp.status_code != 200:
    print(f"❌ 提升失败: {resp.text[:200]}")
    sys.exit(1)
result = resp.json()
print(f"✅ {result['message']}")
print(f"   old_role={result['old_role']} → new_role={result['new_role']}")


# 7. admin 尝试修改自己的角色（应被拒绝）
print(f"\n=== admin 尝试修改自己的角色（应返回 400）===")
resp = requests.patch(
    f"{BASE_URL}/api/auth/users/{admin_user_id}/role",
    json={"role": "user"},
    headers=auth_headers(admin_token),
    timeout=15,
)
print(f"Status: {resp.status_code}")
if resp.status_code == 400:
    print(f"✅ 安全约束生效：{resp.json().get('detail', '')}")
else:
    print(f"❌ 漏洞：admin 可修改自己角色: {resp.text[:200]}")
    sys.exit(1)


# 8. admin 尝试传无效角色（应被拒绝）
print(f"\n=== admin 传无效角色 superadmin（应返回 422）===")
resp = requests.patch(
    f"{BASE_URL}/api/auth/users/{new_user_id}/role",
    json={"role": "superadmin"},
    headers=auth_headers(admin_token),
    timeout=15,
)
print(f"Status: {resp.status_code}")
if resp.status_code == 422:
    print(f"✅ 角色合法性校验生效：{resp.json().get('detail', '')}")
else:
    print(f"❌ 漏洞：可设置无效角色: {resp.text[:200]}")
    sys.exit(1)


# 9. 把测试用户改回 user（清理）
print(f"\n=== 清理：把 {unique} 改回 user ===")
resp = requests.patch(
    f"{BASE_URL}/api/auth/users/{new_user_id}/role",
    json={"role": "user"},
    headers=auth_headers(admin_token),
    timeout=15,
)
if resp.status_code == 200:
    print(f"✅ {resp.json()['message']}")


print("\n✅ 全部验证通过")
print("\n=== 总结 ===")
print("1. 注册接口已去掉 role 参数（强制 user），即使传 role=admin 也无效")
print("2. 非 admin 调用 /users 与 /users/{id}/role 返回 403")
print("3. admin 可列出所有用户")
print("4. admin 可提升/降级他人角色")
print("5. admin 不可修改自己角色（防止无人管理）")
print("6. 角色合法性校验（admin/user 之外的角色被拒）")
