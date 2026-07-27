# 日志智能问答系统 API 文档

> 本文档基于实际代码生成，源文件：
> - 认证路由：file:///d:/log-qa-system/backend/api/auth.py
> - 问答路由：file:///d:/log-qa-system/backend/api/qa.py
> - 认证 Schema：file:///d:/log-qa-system/backend/schemas/auth.py
> - 问答 Schema：file:///d:/log-qa-system/backend/schemas/qa.py
> - 应用入口：file:///d:/log-qa-system/backend/main.py
> - 前端 SSE 处理：file:///d:/log-qa-system/frontend/src/api/qa.js

---

## 1. 概述

### 1.1 Base URL

```
http://localhost:8000
```

开发环境前端默认走 Vite 代理（`VITE_API_BASE_URL`），CORS 已放行 `http://localhost:5173`、`http://localhost:5174`、`http://localhost:3000`。

### 1.2 认证方式

JWT Bearer Token。除 `POST /api/auth/register`、`POST /api/auth/login`、系统健康检查接口外，所有接口都需要在请求头携带：

```
Authorization: Bearer <access_token>
```

Token 由 `POST /api/auth/login` 返回，内部载荷为 `{"sub": <username>, "role": <role>}`。

### 1.3 通用响应格式

成功响应体均包含 `success: true` 字段（部分接口直接返回业务对象，如 `GET /`、`GET /health`、`POST /api/auth/logout`、`GET /api/auth/users` 列表字段）。

错误处理分两类：

- **问答主链路（`POST /api/qa/ask`、`POST /api/qa/ask/stream`）**：检索/LLM 异常由 `RobustQAPipeline` 兜底，返回 HTTP 200 + `success=false`（同步）或 SSE `error` 事件（流式），不抛 5xx，保证前端始终拿到可渲染的响应。
- **认证与管理类接口**：使用标准 HTTP 状态码（400 / 401 / 403 / 404 / 422 / 500），响应体为 FastAPI 默认格式 `{"detail": "<错误描述>"}`。

业务校验类错误码约定：

| 状态码 | 含义 | 典型场景 |
|--------|------|----------|
| 400 | 业务约束冲突 | 用户名已存在、改自己角色、删自己、删最后一个 admin、新旧密码相同 |
| 401 | 未认证 / 凭证无效 | 缺失/无效 Token、用户名或密码错误 |
| 403 | 权限不足 | 非 admin 调用管理员接口 |
| 404 | 资源不存在或不属于当前用户 | 历史/会话/用户 ID 不存在或越权访问 |
| 422 | 参数校验失败 | Pydantic 校验失败、非法枚举值（role / feedback） |
| 500 | 服务端异常 | 数据库提交失败等罕见情况 |

---

## 2. 认证接口（`/api/auth`）

### 2.1 POST `/api/auth/register` — 用户注册

- 认证：否
- admin：否
- 权限约束：**注册角色固定为 `user`，请求体中的 `role` 字段（即使传入）会被忽略**。如需 admin，须由已登录的 admin 调用 2.7 提升。

请求体 `RegisterRequest`：

| 字段 | 类型 | 必填 | 约束 | 示例 |
|------|------|------|------|------|
| username | string | 是 | 3-50 字符，唯一 | `"alice"` |
| password | string | 是 | 6-50 字符 | `"alice123"` |

响应 `UserResponse`：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 用户 ID |
| username | string | 用户名 |
| role | string | 角色，注册后固定为 `"user"` |
| created_at | string | 创建时间（ISO 字符串） |

示例：

```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"alice123"}'
```

```json
{
  "id": 12,
  "username": "alice",
  "role": "user",
  "created_at": "2026-07-27T10:00:00"
}
```

错误：用户名已存在 → `400 {"detail": "用户名已存在"}`。

---

### 2.2 POST `/api/auth/login` — 用户登录

- 认证：否
- admin：否
- 权限约束：无

请求体 `LoginRequest`：

| 字段 | 类型 | 必填 | 约束 | 示例 |
|------|------|------|------|------|
| username | string | 是 | 3-50 字符 | `"alice"` |
| password | string | 是 | 6-50 字符 | `"alice123"` |

响应 `TokenResponse`：

