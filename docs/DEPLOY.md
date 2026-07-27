# 日志智能问答系统 部署文档

本文档描述日志智能问答系统（前端 React + 后端 FastAPI + Qdrant 向量库）的完整部署流程。

---

## 1. 环境要求

| 依赖 | 最低版本 | 说明 |
| --- | --- | --- |
| Python | 3.10+ | 后端运行时 |
| Node.js | 18+ | 前端构建 |
| Qdrant | 1.7+ | 向量数据库，本地 Docker 或 Qdrant Cloud |
| DeepSeek API Key | - | LLM 生成服务 |
| 磁盘空间 | 约 2GB | 模型缓存 + 向量库 + SQLite 数据库 |

操作系统支持 Windows / Linux / macOS，下文命令会分别给出差异。

---

## 2. 后端部署

### 2.1 创建虚拟环境并安装依赖

```bash
cd backend
python -m venv venv
```

激活虚拟环境：

```bash
# Windows (PowerShell)
venv\Scripts\Activate.ps1
# Windows (cmd)
venv\Scripts\activate.bat
# Linux / macOS
source venv/bin/activate
```

安装 requirements.txt 中的依赖：

```bash
pip install -r requirements.txt
```

手动安装 requirements.txt 中未列出但代码实际使用的依赖：

```bash
pip install jieba rank_bm25 nltk httpx modelscope ragas
```

说明：
- `jieba`：中文分词（BM25 检索器使用）
- `rank_bm25`：BM25 算法实现
- `nltk`：英文词干提取（PorterStemmer）
- `httpx`：异步 HTTP 客户端
- `modelscope`：BGE 模型下载源
- `ragas`：RAG 评估（可选，用于离线评测）

### 2.2 配置 .env 文件

在 `backend/` 目录下创建 `.env` 文件：

```env
# ===== DeepSeek 配置 =====
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro

# ===== Qdrant 配置 =====
QDRANT_URL=https://your-qdrant-cluster
QDRANT_API_KEY=your-qdrant-api-key
QDRANT_COLLECTION_NAME=log_knowledge

# ===== JWT 配置 =====
SECRET_KEY=your-random-secret
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# ===== 切片配置 =====
LOG_CHUNK_SIZE=500
LOG_CHUNK_OVERLAP=50
```

字段说明：
- `DEEPSEEK_MODEL`：默认 `deepseek-v4-pro`，限流场景可改为 `deepseek-v4-flash`。注意：旧名 `deepseek-chat` 已废弃。
- `QDRANT_COLLECTION_NAME`：默认 `log_knowledge`，需与向量化脚本保持一致。
- `SECRET_KEY`：JWT 签名密钥，生产环境务必替换为强随机串，前后端实例需保持一致。
- `LOG_CHUNK_SIZE` / `LOG_CHUNK_OVERLAP`：日志切片字符数与重叠量，默认 500 / 50。

配置检查：后端启动时会调用 `Settings.check_config()` 校验 `DEEPSEEK_API_KEY`、`QDRANT_URL`、`QDRANT_API_KEY` 是否填写，缺失会在控制台告警。

### 2.3 数据初始化

按顺序执行（工作目录为 `backend/`）：

```bash
# 1. 生成测试日志数据
python scripts/generate_logs.py

# 2. 导入 SQLite 数据库
python scripts/import_logs.py

# 3. 向量化并写入 Qdrant（--rebuild 会重建 collection）
python scripts/batch_vectorize.py --rebuild
```

首次运行注意事项：
- `jieba` 首次调用会自动加载词典，耗时约 1-2 秒。
- `NLTK` 首次调用会自动下载 `punkt` 和 `stopwords` 数据集到 `~/nltk_data/`。
- BGE 模型首次会从 ModelScope 下载（约 200MB），缓存到 `backend/models_cache/`。
- `batch_vectorize.py` 支持断点续传，进度记录在 `backend/vectorize_checkpoint.json`。

### 2.4 启动后端

