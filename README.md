# 日志智能问答系统（Log QA System）

基于 LLM + RAG 的应用运行日志智能问答系统。系统将应用日志经清洗、分块、向量化后存入向量数据库，用户通过自然语言提问，系统混合检索（向量 + BM25）相关日志，由 DeepSeek LLM 基于证据生成结构化回答，并提供来源溯源、质量自检与多轮对话能力。

## 核心能力

- **混合检索**：BGE 向量语义检索 + BM25 关键词检索，RRF 融合重排
- **双路径问答**：RAG 证据链问答（细节查询）+ NL2SQL 直查（聚合统计）
- **来源溯源**：回答中标注 `[1] [2]` 引用，可点击追溯至原始日志
- **流式输出**：SSE 逐字输出，实时响应
- **质量自检**：幻觉检测、分段完整性校验、置信度评分
- **多轮对话**：基于 conversation_id 的历史记忆（最近 5 轮）
- **日志摄入管线**：管理员可上传 CSV/LOG/TXT 文件或生成模拟日志，自动完成解析→清洗→分块→向量化→BM25 索引重建全流程
- **用户权限**：JWT 认证 + RBAC（user / admin），管理员可管理用户角色与日志数据
- **审计日志**：关键操作（角色变更、用户删除、数据摄入）可追溯
- **健壮容错**：RobustQAPipeline 封装重试 + 超时 + 优雅降级，始终返回 HTTP 200

## 技术栈

| 层 | 技术 |
|----|------|
| 后端框架 | FastAPI 0.104 + Uvicorn |
| ORM | SQLAlchemy 2.0（SQLite） |
| 认证 | JWT（python-jose） + bcrypt |
| 向量数据库 | Qdrant（qdrant-client 1.7） |
| 嵌入模型 | BAAI/bge-base-zh-v1.5（sentence-transformers + PyTorch CPU，768 维） |
| 重排序（可选） | BAAI/bge-reranker-base（CrossEncoder，默认未启用） |
| 关键词检索 | rank_bm25 + jieba 中文分词 + NLTK stemming |
| LLM | DeepSeek API（httpx 异步调用，deepseek-v4-pro / deepseek-v4-flash） |
| 数据处理 | pandas + numpy |
| 评估框架 | RAGAS 0.2 |
| 前端 | React 19 + Vite 8 + react-router-dom 7 + axios |
| 前端 Lint | Oxlint |

## 系统架构

```
┌──────────────────────────────────────────────────────────────────┐
│                    前端 (React + Vite SPA)                        │
│   Login / Register / Dashboard / UserManagement / AdminLogs       │
│   Chat（SSE 流式） + ConversationSidebar + AuthContext            │
└───────────────────────────────┬──────────────────────────────────┘
                                │ JWT / SSE
┌───────────────────────────────▼──────────────────────────────────┐
│                    后端 (FastAPI)                                 │
│   api/auth.py      注册 / 登录 / 用户管理 / 审计                  │
│   api/qa.py        /ask 同步问答、/ask/stream 流式、反馈、历史     │
│   api/ingest.py    日志上传 / 模拟生成 / 任务状态（仅 admin）      │
└───────────────────────────────┬──────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────┐
│                    问答流水线 (services/)                         │
│   RobustQAPipeline  异常包装 + 重试 + 降级                        │
│   ├─ 意图路由：RAG (QAPipeline)  vs  NL2SQL (nl2sql.py)           │
│   ├─ 检索：HybridRetriever (向量 + BM25 + RRF)                    │
│   ├─ 生成：DeepSeekClient + PromptTemplates (evidence_chain)      │
│   └─ 校验：QualityChecker（幻觉 / 完整性 / 置信度）               │
├──────────────────────────────────────────────────────────────────┤
│                    摄入管线 (services/)                           │
│   IngestService  解析 → 清洗 → 分块 → 向量化 → BM25重建 → 入库   │
└───────┬───────────────────────────────┬──────────────────────────┘
        │                               │
┌───────▼───────────┐         ┌─────────▼──────────────┐
│  Qdrant 向量库     │         │  SQLite (app.db)        │
│  bge-base-zh-v1.5  │         │  logs / users /         │
│  log_knowledge     │         │  qa_history / audit_log │
└────────────────────┘         └─────────────────────────┘
```

## 目录结构