| 字段 | 类型 | 说明 |
|------|------|------|
| access_token | string | JWT 访问令牌 |
| token_type | string | 固定 `"bearer"` |
| username | string | 用户名 |
| role | string | 用户角色（`"user"` / `"admin"`） |
| user_id | int | 用户 ID |

示例：

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"alice123"}'
```

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "username": "alice",
  "role": "user",
  "user_id": 12
}
```

错误：用户名或密码错误 → `401 {"detail": "用户名或密码错误"}`（失败尝试会写入审计日志 `login_failed`）。

---

### 2.3 GET `/api/auth/me` — 获取当前用户信息

- 认证：是
- admin：否

请求体：无

响应 `UserResponse`：同 2.1。

示例：

```bash
curl http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer <token>"
```

```json
{
  "id": 12,
  "username": "alice",
  "role": "user",
  "created_at": "2026-07-27T10:00:00"
}
```

---

### 2.4 POST `/api/auth/me/password` — 修改自己的密码

- 认证：是
- admin：否
- 权限约束：只能改自己的密码；必须验证旧密码；新密码不能与旧密码相同。

> 注：实际路径为 `/api/auth/me/password`（非 `/change-password`），见 file:///d:/log-qa-system/backend/api/auth.py:219。

请求体 `ChangePasswordRequest`：

| 字段 | 类型 | 必填 | 约束 | 示例 |
|------|------|------|------|------|
| old_password | string | 是 | 6-50 字符，必须匹配当前密码 | `"alice123"` |
| new_password | string | 是 | 6-50 字符，不能等于 old_password | `"alice456"` |

响应 `ChangePasswordResponse`：

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 是否成功 |
| message | string | 提示信息 |

示例：

```bash
curl -X POST http://localhost:8000/api/auth/me/password \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"old_password":"alice123","new_password":"alice456"}'
```

```json
{
  "success": true,
  "message": "密码修改成功，下次登录请使用新密码"
}
```

错误：旧密码错误 → `400 {"detail": "旧密码错误"}`；新旧密码相同 → `400 {"detail": "新密码不能与旧密码相同"}`。

---

### 2.5 POST `/api/auth/logout` — 用户登出

- 认证：是
- admin：否
- 权限约束：服务端仅记录审计日志，**客户端须自行清除本地 Token**（JWT 无服务端会话）。

请求体：无

响应（非标准 schema，直接返回对象）：

```json
{ "message": "登出成功" }
```

示例：

```bash
curl -X POST http://localhost:8000/api/auth/logout \
  -H "Authorization: Bearer <token>"
```

---

### 2.6 GET `/api/auth/users` — 查询用户列表（仅 admin）

- 认证：是
- admin：**是**（非 admin → `403`）
- 权限约束：仅 admin 可调用；支持按用户名模糊搜索（包含匹配，大小写不敏感）。

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 否 | 按用户名模糊搜索（包含匹配，大小写不敏感） |

响应（直接返回对象）：

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 固定 `true` |
| total | int | 命中数量 |
| items | `UserResponse[]` | 用户列表（按 id 升序） |

示例：

```bash
curl "http://localhost:8000/api/auth/users?username=ali" \
  -H "Authorization: Bearer <admin_token>"
```

```json
{
  "success": true,
  "total": 1,
  "items": [
    { "id": 12, "username": "alice", "role": "user", "created_at": "2026-07-27T10:00:00" }
  ]
}
```

---

### 2.7 PATCH `/api/auth/users/{user_id}/role` — 修改用户角色（仅 admin）

- 认证：是
- admin：**是**
- 权限约束：
  - 非 admin → `403`
  - 目标用户不存在 → `404`
  - **不允许修改自己的角色** → `400`（避免唯一 admin 把自己降级后无人管理）
  - `role` 必须是 `admin` / `user` 之一 → 否则 `422`

路径参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| user_id | int | 被修改用户的 ID |

请求体 `SetRoleRequest`：

| 字段 | 类型 | 必填 | 约束 | 示例 |
|------|------|------|------|------|
| role | string | 是 | `"admin"` 或 `"user"` | `"admin"` |