```bash
# 开发模式（热重载）
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

启动后访问：
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health
- 根路径：http://localhost:8000/

启动流程（`main.py` lifespan）：
1. `init_db()` 初始化 SQLite 表结构（幂等）
2. `warmup()` 系统预热，依次加载：
   - jieba 词典
   - BGE 嵌入模型（`BAAI/bge-base-zh-v1.5`）
   - BM25 索引（从 `bm25_index.pkl` 加载）
   - Qdrant 连接（执行 `count()` 探活）
   - 混合检索器初始化

CORS 已允许 `http://localhost:5173`、`http://localhost:5174`、`http://localhost:3000` 三个前端来源。

---

## 3. 前端部署

### 3.1 安装依赖

```bash
cd frontend
npm install
```

主要依赖：React 19、react-router-dom 7、axios；构建工具 Vite 8，linter oxlint。

### 3.2 配置 .env

在 `frontend/` 目录下创建 `.env` 文件：

```env
VITE_API_BASE_URL=http://localhost:8000
```

生产环境替换为后端公网地址或反向代理地址。

### 3.3 启动开发服务器

```bash
npm run dev
```

访问 http://localhost:5173

### 3.4 生产构建

```bash
# 构建产物输出到 dist/
npm run build

# 本地预览构建产物
npm run preview
```

代码规范检查：

```bash
npm run lint
```

---

## 4. Qdrant 部署

### 4.1 Docker 部署（本地开发推荐）

Linux / macOS：

```bash
docker run -d --name qdrant \
  -p 6333:6333 -p 6334:6334 \
  -v $(pwd)/qdrant_data:/qdrant/storage \
  qdrant/qdrant
```

Windows (PowerShell)：

```powershell
docker run -d --name qdrant `
  -p 6333:6333 -p 6334:6334 `
  -v ${PWD}/qdrant_data:/qdrant/storage `
  qdrant/qdrant
```

端口说明：
- 6333：HTTP REST API
- 6334：gRPC（可选）

本地部署时 `.env` 配置：
```env
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
```

### 4.2 Qdrant Cloud（生产推荐）

1. 注册 https://qdrant.cloud
2. 创建集群，获取 Cluster URL 和 API Key
3. 填入 `backend/.env` 的 `QDRANT_URL` 和 `QDRANT_API_KEY`

### 4.3 Collection 配置

| 配置项 | 值 |
| --- | --- |
| 名称 | `log_knowledge`（与 `.env` 一致） |
| 向量维度 | 768（BGE bge-base-zh-v1.5） |
| 距离度量 | Cosine |
| HNSW 索引 | m=16, ef_construct=100 |

Payload 字段（建议建索引）：`log_id`、`level`、`service`、`timestamp`、`chunk_text`、`source`。

首次运行 `python scripts/batch_vectorize.py --rebuild` 会自动创建 collection 并写入向量，无需手动建表。

---

## 5. 生产环境配置

### 5.1 后端生产启动

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

注意：使用 `--workers > 1` 时，每个 worker 会独立加载一份 BGE 模型（约 500MB 内存 / worker），并各自构建 BM25 索引。建议单 worker + 反向代理水平扩展多实例，每个实例绑定不同端口。

### 5.2 反向代理（Nginx 示例）

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 前端静态资源
    location / {
        root /path/to/frontend/dist;
        try_files $uri $uri/ /index.html;
    }

    # 后端 API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 5.3 SSE 流式响应配置

问答接口使用 SSE 流式输出，Nginx 必须关闭缓冲，否则会出现响应延迟或截断：

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_buffering off;
    proxy_cache off;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_read_timeout 300s;
}
```

### 5.4 当前生产配置（OPT2 最优）

| 维度 | 配置 |
| --- | --- |
| 检索策略 | hybrid（向量 + BM25 混合） |
| 向量权重 | 1.0 |
| BM25 权重 | 2.0（偏 BM25） |
| top_k | 5 |
| Prompt 模板 | evidence_chain |
| LLM | deepseek-v4-flash |
| Embeddings | bge-base-zh-v1.5 |
| 重排序 | 未启用（实验证明性价比低） |
| 意图路由 | 聚合类查询走 NL2SQL，其余走 RAG |

---

## 6. 常见问题

### 6.1 BGE 模型下载失败

现象：`snapshot_download` 报错或卡住。
解决：
- 配置 ModelScope 镜像源
- 或手动下载 `AI-ModelScope/bge-base-zh-v1.5` 模型文件，放入 `backend/models_cache/models/AI-ModelScope--bge-base-zh-v1.5/snapshots/master/`，确保目录下包含 `config.json`