```
log-qa-system/
├── backend/
│   ├── api/                  # 路由层（auth / qa / ingest）
│   ├── core/                 # 配置、数据库、安全、后台任务
│   ├── models/               # SQLAlchemy 模型（user / log / qa_history / conversation / audit_log）
│   ├── schemas/              # Pydantic Schema
│   ├── services/             # 业务核心：检索、LLM、Pipeline、NL2SQL、摄入管线
│   ├── scripts/              # 数据导入、批量向量化、索引重建、测试脚本
│   ├── tests/                # pytest 单元测试
│   ├── evaluation/           # RAGAS 评估 + 消融实验
│   │   ├── scripts/          # run_baseline / run_ablation / eval_split
│   │   ├── data/             # 测试集与实验结果 JSON
│   │   └── docs/reports/     # 评估报告（A0-A5 / OPT / OPT2）
│   ├── data/                 # 原始日志 CSV / 上传文件
│   ├── datasets/HDFS_v1/     # HDFS 日志数据集（原始 + 预处理）
│   ├── models_cache/         # BGE 嵌入模型本地缓存
│   ├── main.py               # FastAPI 入口
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/              # axios 封装（auth / qa / ingest）
│   │   ├── components/       # Chat / Sidebar / ProtectedRoute / AdminRoute / ChangePasswordModal
│   │   ├── pages/            # Login / Register / Dashboard / UserManagement / AdminLogs
│   │   └── context/          # AuthContext
│   └── package.json
└── docs/                     # API、部署、Code Wiki 文档
```

## 快速开始

### 1. 环境准备

- Python 3.10+
- Node.js 18+
- Qdrant 实例（本地或云端）
- DeepSeek API Key

### 2. 后端配置

在 `backend/` 下创建 `.env`：

```env
# DeepSeek
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro

# Qdrant
QDRANT_URL=https://your-qdrant-cluster
QDRANT_API_KEY=your-qdrant-api-key
QDRANT_COLLECTION_NAME=log_knowledge

# JWT
SECRET_KEY=your-random-secret
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# 日志分块
LOG_CHUNK_SIZE=500
LOG_CHUNK_OVERLAP=50
```

### 3. 后端启动

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
pip install jieba rank_bm25 nltk httpx modelscope  # 补充依赖

# 首次运行：生成模拟日志 → 导入 → 向量化
python scripts/generate_logs.py
python scripts/import_logs.py
python services/batch_vectorize.py --rebuild
# 注：python scripts/batch_vectorize.py ... 仍可用（兼容入口）

# 启动服务
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API 文档访问：http://localhost:8000/docs

### 4. 前端启动

```bash
cd frontend
npm install

# 创建 frontend/.env
echo VITE_API_BASE_URL=http://localhost:8000 > .env

npm run dev
```

访问：http://localhost:5173

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 用户注册（默认 user 角色） |
| POST | `/api/auth/login` | 登录，返回 JWT |
| POST | `/api/auth/logout` | 登出 |
| GET  | `/api/auth/me` | 获取当前用户信息 |
| PATCH | `/api/auth/users/{user_id}/role` | 修改用户角色（仅 admin） |
| PUT  | `/api/auth/users/{user_id}/password` | 修改用户密码（仅 admin） |
| DELETE | `/api/auth/users/{user_id}` | 删除用户（仅 admin） |
| GET  | `/api/auth/users` | 用户列表（仅 admin） |
| POST | `/api/qa/ask` | 同步问答 |
| POST | `/api/qa/ask/stream` | SSE 流式问答 |
| GET  | `/api/qa/history` | 问答历史 |
| GET  | `/api/qa/conversations` | 会话列表 |
| GET  | `/api/qa/conversations/{id}` | 会话详情 |
| DELETE | `/api/qa/conversations/{id}` | 删除会话 |
| POST | `/api/qa/feedback` | 点赞 / 点踩反馈 |
| GET  | `/api/qa/feedback/stats` | 反馈统计（支持 scope=me/all） |
| POST | `/api/ingest/generate` | 生成模拟日志并入库（仅 admin） |
| POST | `/api/ingest/upload` | 上传日志文件并入库（仅 admin，上限 3GB） |
| GET  | `/api/ingest/tasks/{task_id}` | 查询摄入任务状态 |
| GET  | `/api/ingest/tasks` | 列出最近摄入任务 |
| POST | `/api/ingest/tasks/{task_id}/cancel` | 取消运行中的摄入任务（仅 admin） |
| POST | `/api/ingest/rebuild` | 补建向量索引 / 重建 BM25 索引（仅 admin） |
| GET  | `/api/ingest/stats` | 数据库 + 向量库统计 |
| GET  | `/api/ingest/formats` | 支持的日志格式列表 |

所有接口（除注册 / 登录）需在请求头携带：

```
Authorization: Bearer <access_token>
```

## 生产配置

当前线上系统采用 OPT2 最优配置：

- 检索：hybrid（vector_weight=1.0, bm25_weight=2.0，偏 BM25）
- top_k = 5
- Prompt 模板：evidence_chain
- LLM：deepseek-v4-flash
- Embeddings：bge-base-zh-v1.5
- 重排序：未启用（实验证明性价比低）
- 超时：30s