响应 `SetRoleResponse`：

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 是否成功 |
| user_id | int | 被修改的用户 ID |
| username | string | 被修改的用户名 |
| old_role | string | 修改前角色 |
| new_role | string | 修改后角色 |
| message | string | 提示信息 |

示例：

```bash
curl -X PATCH http://localhost:8000/api/auth/users/12/role \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"role":"admin"}'
```

```json
{
  "success": true,
  "user_id": 12,
  "username": "alice",
  "old_role": "user",
  "new_role": "admin",
  "message": "已将用户 alice 提升为管理员"
}
```

---

### 2.8 DELETE `/api/auth/users/{user_id}` — 删除用户（仅 admin，级联删除）

- 认证：是
- admin：**是**
- 权限约束：
  - 非 admin → `403`
  - **不允许删除自己** → `400`
  - 目标用户不存在 → `404`
  - **不允许删除最后一个 admin** → `400`（避免无人管理系统）
  - 级联删除该用户的全部 `qa_history` 记录；保留 `audit_log` 以便追溯

路径参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| user_id | int | 被删除用户的 ID |

响应 `DeleteUserResponse`：

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 是否成功 |
| user_id | int | 被删除的用户 ID |
| username | string | 被删除的用户名 |
| deleted_qa_count | int | 级联删除的问答记录数 |
| message | string | 提示信息 |

示例：

```bash
curl -X DELETE http://localhost:8000/api/auth/users/12 \
  -H "Authorization: Bearer <admin_token>"
```

```json
{
  "success": true,
  "user_id": 12,
  "username": "alice",
  "deleted_qa_count": 23,
  "message": "已删除用户 alice（同时清理 23 条问答记录）"
}
```

---

## 3. 问答接口（`/api/qa`）

### 3.1 POST `/api/qa/ask` — 同步问答

- 认证：是
- admin：否（所有登录用户可调用）
- 权限约束：问答历史仅写入当前用户名下；意图路由自动判断走 NL2SQL 或 RAG。

请求体 `QARequest`：

| 字段 | 类型 | 必填 | 约束 | 示例 |
|------|------|------|------|------|
| question | string | 是 | 1-500 字符 | `"最近一小时 auth-service 报了哪些 ERROR？"` |
| filters | object | 否 | 检索过滤条件 | `{"level":"ERROR","service":"auth-service"}` |
| top_k | int | 否 | 1-50，默认 5 | `5` |
| template_type | string | 否 | `evidence_chain` / `quick` / `short`，默认 `evidence_chain` | `"evidence_chain"` |
| retriever_type | string | 否 | `vector` / `bm25` / `hybrid`，默认 `hybrid` | `"hybrid"` |
| conversation_id | string | 否 | 已有会话 ID 表示续聊；空则新建 | `"conv_abc123def456"` |

> 多轮对话：服务端自动加载该会话最近 5 轮（10 条消息）作为上下文传给 LLM。传入的 `conversation_id` 若不属于当前用户或不复存在，会被静默新建一个会话（避免打断 UX）。

响应 `QAResponse`：

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 兜底响应时为 `false` |
| question | string | 原始问题 |
| answer | string | 回答（带 `[1] [2]` 来源标注） |
| sources | `QASourceRef[]` | 来源引用列表 |
| confidence | string | 置信度：`高` / `中` / `低` |
| retriever_type | string | 实际使用的检索器（可能为 `nl2sql`） |
| total_tokens | int | LLM token 消耗 |
| retrieval_time | float | 检索耗时（秒） |
| llm_time | float | LLM 调用耗时（秒） |
| total_time | float | 总耗时（秒） |
| qa_id | int \| null | 问答历史记录 ID |
| conversation_id | string \| null | 会话 ID（前端应在续聊时携带） |
| quality_check | `QAQualityCheck` \| null | 回答质量自检结果 |
| error | string \| null | 兜底错误信息（成功时为 `null`） |

`QASourceRef` 结构：

| 字段 | 类型 | 说明 |
|------|------|------|
| ref_id | string | 引用编号，如 `[1]` |
| log_id | int \| null | 日志 ID |
| service | string | 服务名 |
| timestamp | string | 日志时间 |
| level | string | 日志级别 |
| content | string | 日志内容（截断） |
| score | float | 相关性分数 |
| snippet | string | 引用片段 |

