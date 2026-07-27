# 日志智能问答系统（Log QA System）

基于 LLM + RAG 的应用运行日志智能问答系统。系统将应用日志经清洗、分块、向量化后存入向量数据库，用户通过自然语言提问，系统混合检索（向量 + BM25）相关日志，由 DeepSeek LLM 基于证据生成结构化回答，并提供来源溯源、质量自检与多轮对话能力。

## 核心能力

- **混合检索**：BGE 向量语义检索 + BM25 关键词检索，RRF 融合重排
- **双路径问答**：RAG 证据链问答（细节查询）+ NL2SQL 直查（聚合统计）
- **来源溯源**：回答中标注 `[1] [2]` 引用，可点击追溯至原始日志
- **流式输出**：SSE 逐字输出，实时响应
- **质量自检**：幻觉检测、分段完整性校验
- **多轮对话**：基于 conversation_id 的历史记忆（最近 5 轮）
- **用户权限**：JWT 认证 + RBAC（user / admin），管理员可管理用户角色
- **审计日志**：关键操作可追溯

## 技术栈

| 层 | 技术 |
|----|------|
| 后端框架 | FastAPI 0.104 + Uvicorn |
| ORM | SQLAlchemy 2.0（SQLite） |
| 认证 | JWT（python-jose） + bcrypt |
| 向量数据库 | Qdrant |
| 嵌入模型 | BAAI/bge-base-zh-v1.5（sentence-transformers + PyTorch CPU） |
| 关键词检索 | rank_bm25 + jieba 中文分词 |
| LLM | DeepSeek API（deepseek-v4-pro / deepseek-v4-flash） |
| 评估框架 | RAGAS 0.2 |
| 前端 | React 19 + Vite 8 + react-router-dom 7 + axios |
| 前端 Lint | Oxlint |

## 系统架构

```
┌──────────────────────────────────────────────────────────────────┐
│                    前端 (React + Vite SPA)                        │
│   Login / Register / Dashboard / UserManagement                   │
│   Chat（SSE 流式） + ConversationSidebar + AuthContext            │
└───────────────────────────────┬──────────────────────────────────┘
                                │ JWT / SSE
┌───────────────────────────────▼──────────────────────────────────┐
│                    后端 (FastAPI)                                 │
│   api/auth.py      注册 / 登录 / 用户管理 / 审计                  │
│   api/qa.py        /ask 同步问答、/ask/stream 流式、反馈、历史     │
└───────────────────────────────┬──────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────┐
│                    问答流水线 (services/)                         │
│   RobustQAPipeline  异常包装 + 重试                               │
│   ├─ 意图路由：RAG (QAPipeline)  vs  NL2SQL (nl2sql.py)           │
│   ├─ 检索：HybridRetriever (向量 + BM25 + RRF)                    │
│   ├─ 生成：DeepSeekClient + PromptTemplates (evidence_chain)      │
│   └─ 校验：QualityChecker（幻觉 / 完整性）                        │
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
│   ├── api/                  # 路由层（auth / qa）
│   ├── core/                 # 配置、数据库、安全
│   ├── models/               # SQLAlchemy 模型
│   ├── schemas/              # Pydantic Schema
│   ├── services/             # 业务核心：检索、LLM、Pipeline、NL2SQL
│   ├── scripts/              # 数据导入、测试、可视化脚本
│   ├── tests/                # pytest 单元测试
│   ├── evaluation/           # RAGAS 评估 + 消融实验
│   │   ├── scripts/          # run_baseline / run_ablation / eval_split
│   │   ├── data/             # 测试集与实验结果 JSON
│   │   └── docs/reports/     # 评估报告
│   ├── data/                 # 原始日志 CSV
│   ├── main.py               # FastAPI 入口
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/              # axios 封装
│   │   ├── components/       # Chat / Sidebar / ProtectedRoute
│   │   ├── pages/            # Login / Register / Dashboard / UserManagement
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
```

### 3. 后端启动

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux / macOS
pip install -r requirements.txt

# 首次运行：导入并向量化日志
python scripts/import_logs.py
python scripts/batch_vectorize.py

# 启动服务
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API 文档访问：http://localhost:8000/docs

### 4. 前端启动

```bash
cd frontend
npm install
npm run dev
```

访问：http://localhost:5173

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/auth/register` | 用户注册（默认 user 角色） |
| POST | `/api/auth/login` | 登录，返回 JWT |
| GET  | `/api/auth/me` | 获取当前用户信息 |
| PATCH | `/api/auth/users/{user_id}/role` | 修改用户角色（仅 admin） |
| GET  | `/api/auth/users` | 用户列表（仅 admin） |
| POST | `/api/qa/ask` | 同步问答 |
| POST | `/api/qa/ask/stream` | SSE 流式问答 |
| GET  | `/api/qa/history` | 问答历史 |
| GET  | `/api/qa/conversations` | 会话列表 |
| GET  | `/api/qa/conversations/{id}` | 会话详情 |
| DELETE | `/api/qa/conversations/{id}` | 删除会话 |
| POST | `/api/qa/feedback` | 点赞 / 点踩反馈 |
| GET  | `/api/qa/feedback/stats` | 反馈统计（支持 scope=me/all） |

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
- 错误响应统一返回 200 + `success=false`，不抛 5xx

## 文档

- [Code Wiki](file:///d:/log-qa-system/docs/CODE_WIKI.md) - 代码百科与架构详解
- [API 文档](file:///d:/log-qa-system/docs/API.md) - 接口规范
- [部署说明](file:///d:/log-qa-system/docs/DEPLOY.md) - 部署指引
- [消融实验汇总](file:///d:/log-qa-system/backend/evaluation/docs/ablation_summary.md) - 实验结论

## 许可

本项目仅用于学习与研究目的。