依据消融实验 A4 / OPT2：BM25 在日志检索场景（错误码、服务名、级别等关键词匹配）显著优于纯向量检索；Cross-Encoder 重排序带来 40% 耗时增加但 ctx_prec 反降，不推荐启用。

## 数据模型

SQLite 数据库（`backend/app.db`）包含以下核心表：

| 表 | 说明 | 关键字段 |
|----|------|----------|
| users | 用户账户 | username, password_hash (bcrypt), role (admin/user) |
| logs | 日志条目 | timestamp, level, service, ip, message, trace_id |
| qa_history | 问答记录 | question, answer, sources, conversation_id, quality_check, feedback |
| conversations | 多轮会话 | user_id, title, 关联 qa_history |
| audit_log | 审计日志 | user_id, action, target, detail |

索引策略：logs 表在 level、service、trace_id 上建立单列索引及复合索引，支撑 NL2SQL 聚合查询性能。

## 数据管理

系统支持多种日志数据来源：

- **模拟生成**：通过 `scripts/generate_logs.py` 或管理端 `/api/ingest/generate` 生成合成日志（可指定条数，上限 10 万条）
- **文件上传**：支持 CSV、LOG、TXT 格式（上限 3GB，适配 HDFS Loghub 等大数据集），管理端 `/api/ingest/upload` 或 `scripts/import_logs.py`
- **HDFS 数据集**：`backend/datasets/HDFS_v1/` 包含 HDFS 开源日志数据集（原始 + 预处理），可通过 `scripts/import_hdfs.py` 导入

摄入流程统一为：原始文件 → LogParser 解析 → LogCleaner 清洗 → Chunker 分块（500 字符，50 重叠） → BGE 向量化 → 写入 Qdrant + SQLite → BM25 索引重建。

### 索引补建

当上传时未勾选「入库后向量化」，或向量化阶段失败时，可补建索引：

- **API**：`POST /api/ingest/rebuild`，支持三种模式：
  - `mode=vector` — 增量补建 Qdrant 向量索引（从 `last_log_id` 检查点续传）
  - `mode=bm25` — 从 DB 全量重建 BM25 索引
  - `mode=both` — 两者都做（推荐，单独跑 `vector` 会导致 BM25 索引过时）
- **脚本**：`scripts/rebuild_indexes.py`，参数同上，另支持 `--rebuild-vector`（清空 Qdrant 全量重做，慎用）

> ⚠️ 单独运行 `batch_vectorize` 只补建 Qdrant 向量索引，无法重建 BM25 索引，会导致混合检索的关键词分支无法获取新日志，推荐使用 `rebuild_indexes.py` 或调用 `POST /api/ingest/rebuild`。

## 评估

测试集：`backend/evaluation/data/testset.json`（60 条 QA，覆盖 8 类场景 × 3 档难度）

评估指标（RAG 路径，44 条）：

| 指标 | 含义 |
|------|------|
| faithfulness | 回答是否忠于检索上下文 |
| answer_relevancy | 回答与问题的相关性 |
| context_precision | 检索结果中相关文档的精度 |
| context_recall | 检索结果对参考答案的覆盖度 |

NL2SQL 路径（16 条）使用 SQL 成功率 / 结果非空率评估。

运行评估：

```bash
cd backend
venv\Scripts\activate
python -m evaluation.scripts.run_baseline        # 基线
python -m evaluation.scripts.run_ablation --group all --stratified  # 消融
python -m evaluation.scripts.eval_split          # 分路径评估
```

详细结果见 `backend/evaluation/docs/reports/`。

## 权限与安全约束

- 用户只能访问自己的 QA 历史与反馈数据
- 非 admin 用户使用 `scope=all` 自动降级为 `scope=me`
- 非 admin 用户访问他人会话详情返回 404
- admin 可访问任意会话详情（响应含 owner_username）
- admin 不能修改自己的角色
- 用户不能删除自己；最后一个 admin 不能被删除
- 前端注册固定为 user 角色，注册接口的 role 参数被忽略
- 日志摄入接口仅 admin 可用，上传文件限 .csv / .log / .txt，大小上限 3GB
- 摄入任务支持 task_token 鉴权（7 天有效），非 admin 用户仅可查询自己触发的任务
- 错误响应统一返回 200 + `success=false`，不抛 5xx

## 文档

- [Code Wiki](file:///d:/log-qa-system/docs/CODE_WIKI.md) - 代码百科与架构详解
- [API 文档](file:///d:/log-qa-system/docs/API.md) - 接口规范
- [部署说明](file:///d:/log-qa-system/docs/DEPLOY.md) - 部署指引
- [消融实验汇总](file:///d:/log-qa-system/backend/evaluation/docs/ablation_summary.md) - 实验结论

## 许可

本项目仅用于学习与研究目的。