`QAQualityCheck` 结构：

| 字段 | 类型 | 说明 |
|------|------|------|
| passed | bool | 是否通过（score ≥ 70 且无 issue） |
| score | float | 0-100，越高越好 |
| issues | `QAQualityIssue[]` | 严重问题（会阻断通过） |
| warnings | string[] | 提示性警告 |
| suggestions | string[] | 改进建议 |

示例：

```bash
curl -X POST http://localhost:8000/api/qa/ask \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "question":"最近 auth-service 有哪些 ERROR？",
    "filters":{"level":"ERROR","service":"auth-service"},
    "top_k":5,
    "retriever_type":"hybrid"
  }'
```

```json
{
  "success": true,
  "question": "最近 auth-service 有哪些 ERROR？",
  "answer": "根据日志 [1][2] ...",
  "sources": [
    {"ref_id":"[1]","log_id":1024,"service":"auth-service","timestamp":"2026-07-27T09:12:00","level":"ERROR","content":"...","score":0.83,"snippet":"..."}
  ],
  "confidence": "中",
  "retriever_type": "hybrid",
  "total_tokens": 820,
  "retrieval_time": 0.312,
  "llm_time": 1.845,
  "total_time": 2.157,
  "qa_id": 88,
  "conversation_id": "conv_3f8a9c1b2d4e5f60",
  "quality_check": {"passed":true,"score":86.0,"issues":[],"warnings":[],"suggestions":[]},
  "error": null
}
```

兜底响应示例（链路异常时）：

```json
{
  "success": false,
  "question": "...",
  "answer": "（兜底提示文案）",
  "sources": [],
  "confidence": "低",
  "retriever_type": "hybrid",
  "total_tokens": 0,
  "retrieval_time": 0.0,
  "llm_time": 0.0,
  "total_time": 0.5,
  "qa_id": null,
  "conversation_id": "conv_xxx",
  "quality_check": null,
  "error": "问答链路异常，已返回兜底响应"
}
```

---

### 3.2 POST `/api/qa/ask/stream` — SSE 流式问答

- 认证：是
- admin：否
- 权限约束：同 3.1。
- Content-Type：`application/json`（请求体同 `QARequest`）
- Accept：`text/event-stream`
- 响应：`StreamingResponse`，`media_type=text/event-stream`，事件序列见第 5 章。

请求体：同 3.1 的 `QARequest`。

事件序列：`source`（检索完成，1 次）→ `answer`（逐字片段，N 次）→ `done`（结束信号，1 次）；异常时为 `error` 事件。

各事件 data 字段：

**`source` 事件**：

| 字段 | 类型 | 说明 |
|------|------|------|
| message | string | 描述文案 |
| sources | `object[]` | 来源引用列表（结构同 `QASourceRef`） |
| retriever_type | string | 检索器类型（可能为 `nl2sql`） |
| sources_count | int | 来源数量 |

**`answer` 事件**：

| 字段 | 类型 | 说明 |
|------|------|------|
| content | string | 本次输出的答案片段（逐字累积） |

**`done` 事件**：

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 固定 `true`（异常已由 `error` 事件单独表达） |
| answer_length | int | 完整答案字符数 |
| sources | `object[]` | 完整来源列表 |
| retriever_type | string | 实际使用的检索器 |
| total_time | float | 总耗时（秒） |
| qa_id | int \| null | 已持久化的历史记录 ID |
| conversation_id | string | 会话 ID |
| quality_check | `QAQualityCheck` \| null | 质量自检结果 |

**`error` 事件**：

| 字段 | 类型 | 说明 |
|------|------|------|
| message | string | 错误描述 |

示例（原始 SSE 文本）：

```
event: source
data: {"message":"检索完成","sources":[{"ref_id":"[1]","service":"auth-service",...}],"retriever_type":"hybrid","sources_count":3}

event: answer
data: {"content":"根据"}

event: answer
data: {"content":"日志 [1] "}

event: done
data: {"success":true,"answer_length":420,"sources":[...],"retriever_type":"hybrid","total_time":2.34,"qa_id":89,"conversation_id":"conv_xxx","quality_check":{...}}
```

curl 示例（需手动观察原始流）：

