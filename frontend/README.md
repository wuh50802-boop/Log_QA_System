# 日志智能问答系统 · 前端

基于 React 19 + Vite 8 的 SPA 前端，配合后端 FastAPI 提供 RAG 日志智能问答服务。

## 功能

- 用户注册 / 登录 / 修改密码（JWT 鉴权）
- SSE 流式问答（逐字输出 + 来源卡片 + 质量自检展示）
- 多轮会话管理（侧边栏切换 / 删除）
- 点赞 / 点踩反馈（覆盖式更新）
- 管理员用户管理界面（角色变更 / 删除用户）
- 路由守卫（ProtectedRoute + AdminRoute）

## 技术栈

| 项 | 版本 |
|----|------|
| React | 19.2 |
| Vite | 8.1 |
| react-router-dom | 7.18 |
| axios | 1.18 |
| Oxlint | 1.71 |

## 目录结构

```
frontend/
├── public/
│   ├── favicon.svg
│   └── icons.svg
├── src/
│   ├── api/
│   │   ├── client.js              # axios 实例 + 拦截器
│   │   ├── auth.js                # 认证 API 封装
│   │   └── qa.js                  # 问答 API 封装（含 SSE 流式）
│   ├── components/
│   │   ├── ProtectedRoute.jsx     # 登录守卫
│   │   ├── AdminRoute.jsx         # admin 角色守卫
│   │   ├── Chat.jsx               # 主聊天界面（SSE + 来源 + 反馈）
│   │   ├── Chat.css
│   │   ├── ConversationSidebar.jsx # 会话列表侧边栏
│   │   ├── ConversationSidebar.css
│   │   ├── ChangePasswordModal.jsx # 修改密码弹窗
│   │   └── ChangePasswordModal.css
│   ├── context/
│   │   └── AuthContext.jsx        # 全局认证 Context
│   ├── pages/
│   │   ├── Login.jsx / Login.css
│   │   ├── Register.jsx
│   │   ├── Dashboard.jsx / Dashboard.css  # 问答工作台
│   │   └── UserManagement.jsx / UserManagement.css  # admin 专属
│   ├── App.jsx                    # 根组件 + 路由
│   ├── App.css
│   ├── index.css
│   └── main.jsx
├── index.html
├── package.json
├── vite.config.js
└── .oxlintrc.json
```

## 路由

| 路径 | 组件 | 守卫 |
|------|------|------|
| `/login` | Login | 公开 |
| `/register` | Register | 公开 |
| `/dashboard` | Dashboard | ProtectedRoute（需登录） |
| `/admin/users` | UserManagement | ProtectedRoute + AdminRoute（需 admin） |
| `/` | 重定向到 `/dashboard` | — |

## 快速开始

### 1. 安装依赖

```bash
cd frontend
npm install
```

### 2. 配置环境变量

在 `frontend/` 下创建 `.env`：

```env
VITE_API_BASE_URL=http://localhost:8000
```

### 3. 启动开发服务器

```bash
npm run dev
```

访问 http://localhost:5173

### 4. 生产构建

```bash
npm run build      # 输出到 dist/
npm run preview    # 本地预览构建产物
```

## 与后端的对接

### API 调用

所有请求通过 [src/api/client.js](file:///d:/log-qa-system/frontend/src/api/client.js) 的 `apiClient` 实例发送：

- `baseURL`：`import.meta.env.VITE_API_BASE_URL`
- 请求拦截器：自动从 `localStorage` 读取 `access_token` 并加 `Authorization: Bearer` 头
- 响应拦截器：401 时清除本地凭证并跳转 `/login`

### SSE 流式问答

[src/api/qa.js](file:///d:/log-qa-system/frontend/src/api/qa.js) 中的 `askStreamQuestion` 使用原生 `fetch` + `ReadableStream` 消费 SSE 事件（浏览器 `EventSource` 不支持 POST + 自定义请求头，故未使用）。

事件序列：

1. `source` - 检索完成，推送来源卡片列表
2. `answer` - 逐字推送答案片段
3. `done` - 流结束，推送 `conversation_id` 与质量自检结果

## 后端接口

详见 [后端 API 文档](file:///d:/log-qa-system/docs/API.md)。

主要端点：

- `POST /api/auth/register` / `login` / `me` / `me/password` / `logout`
- `GET /api/auth/users`（admin） / `PATCH /api/auth/users/{id}/role`（admin） / `DELETE /api/auth/users/{id}`（admin）
- `POST /api/qa/ask` / `ask/stream`
- `GET /api/qa/history` / `conversations` / `conversations/{id}`
- `DELETE /api/qa/conversations/{id}`
- `POST /api/qa/feedback/{qa_id}`
- `GET /api/qa/feedback/stats?scope=me|all`

## 权限约束

- 仅 admin 可访问 `/admin/users` 路由（AdminRoute 守卫）
- 非 admin 用户调用 `scope=all` 接口会被后端自动降级为 `scope=me`
- 注册接口的 role 参数被后端忽略，前端注册固定为 user 角色

## 测试账号

首次使用需先注册账号。如需 admin 权限，注册后由现有 admin 在用户管理界面提权，或直接在数据库执行：

```sql
UPDATE users SET role='admin' WHERE username='your-username';
```

## 相关文档

- [项目总览](file:///d:/log-qa-system/README.md)
- [API 文档](file:///d:/log-qa-system/docs/API.md)
- [部署说明](file:///d:/log-qa-system/docs/DEPLOY.md)
- [Code Wiki](file:///d:/log-qa-system/docs/CODE_WIKI.md)