### 6.2 Qdrant 连接失败

现象：启动时 `Qdrant 连接失败` 警告。
排查：
- 检查 `QDRANT_URL` 和 `QDRANT_API_KEY` 是否正确
- 检查网络 / 防火墙是否放行 6333 端口
- 本地 Docker 部署确认容器在运行：`docker ps | grep qdrant`

### 6.3 DeepSeek API 限流

现象：HTTP 429 或响应缓慢。
解决：
- 调低并发参数 `QA_CONCURRENCY`
- 在 `.env` 中将 `DEEPSEEK_MODEL` 改为 `deepseek-v4-flash`（限流更宽松、成本更低）

### 6.4 NLTK 数据下载失败

现象：`LookupError: Resource punkt not found` 或下载超时。
解决：手动下载 `punkt` 和 `stopwords`，放入 `~/nltk_data/`（Windows 为 `%USERPROFILE%\nltk_data\`）。

### 6.5 SQLite 锁定

现象：`database is locked` 错误。
说明：单机部署 SQLite 足够；高并发写入场景建议改用 PostgreSQL，需调整 `core/database.py` 连接串。

### 6.6 前端 401 循环

现象：登录后接口持续返回 401，页面反复跳转登录。
排查：
- 检查 JWT 是否已过期（默认 30 分钟）
- 确认后端 `SECRET_KEY` 与签发时一致（多实例部署时尤其重要）
- 确认请求头携带 `Authorization: Bearer <token>`

### 6.7 模型名 'deepseek-chat' 已废弃

旧名 `deepseek-chat` 已不可用，请使用：
- `deepseek-v4-pro`：高质量，成本较高
- `deepseek-v4-flash`：快速，限流宽松，成本较低

---

## 7. 测试账号

系统无内置管理员账号，首次启动需手动创建：

1. 注册账号（注册接口固定写入 `role='user'`）：
   ```bash
   POST /api/auth/register
   Content-Type: application/json

   {
     "username": "admin",
     "password": "your-password"
   }
   ```

2. 提升为管理员（任选其一）：
   - 直接 SQL：
     ```sql
     UPDATE users SET role='admin' WHERE username='admin';
     ```
   - 使用 SQLite 命令行：
     ```bash
     sqlite3 backend/app.db "UPDATE users SET role='admin' WHERE username='admin';"
     ```

3. 使用 admin 账号登录获取 JWT Token。

---

## 8. 目录结构说明

| 路径 | 说明 | 生成时机 |
| --- | --- | --- |
| `backend/app.db` | SQLite 数据库 | 首次启动后端时生成 |
| `backend/models_cache/` | BGE 模型缓存 | 首次加载 BGE 时生成（约 200MB） |
| `backend/bm25_index.pkl` | BM25 索引缓存 | 首次构建 BM25 索引时生成 |
| `backend/vectorize_checkpoint.json` | 向量化断点续传记录 | 运行 `batch_vectorize.py` 时生成 |
| `frontend/dist/` | 前端构建产物 | 执行 `npm run build` 后生成 |
| `backend/.env` | 后端环境变量 | 手动创建 |
| `frontend/.env` | 前端环境变量 | 手动创建 |
| `qdrant_data/`（Docker 挂载） | Qdrant 数据持久化 | Docker 启动时生成 |

---

## 附：快速启动检查清单

- [ ] Python 3.10+ / Node.js 18+ 已安装
- [ ] `backend/.env` 已填写真实 DeepSeek / Qdrant 配置
- [ ] `backend/requirements.txt` + 手动依赖已安装
- [ ] Qdrant 实例可访问（本地或云端）
- [ ] `python scripts/generate_logs.py` 已执行
- [ ] `python scripts/import_logs.py` 已执行
- [ ] `python scripts/batch_vectorize.py --rebuild` 已执行
- [ ] `frontend/.env` 已配置 `VITE_API_BASE_URL`
- [ ] 后端 `uvicorn main:app` 启动后 `/health` 返回 healthy
- [ ] 前端 `npm run dev` 启动后可访问 http://localhost:5173
- [ ] 已注册并提权 admin 账号