```bash
curl -N -X POST http://localhost:8000/api/qa/ask/stream \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"question":"最近有哪些 ERROR？","top_k":5}'
```

---

### 3.3 GET `/api/qa/history` — 查询问答历史列表

- 认证：是
- admin：否（所有登录用户可查自己的历史）
- 权限约束：**只返回当前登录用户自己的历史记录**。

查询参数：

| 参数 | 类型 | 必填 | 约束 | 说明 |
|------|------|------|------|------|
| page | int | 否 | ≥ 1，默认 1 | 页码 |
| page_size | int | 否 | 1-100，默认 20 | 每页数量 |
| keyword | string | 否 | - | 在问题和回答中模糊搜索 |
| feedback | string | 否 | `like` / `dislike` / `none` | 按反馈过滤 |

响应 `QAHistoryListResponse`：

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 固定 `true` |
| total | int | 符合过滤条件的总数 |
| page | int | 当前页码 |
| page_size | int | 每页大小 |
| total_pages | int | 总页数 |
| items | `QAHistoryItem[]` | 历史列表（按时间倒序） |

`QAHistoryItem` 结构：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 历史记录 ID |
| question | string | 用户问题 |
| answer | string | 系统回答 |
| sources | `object[]` \| null | 引用来源列表 |
| feedback | string | `like` / `dislike` / `none` |
| created_at | string | 提问时间（ISO） |

示例：

```bash
curl "http://localhost:8000/api/qa/history?page=1&page_size=20&feedback=dislike" \
  -H "Authorization: Bearer <token>"
```

错误：非法 `feedback` 值 → `422`。

---

### 3.4 GET `/api/qa/history/{history_id}` — 查询历史详情

- 认证：是
- admin：否
- 权限约束：只能查自己的记录；记录不存在或不属于当前用户 → `404`。

路径参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| history_id | int | 历史记录 ID |

响应 `QAHistoryDetailResponse`：

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 固定 `true` |
| id | int | 历史记录 ID |
| question | string | 用户问题 |
| answer | string | 系统回答 |
| sources | `object[]` \| null | 引用来源列表 |
| feedback | string | 反馈状态 |
| created_at | string | 提问时间 |
| username | string | 提问用户名（始终为当前用户） |
| quality_check | `object` \| null | 质量自检结果（含 passed/score/issues/warnings/suggestions） |

示例：

```bash
curl http://localhost:8000/api/qa/history/88 \
  -H "Authorization: Bearer <token>"
```

---

### 3.5 GET `/api/qa/conversations` — 查询会话列表

- 认证：是
- admin：否（scope=all 仅 admin 可用，非 admin 会被降级为 scope=me）
- 权限约束：
  - `scope=me`（默认）：仅当前用户自己的会话
  - `scope=all`：全平台所有用户的会话，**仅 admin 可选**；非 admin 传 `all` 会被静默降级为 `me`（不报错）

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| scope | string | 否 | `me`（默认） / `all`（仅 admin） |

响应 `ConversationListResponse`：

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 固定 `true` |
| total | int | 会话总数 |
| items | `ConversationItem[]` | 会话列表（按最近更新倒序） |

`ConversationItem` 结构：

| 字段 | 类型 | 说明 |
|------|------|------|
| conversation_id | string | 会话 ID |
| title | string | 会话标题（取首条问题，截断 60 字符） |
| message_count | int | 该会话的问答轮数 |
| last_question | string | 最近一次提问（截断 60 字符，用于预览） |
| created_at | string | 首条记录时间（ISO） |
| updated_at | string | 最近记录时间（ISO） |

示例：

```bash
curl "http://localhost:8000/api/qa/conversations?scope=me" \
  -H "Authorization: Bearer <token>"
```

---

### 3.6 GET `/api/qa/conversations/{conversation_id}` — 查询会话详情

- 认证：是
- admin：否（但 admin 拥有越权查看能力）
- 权限约束：
  - **普通用户**：只能查自己的会话；会话不存在或不属于自己 → `404`（不暴露他人会话存在性）
  - **admin**：可查任意用户的会话（用于从反馈统计/审计跳转查看上下文），响应中额外返回 `owner_username`

路径参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| conversation_id | string | 会话 ID |

响应 `ConversationDetailResponse`：

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 固定 `true` |
| conversation_id | string | 会话 ID |
| title | string | 会话标题（首条问题，截断 60 字符） |
| message_count | int | 问答轮数 |
| items | `ConversationMessageItem[]` | 全部 Q&A（按时间正序） |
| owner_username | string | 会话所有者用户名（admin 查他人会话时返回，普通用户为空串） |

`ConversationMessageItem` 结构：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 问答历史记录 ID |
| question | string | 用户问题 |
| answer | string | 系统回答 |
| sources | `object[]` \| null | 引用来源列表 |
| feedback | string | 反馈状态 |
| created_at | string | 提问时间 |
| quality_check | `object` \| null | 质量自检结果 |

示例：

```bash
curl http://localhost:8000/api/qa/conversations/conv_3f8a9c1b2d4e5f60 \
  -H "Authorization: Bearer <token>"
```

---

### 3.7 DELETE `/api/qa/conversations/{conversation_id}` — 删除会话

- 认证：是
- admin：否
- 权限约束：**只能删除自己的会话**；会话不存在或不属于当前用户 → `404`；删除后不可恢复，连同该会话下全部问答记录一并删除。

路径参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| conversation_id | string | 会话 ID |

响应 `ConversationDeleteResponse`：

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 固定 `true` |
| conversation_id | string | 被删除的会话 ID |
| deleted_count | int | 删除的问答记录数 |
| message | string | 提示信息 |

示例：

```bash
curl -X DELETE http://localhost:8000/api/qa/conversations/conv_3f8a9c1b2d4e5f60 \
  -H "Authorization: Bearer <token>"
```

---

### 3.8 POST `/api/qa/feedback/{qa_id}` — 提交问答反馈

- 认证：是
- admin：否
- 权限约束：只能对自己的问答记录反馈；记录不存在或不属于当前用户 → `404`；**重复反馈会覆盖上一次的值（覆盖式更新）**。

> 注：实际路径为 `/api/qa/feedback/{qa_id}`（`qa_id` 是路径参数），见 file:///d:/log-qa-system/backend/api/qa.py:649。

路径参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| qa_id | int | 问答历史记录 ID |

请求体 `FeedbackRequest`：

| 字段 | 类型 | 必填 | 约束 | 示例 |
|------|------|------|------|------|
| feedback | string | 是 | `like` / `dislike` / `none`（`none` 表示取消反馈） | `"like"` |

响应 `FeedbackResponse`：

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 固定 `true` |
| qa_id | int | 问答历史记录 ID |
| feedback | string | 当前反馈状态 |
| message | string | 提示信息 |

示例：

```bash
curl -X POST http://localhost:8000/api/qa/feedback/88 \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"feedback":"like"}'
```

```json
{
  "success": true,
  "qa_id": 88,
  "feedback": "like",
  "message": "已点赞问答记录 88"
}
```

错误：非法 `feedback` 值 → `422`。

---

### 3.9 GET `/api/qa/feedback/stats` — 反馈统计

- 认证：是
- admin：否（scope=all 仅 admin 可用，非 admin 自动降级为 me）
- 权限约束：
  - `scope=me`（默认）：仅统计当前用户自己的数据，所有用户可用
  - `scope=all`：统计全平台数据，**仅 admin 可选**；非 admin 传 `all` 会被强制降级为 `me`（响应中的 `scope` 字段回填实际生效值，便于前端识别）

查询参数：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| scope | string | 否 | `me`（默认） / `all`（仅 admin） |

响应 `FeedbackStatsResponse`：

| 字段 | 类型 | 说明 |
|------|------|------|
| success | bool | 固定 `true` |
| scope | string | 实际生效的统计范围（`me` / `all`） |
| total_qa | int | 统计范围内的总问答数 |
| total_likes | int | 总点赞数 |
| total_dislikes | int | 总点踩数 |
| total_no_feedback | int | 未反馈数 |
| like_rate | float | 好评率 = likes / (likes + dislikes)，0-1 之间 |
| top_disliked | `FeedbackStatsItem[]` | 差评问题列表（按时间倒序，最多 10 条） |

`FeedbackStatsItem` 结构：

| 字段 | 类型 | 说明 |
|------|------|------|
| qa_id | int | 问答记录 ID |
| question | string | 用户问题 |
| answer | string | 系统回答（截断 200 字符） |
| feedback | string | 固定 `"dislike"` |
| created_at | string | 提问时间 |
| conversation_id | string \| null | 所属会话 ID（前端可据此跳回原会话查看完整上下文） |
| username | string | 提问用户名（scope=all 时返回，便于 admin 识别来源） |

示例：

```bash
curl "http://localhost:8000/api/qa/feedback/stats?scope=all" \
  -H "Authorization: Bearer <admin_token>"
```

---

## 4. 系统接口

### 4.1 GET `/` — 根路径健康检查

- 认证：否
- admin：否

响应：

```json
{ "message": "日志智能问答系统运行中", "status": "healthy" }
```

---

### 4.2 GET `/health` — 健康检查

- 认证：否
- admin：否
- 用途：轻量级探针，适合负载均衡 / 容器 liveness/readiness。

响应：

```json
{ "status": "healthy" }
```

---

## 5. SSE 流式响应说明

### 5.1 事件类型

| 事件 | 次数 | data 关键字段 | 含义 |
|------|------|---------------|------|
| `source` | 1 | `sources`, `retriever_type`, `sources_count` | 检索完成，前端可先渲染来源卡片 |
| `answer` | N | `content` | 答案逐字片段，前端应累积拼接到消息流 |
| `done` | 1 | `answer_length`, `sources`, `qa_id`, `conversation_id`, `quality_check`, `total_time` | 流结束信号，包含完整元信息 |
| `error` | 0/1 | `message` | 异常事件，前端应中止解析并提示 |

事件序列：`source` → `answer` × N → `done`；异常路径下可能直接 `error`。

### 5.2 防缓冲响应头

服务端在 `StreamingResponse` 上显式设置（见 file:///d:/log-qa-system/backend/api/qa.py:488）：

| 响应头 | 值 | 作用 |
|--------|----|------|
| `Content-Type` | `text/event-stream` | SSE 标准 MIME |
| `Cache-Control` | `no-cache` | 禁用客户端缓存 |
| `Connection` | `keep-alive` | 保持长连接 |
| `X-Accel-Buffering` | `no` | **禁用 nginx 反向代理缓冲**，确保逐字输出（关键） |

每个 SSE 事件按规范以空行（`\n\n`）分隔，单事件格式：

```
event: <type>
data: <json>

```

### 5.3 前端处理逻辑

前端位于 file:///d:/log-qa-system/frontend/src/api/qa.js，导出 `askStreamQuestion(params, handlers)`，回调签名：

- `onSource(data)` — 检索完成
- `onAnswer(data)` — 逐字输出，`data.content` 为本次片段
- `onDone(data)` — 流结束（含 `conversation_id`，前端应缓存以维持多轮上下文）
- `onError(data)` — 异常

实现要点：

1. **不使用浏览器原生 `EventSource`**：因为 `EventSource` 仅支持 GET 请求且无法自定义请求头（无法携带 `Authorization`），改用 `fetch` + `ReadableStream` 手动解析。
2. 请求头携带 `Accept: text/event-stream` 与 `Authorization: Bearer <token>`，请求体同 `QARequest`。
3. 通过 `response.body.getReader()` 逐 chunk 读取，`TextDecoder` 解码后追加到 buffer。
4. 按 `\n\n` 切分事件块，最后一段可能不完整 → 保留到下次循环（流式分块边界处理）。
5. 每个事件块用 `_parseSseEvent` 解析：以 `event: ` 前缀取类型，以 `data: ` 前缀取数据，`JSON.parse` 后分发到对应回调。
6. 收到 `done` 或 `error` 事件后立即 `return`，结束读取循环。

---

## 6. 权限与安全约束

以下硬约束来自 file:///d:/log-qa-system/backend/api/auth.py 与 file:///d:/log-qa-system/backend/api/qa.py：

1. **用户只能访问自己的 QA 历史和反馈数据**
   - `GET /api/qa/history`、`GET /api/qa/history/{id}`、`POST /api/qa/feedback/{qa_id}` 均按 `current_user.id` 过滤；越权访问统一返回 `404`（不暴露存在性）。

2. **非 admin 用户使用 `scope=all` 自动降级为 `scope=me`**
   - 涉及 `GET /api/qa/conversations` 和 `GET /api/qa/feedback/stats`；不报错，响应中 `scope` 字段回填实际生效值。

3. **非 admin 用户访问他人会话详情返回 `404`**
   - `GET /api/qa/conversations/{id}` 对普通用户加 `user_id` 过滤；admin 不加过滤，可查任意会话。

4. **admin 可访问任意会话详情（响应含 `owner_username`）**
   - 用于从反馈统计/审计跳转查看上下文，便于识别"查看中：xxx 的会话"。

5. **admin 不能修改自己的角色**
   - `PATCH /api/auth/users/{user_id}/role` 校验 `target.id == current_user.id` → `400`，避免唯一 admin 把自己降级后无人管理。

6. **用户不能删除自己；最后一个 admin 不能被删除**
   - `DELETE /api/auth/users/{user_id}` 校验：删自己 → `400`；目标为 admin 且 admin 总数 ≤ 1 → `400`。

7. **前端注册固定为 `user` 角色，注册接口的 `role` 参数被忽略**
   - `POST /api/auth/register` 内部强制 `role=UserRole.USER`，即使请求体含 `role` 字段也不生效；如需 admin 须由已登录 admin 调用 2.7 提升。

8. **问答主链路错误统一返回 200 + `success=false`，不抛 5xx**
   - `POST /api/qa/ask` 与 `POST /api/qa/ask/stream` 由 `RobustQAPipeline` 兜底：LLM 超时 / Qdrant 故障时自动重试，重试仍失败则返回带友好提示的结果（`confidence="低"`、`sources=[]`、`success=false`、`error="问答链路异常，已返回兜底响应"`），保证前端始终拿到可渲染的响应。流式接口通过 `error` 事件表达异常。
   - 注意：**认证与管理类接口**（注册、登录、改角色、删用户等）仍使用标准 HTTP 4xx/5xx 状态码，详见第 1.3 节。

---

## 7. 生产配置说明

### 7.1 检索与生成配置（OPT2 最优配置）

RAG 路径默认采用 OPT2 实验最优配置，见 file:///d:/log-qa-system/backend/api/qa.py:81（`_build_pipeline`）：

| 配置项 | 值 | 说明 |
|--------|----|------|
| retriever_type | `hybrid` | 向量 + BM25 混合检索，RRF 融合 |
| vector_weight | `1.0` | 向量检索权重 |
| bm25_weight | `2.0` | BM25 权重（偏 BM25，日志场景关键词匹配更重要） |
| top_k | `5` | 检索返回的日志条数（请求体可覆盖，1-50） |
| template_type | `evidence_chain` | 证据链 Prompt 模板（结构化五段式回答） |

> 选型依据：消融实验 A4/OPT 证明偏 BM25 在日志检索场景下 `ctx_prec` / `ans_rel` 更优——错误码、服务名、级别等关键词对精确检索更重要。

### 7.2 LLM 配置

- 提供方：DeepSeek
- Base URL：`https://api.deepseek.com/v1`（可通过 `DEEPSEEK_BASE_URL` 环境变量覆盖）
- 模型：`deepseek-v4-flash`（可通过 `DEEPSEEK_MODEL` 环境变量覆盖）
- 配置源：file:///d:/log-qa-system/backend/services/llm_client.py:23

### 7.3 意图路由

问答接口在执行前先做意图判断（见 file:///d:/log-qa-system/backend/api/qa.py:193 与 file:///d:/log-qa-system/backend/api/qa.py:356）：

- **聚合 / 统计类问题**（如"过去一小时有多少条 ERROR"、"哪个服务报错最多"）→ 走 **NL2SQL** 路径，直接查 `logs` 表，响应中 `retriever_type` 为 `"nl2sql"`，`sources` 为空。
- **其他问题**（错误诊断、服务健康、用户活动等）→ 走 **RAG** 检索路径（向量 / BM25 / hybrid + LLM 生成）。

两条路径共用 `QAResponse` / SSE 事件协议，前端无需区分处理。
