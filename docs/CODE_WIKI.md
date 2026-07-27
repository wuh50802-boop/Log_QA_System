  # 日志智能问答系统 · Code Wiki

> 本文档是对 `log-qa-system` 项目仓库的结构化代码百科，涵盖项目整体架构、主要模块职责、关键类与函数说明、依赖关系以及项目运行方式等关键信息。
>
> 文档基于代码库静态分析生成，反映截至 2026-07-27 的代码状态。

---

## 目录

- [1. 项目概述](#1-项目概述)
- [2. 系统整体架构](#2-系统整体架构)
- [3. 目录结构](#3-目录结构)
- [4. 技术栈与依赖](#4-技术栈与依赖)
- [5. 后端模块详解](#5-后端模块详解)
  - [5.1 应用入口 main.py](#51-应用入口-mainpy)
  - [5.2 核心配置层 core/](#52-核心配置层-core)
  - [5.3 数据模型层 models/](#53-数据模型层-models)
  - [5.4 Pydantic Schema 层 schemas/](#54-pydantic-schema-层-schemas)
  - [5.5 API 路由层 api/](#55-api-路由层-api)
  - [5.6 服务层 services/（核心业务逻辑）](#56-服务层-services核心业务逻辑)
  - [5.7 脚本层 scripts/](#57-脚本层-scripts)
  - [5.8 评估模块 evaluation/](#58-评估模块-evaluation)
  - [5.9 测试层 tests/](#59-测试层-tests)
  - [5.10 工具层 utils/](#510-工具层-utils)
  - [5.11 数据文件 data/](#511-数据文件-data)
- [6. 前端模块详解](#6-前端模块详解)
- [7. 核心数据流与处理流程](#7-核心数据流与处理流程)
- [8. 关键类与函数索引](#8-关键类与函数索引)
- [9. 依赖关系总览](#9-依赖关系总览)
- [10. 项目运行方式](#10-项目运行方式)
- [11. 环境变量配置](#11-环境变量配置)
- [12. 已知问题与注意事项](#12-已知问题与注意事项)

---

## 1. 项目概述

**项目名称**：日志智能问答系统（Log QA System）

**项目定位**：基于 LLM（DeepSeek）+ RAG（检索增强生成）的应用运行日志智能问答系统。系统将应用日志经清洗、分块、向量化后存入向量数据库，用户可通过自然语言提问，系统混合检索（向量 + BM25）相关日志，再由 LLM 基于证据生成结构化回答，并提供来源溯源与质量自检能力。

**核心能力**：
- 用户认证与授权（JWT + RBAC，含管理员用户管理、改密）
- 日志数据解析、清洗、分块、向量化入库
- 混合检索（向量语义检索 + BM25 关键词检索 + RRF 融合重排）
- 聚合统计类问题走 NL2SQL 路径（意图识别 + LLM 生成 SQL + 安全校验 + 只读执行）
- Cross-Encoder 重排序（bge-reranker-base，可选精排）
- 基于 DeepSeek LLM 的证据链问答（含 SSE 流式输出）
- 多轮对话（DB conversation_id 持久化）、来源溯源、回答质量自检、统一异常处理
- 问答历史、会话管理、点赞/点踩反馈与统计、审计日志记录
- RAGAS 评估框架与消融实验（backend/evaluation/）

**技术栈速览**：

| 层 | 技术 |
|----|------|
| 后端框架 | FastAPI 0.104 + Uvicorn |
| ORM | SQLAlchemy 2.0（SQLite） |
| 认证 | JWT（python-jose） + bcrypt（passlib） |
| 向量数据库 | Qdrant（qdrant-client 1.7） |
| 嵌入模型 | BAAI/bge-base-zh-v1.5（sentence-transformers + PyTorch CPU） |
| 重排序模型 | BAAI/bge-reranker-base（CrossEncoder，可选） |
| 关键词检索 | rank_bm25（BM25Okapi） + jieba 中文分词 + NLTK 词干 |
| LLM | DeepSeek API（httpx 同步/流式） |
| 数据处理 | pandas |
| 评估框架 | RAGAS（backend/evaluation/） |
| 前端框架 | React 19 + Vite 8 |
| 前端路由 | react-router-dom 7 |
| 前端 HTTP | axios（同步） + 原生 fetch（SSE 流式） |
| 状态管理 | React Context（AuthContext） |
| 前端 Lint | Oxlint |

---

## 2. 系统整体架构

系统采用前后端分离架构，后端为 RAG 智能问答服务，前端为 React SPA。

### 2.1 架构总览图

```
┌──────────────────────────────────────────────────────────────────────┐
│                            前端 (React + Vite)                         │
│  Login / Register / Dashboard  ←→  AuthContext  ←→  axios client     │
│                          (JWT 存于 localStorage)                       │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ HTTP / REST (Bearer JWT)
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      后端 (FastAPI, main.py)                          │
│  ┌──────────────┐   ┌────────────────────────────────────────────┐  │
│  │  api/auth.py  │   │  api/qa.py (问答路由 + NL2SQL 路由分发)       │  │
│  │  注册/登录/me  │   │  /ask /ask/stream /history /conversations   │  │
│  │  用户管理/改密 │   │  /feedback /feedback/stats                 │  │
│  └──────┬───────┘   └──────────────┬─────────────────────────────┘  │
│         │                          │ detect_intent 路由              │
│         ▼                          ▼                                │
│  ┌──────────────┐      ┌───────────────────────┐ ┌────────────────┐  │
│  │ core/security│      │ services/qa_pipeline  │ │ services/nl2sql│  │
│  │  JWT + bcrypt│      │  QAPipeline (RAG 路径) │ │ (聚合统计路径)  │  │
│  └──────┬───────┘      └──┬─────────┬──────────┘ └───────┬────────┘  │
│         │                 │         │                   │           │
│         ▼                 ▼         ▼                   ▼           │
│  ┌──────────────┐   ┌──────────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ core/database │   │hybrid_retriev│ │llm_client│ │ SQLite logs  │  │
│  │  SQLAlchemy   │   │   RRF 融合    │ │ DeepSeek │ │  (只读查询)   │  │
│  │  SQLite       │   └──┬───────┬───┘ └──────────┘ └──────────────┘  │
│  └──────┬───────┘      │       │                                    │
│         │              ▼       ▼                                    │
│         ▼       ┌──────────┐ ┌──────────────┐                      │
│  ┌────────────┐ │retriever │ │bm25_retriever│                      │
│  │  models/*  │ │ (向量)   │ │  (关键词)     │                      │
│  │ User/Log/  │ └────┬─────┘ └──────┬───────┘                      │
│  │ QAHistory/ │      │            │                                │
│  │ AuditLog   │      ▼            ▼                                │
│  └────────────┘ ┌──────────┐ ┌──────────┐ ┌────────┐              │
│                 │ embedder │ │qdrant_   │ │ chunker│              │
│                 │  BGE-zh  │ │client    │ │  分块   │              │
│                 └──────────┘ └──────────┘ └────────┘                │
│                 ┌──────────┐                                       │
│                 │ reranker │  (可选 Cross-Encoder 精排)              │
│                 └──────────┘                                       │
└──────────────────────────────────────────────────────────────────────┘
        │                              │
        ▼                              ▼
  ┌──────────┐                  ┌───────────────┐
  │ SQLite   │                  │   Qdrant 云    │
  │ app.db   │                  │ (向量库 768维)  │
  └──────────┘                  └───────────────┘
        │
        ▼
  ┌──────────────────┐
  │ data/*.csv 日志源  │
  └──────────────────┘
```

### 2.2 RAG 核心处理链

```
日志源 CSV
  │
  ▼ LogParser 解析校验
  ▼ LogCleaner 清洗去重
  ▼ LogChunker 分块
  ▼ BGEEmbedder 向量化
  ▼ QdrantClientWrapper 入库（向量 + payload）
  │
  │ ◆ 用户提问 ◆
  ▼
  ▼ api/qa.py: detect_intent 路由分发
  │     ├─ 聚合/统计类（"统计/数量/Top N/占比..."）→ services/nl2sql.ask
  │     │     ├─ LLM 生成 SQL（DeepSeek + schema 提示）
  │     │     ├─ 安全校验（禁写/强制 LIMIT）
  │     │     └─ 只读执行 SQLite logs 表 + 格式化为五段式答案
  │     └─ 其他问题 → RobustQAPipeline.ask（RAG 路径）
  │           ├─ HybridRetrieverAsync 并行检索
  │           │     ├─ LogRetriever（向量检索，Qdrant）
  │           │     └─ BM25Retriever（关键词检索，本地索引）
  │           ├─ RRF 融合重排（1/(k+rank)，OPT2 默认 v=1.0/b=2.0）
  │           ├─ （可选）Reranker Cross-Encoder 精排
  │           ├─ PromptTemplates 构造证据链 Prompt（含 DB 加载的多轮历史）
  │           ├─ DeepSeekClient 调用 LLM（同步 / 流式 SSE）
  │           ├─ QAPipeline 内置来源标注（[ID:xxx] → [n]）
  │           ├─ QualityChecker 质量自检（幻觉检测等）
  │           └─ ErrorHandler 异常兜底（兜底返回 confidence="低" 的 QAResult）
  ▼
  返回 QAResult（答案 + 来源 + 置信度 + 耗时 + retriever_type）
  ▼
  持久化 QAHistory（含 conversation_id + quality_check JSON）+ 审计日志
```

### 2.3 Pipeline 编排模型

`QAPipeline` 为基础问答流水线（检索 + Prompt + LLM + 内置来源提取）。生产路径通过 `RobustQAPipeline` 包装 `QAPipeline` 接管异常处理与重试，质量自检与多轮对话历史加载由 `api/qa.py` 路由层在调用前后编排：

```
api/qa.py 路由层
  ├─ _resolve_conversation_id / _load_conversation_history  ← DB 多轮上下文
  ├─ _run_quality_check                                      ← QualityChecker（路由层调用）
  └─ _build_pipeline → create_robust_pipeline(...)
        └─ RobustQAPipeline ← 异常兜底（最外层）
             └─ QAPipeline  ← 基础流水线（检索 + Prompt + LLM + 来源提取）
```

> 说明：早期版本的 `ConversationAwarePipeline` / `SourceAwareQAPipeline` / `QualityAwarePipeline` 装饰器式包装已废弃（`services/conversation.py`、`services/source_tracking.py` 已于 2026-07-26 删除）。多轮对话改由 DB `qa_history.conversation_id` 持久化实现，来源溯源直接在 `QAPipeline` 内部完成，质量自检在路由层显式调用 `QualityChecker`。`services/quality_checker.py` / `services/error_handler.py` 仍保留 `QualityAwarePipeline` / `RobustQAPipeline` 类供脚本场景使用。

---

## 3. 目录结构

```
log-qa-system/
├── backend/                         # 后端 FastAPI 服务
│   ├── api/                         # API 路由层
│   │   ├── __init__.py
│   │   ├── auth.py                  # 认证 + 用户管理 + 改密路由
│   │   └── qa.py                    # ★ 问答路由（同步/SSE/历史/会话/反馈/统计 + NL2SQL 路由）
│   ├── core/                        # 核心配置层
│   │   ├── __init__.py
│   │   ├── config.py                # 应用配置类 Settings
│   │   ├── database.py              # SQLAlchemy 引擎与会话
│   │   └── security.py              # JWT + bcrypt 密码工具
│   ├── data/                        # 日志数据 CSV
│   │   ├── logs.csv
│   │   └── logs_cleaned.csv
│   ├── evaluation/                  # ★ RAGAS 评估框架与消融实验
│   │   ├── __init__.py
│   │   ├── eval_core.py             # 评估核心逻辑
│   │   ├── ragas_config.py          # RAGAS 配置
│   │   ├── testset_loader.py        # 测试集加载
│   │   ├── data/                    # 测试集与实验结果（testset.json 60 条 QA + 各消融配置 JSON/raw.jsonl）
│   │   ├── docs/                    # 评估报告与设计文档（reports/ablation_*.md 等）
│   │   └── scripts/                 # 评估脚本（run_baseline/run_ablation/eval_split/build_testset/test_ragas）
│   ├── models/                      # SQLAlchemy ORM 模型
│   │   ├── __init__.py              # 统一导出
│   │   ├── user.py                  # User + UserRole
│   │   ├── log.py                   # Log
│   │   ├── qa_history.py            # QAHistory + FeedbackType（含 conversation_id + quality_check 字段）
│   │   ├── audit_log.py             # AuditLog
│   │   └── conversation.py          # 空占位文件（会话持久化已合并到 qa_history）
│   ├── schemas/                     # Pydantic 请求/响应 Schema
│   │   ├── __init__.py
│   │   ├── auth.py                  # Login/Register/Token/UserResponse + SetRole/ChangePassword/DeleteUser
│   │   └── qa.py                    # ★ QA 请求/响应 + 历史 + 会话 + 反馈 + 质量检查 Schema
│   ├── scripts/                     # 运维/数据脚本 + 功能测试脚本
│   │   ├── import_logs.py           # 日志批量入库
│   │   ├── batch_vectorize.py       # 批量向量化入库 Qdrant
│   │   ├── generate_logs.py         # 生成测试日志
│   │   ├── check_db.py              # 检查数据库表
│   │   ├── debug_bm25.py            # BM25 分词调试
│   │   ├── visualize_retrieval.py   # 检索结果可视化对比
│   │   ├── test_admin_view_conversation.py  # admin 查看他人会话权限测试
│   │   ├── test_bm25.py / test_hybrid.py / test_retrieval.py
│   │   ├── test_cleaner.py / test_parser.py / test_formatter.py
│   │   ├── test_error_handling.py / test_quality_check.py / test_source_tracking.py
│   │   ├── test_feedback_stats.py   # 反馈统计接口测试
│   │   ├── test_llm.py / test_qa_pipeline.py
│   │   ├── test_multi_turn.py       # 多轮对话测试
│   │   ├── test_performance.py      # 性能测试
│   │   └── test_role_security.py    # 角色/权限安全测试
│   ├── services/                    # 核心业务服务层（RAG 核心）
│   │   ├── __init__.py
│   │   ├── qa_pipeline.py            # ★ 问答流水线编排（内置来源提取）
│   │   ├── hybrid_retriever.py       # ★ 混合检索器（RRF 融合）
│   │   ├── retriever.py              # 向量检索器
│   │   ├── bm25_retriever.py         # BM25 关键词检索器
│   │   ├── qdrant_client.py          # Qdrant 客户端封装
│   │   ├── embedder.py               # BGE 嵌入模型封装
│   │   ├── reranker.py               # ★ Cross-Encoder 重排序（bge-reranker-base，可选）
│   │   ├── nl2sql.py                 # ★ 聚合类问题 NL2SQL 路径（意图识别+生成+校验+执行）
│   │   ├── llm_client.py             # DeepSeek LLM 客户端
│   │   ├── prompt_templates.py       # Prompt 模板
│   │   ├── chunker.py                # 日志文本分块器
│   │   ├── formatter.py              # 检索结果格式化
│   │   ├── log_parser.py             # 日志解析器
│   │   ├── log_cleaner.py            # 日志清洗器
│   │   ├── quality_checker.py        # 回答质量自检
│   │   ├── error_handler.py          # 统一异常处理（RobustQAPipeline）
│   │   └── exceptions.py             # 自定义异常类
│   ├── tests/                       # pytest 测试
│   │   ├── conftest.py
│   │   ├── pytest.ini
│   │   ├── test_auth.py
│   │   ├── test_qa_pipeline_unit.py
│   │   ├── test_qdrant_connection.py
│   │   ├── test_retrieval.py
│   │   └── test_retriever.py
│   ├── utils/                       # 工具层（当前为空）
│   │   ├── __init__.py
│   │   └── logger.py
│   ├── main.py                      # FastAPI 应用入口
│   ├── app.db                       # ★ SQLite 数据库文件（users / logs / qa_history / audit_logs）
│   └── requirements.txt
├── frontend/                        # 前端 React 应用
│   ├── public/
│   │   ├── favicon.svg
│   │   └── icons.svg
│   ├── src/
│   │   ├── api/
│   │   │   ├── client.js            # axios 实例 + 拦截器
│   │   │   ├── auth.js              # 认证 + 用户管理 + 改密 API 封装
│   │   │   └── qa.js                # ★ 问答 API 封装（同步/SSE/历史/会话/反馈/统计）
│   │   ├── assets/
│   │   ├── components/
│   │   │   ├── ProtectedRoute.jsx   # 通用路由守卫（已登录）
│   │   │   ├── AdminRoute.jsx       # ★ admin 角色守卫（非 admin 跳转）
│   │   │   ├── Chat.jsx / Chat.css              # ★ SSE 流式问答界面 + 来源卡片 + 反馈按钮 + 质量检查
│   │   │   ├── ConversationSidebar.jsx / .css   # ★ 会话列表侧边栏
│   │   │   └── ChangePasswordModal.jsx / .css   # ★ 修改密码弹窗
│   │   ├── context/
│   │   │   └── AuthContext.jsx      # 全局认证 Context
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx / .css # 主问答界面（含 Chat + ConversationSidebar）
│   │   │   ├── Login.jsx / .css     # 登录页
│   │   │   ├── Register.jsx         # 注册页
│   │   │   └── UserManagement.jsx   # ★ 管理员用户管理界面（admin 专属）
│   │   ├── App.jsx                  # 根组件 + 路由（含 /admin/users）
│   │   ├── App.css
│   │   ├── index.css
│   │   └── main.jsx                 # 入口
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── README.md
├── docs/                            # 文档
│   ├── frontend/                    # 前端目录副本（含 .env 示例，详见第 12 章）
│   ├── API.md                       # 空
│   ├── DEPLOY.md                    # 空
│   └── 前后端启动.txt
├── .gitignore
└── README.md                         # 空
```

---

## 4. 技术栈与依赖

### 4.1 后端依赖（`backend/requirements.txt`）

| 依赖 | 版本 | 用途 |
|------|------|------|
| fastapi | 0.104.1 | Web 框架 |
| uvicorn[standard] | 0.24.0 | ASGI 服务器 |
| sqlalchemy | 2.0.23 | ORM |
| python-dotenv | 1.0.0 | .env 加载 |
| pytest / pytest-cov | 7.4.3 / 4.1.0 | 测试 |
| bcrypt | 4.1.1 | 密码哈希 |
| python-jose[cryptography] | 3.3.0 | JWT |
| passlib[bcrypt] | 1.7.4 | 密码哈希封装 |
| python-multipart | 0.0.6 | 表单解析 |
| pandas | 2.1.3 | CSV/数据处理 |
| sentence-transformers | 2.2.2 | BGE 模型加载 |
| qdrant-client | 1.7.0 | Qdrant 客户端 |
| torch | 2.1.0 | PyTorch（CPU） |
| transformers | 4.36.0 | HuggingFace 模型库 |
| tqdm | 4.66.1 | 进度条 |
| numpy | 1.24.3 | 向量计算 |

> 另通过代码动态导入：`jieba`（中文分词）、`rank_bm25`（BM25 算法）、`nltk`（词干提取）、`httpx`（HTTP 客户端）、`modelscope`（模型下载）。需手动安装：`pip install jieba rank_bm25 nltk httpx modelscope`。

### 4.2 前端依赖（`frontend/package.json`）

| 依赖 | 版本 | 用途 |
|------|------|------|
| react / react-dom | ^19.2.7 | UI 框架 |
| react-router-dom | ^7.18.1 | 路由 |
| axios | ^1.18.1 | HTTP 客户端 |
| @vitejs/plugin-react | ^6.0.3 | Vite React 插件 |
| vite | ^8.1.1 | 构建工具 |
| oxlint | ^1.71.0 | Lint |

---

## 5. 后端模块详解

### 5.1 应用入口 main.py

**路径**：[backend/main.py](file:///d:/log-qa-system/backend/main.py)

FastAPI 应用入口，职责：

1. **应用生命周期管理**（`lifespan`）：启动时执行 `init_db()` 建表与轻量迁移，再执行 `warmup()` 系统预热；关闭时释放混合检索器线程池。
2. **系统预热 `warmup()`**：依次预加载 jieba 词典、BGE 模型、BM25 索引、Qdrant 连接、混合检索器，避免首次请求冷启动延迟。
3. **CORS 中间件**：允许 `http://localhost:5173`、`http://localhost:5174`、`http://localhost:3000`。
4. **路由注册**：`api.auth`（前缀 `/api/auth`，含认证 + 用户管理 + 改密）、`api.qa`（前缀 `/api/qa`，含问答同步/SSE/历史/会话/反馈/统计）。
5. **健康检查**：`GET /`、`GET /health`。

**关键对象**：

| 名称 | 类型 | 说明 |
|------|------|------|
| `app` | FastAPI | 全局应用实例（title="日志智能问答系统 API"） |
| `warmup()` | function | 启动预热，加载模型与索引 |
| `lifespan(app)` | async context manager | 应用生命周期管理 |

---

### 5.2 核心配置层 core/

#### 5.2.1 config.py — 应用配置

**路径**：[backend/core/config.py](file:///d:/log-qa-system/backend/core/config.py)

| 类 | 说明 |
|----|------|
| `Settings` | 应用配置类，所有配置项从环境变量读取并提供默认值 |

**配置项分组**：

| 分组 | 字段 | 默认值 |
|------|------|--------|
| DeepSeek | `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | `""` / `https://api.deepseek.com` / `deepseek-v4-pro` |
| Qdrant | `QDRANT_URL` / `QDRANT_API_KEY` / `QDRANT_COLLECTION_NAME` | `""` / `""` / `log_knowledge` |
| RAG | `RETRIEVER_TOP_K` / `RETRIEVER_SCORE_THRESHOLD` | 10 / 0.0 |
| JWT | `SECRET_KEY` / `ALGORITHM` / `ACCESS_TOKEN_EXPIRE_MINUTES` | `dev-secret-key` / `HS256` / 30 |
| 切片 | `LOG_CHUNK_SIZE` / `LOG_CHUNK_OVERLAP` | 500 / 50 |

- `check_config()` 类方法：校验 DeepSeek/Qdrant 关键配置是否完整，缺失时打印告警。
- 全局实例：`settings = Settings()`。

#### 5.2.2 database.py — 数据库

**路径**：[backend/core/database.py](file:///d:/log-qa-system/backend/core/database.py)

- SQLite 数据库，文件路径 `<backend>/app.db`。
- `engine`：SQLAlchemy 引擎（`check_same_thread=False` 支持多线程）。
- `SessionLocal`：会话工厂（`autocommit=False, autoflush=False`）。
- `Base`：declarative base，所有 ORM 模型继承自此。
- `get_db()`：FastAPI 依赖注入生成器，提供数据库会话并在请求结束自动关闭。
- `init_db()`：创建所有表（导入所有模型后调用 `Base.metadata.create_all`）。

#### 5.2.3 security.py — 认证工具

**路径**：[backend/core/security.py](file:///d:/log-qa-system/backend/core/security.py)

| 函数 | 说明 |
|------|------|
| `verify_password(plain, hashed) -> bool` | bcrypt 密码校验 |
| `get_password_hash(password) -> str` | bcrypt 密码哈希 |
| `create_access_token(data, expires_delta=None) -> str` | 生成 JWT（含 exp，默认 30 分钟） |
| `decode_token(token) -> Optional[dict]` | 解码 JWT，失败返回 None |
| `get_username_from_token(token) -> Optional[str]` | 从 Token 提取 `sub`（用户名） |

- 使用 `passlib.context.CryptContext(schemes=["bcrypt"])`。
- JWT 通过 `jose.jwt` 编解码，算法与密钥取自 `settings`。

---

### 5.3 数据模型层 models/

所有模型继承自 `core.database.Base`。统一通过 `models/__init__.py` 导出。

#### 5.3.1 user.py

**路径**：[backend/models/user.py](file:///d:/log-qa-system/backend/models/user.py)

| 名称 | 类型 | 说明 |
|------|------|------|
| `UserRole` | Enum(str, enum.Enum) | `ADMIN="admin"`、`USER="user"` |
| `User` | ORM Model | 表 `users` |

`User` 字段：

| 字段 | 类型 | 约束 |
|------|------|------|
| `id` | Integer | PK, autoincrement |
| `username` | String(50) | unique, index, not null |
| `password_hash` | String(255) | not null（bcrypt） |
| `role` | Enum(UserRole) | default=USER, not null |
| `created_at` | DateTime | default=datetime.now |
| `updated_at` | DateTime | default=datetime.now, onupdate=datetime.now |

#### 5.3.2 log.py

**路径**：[backend/models/log.py](file:///d:/log-qa-system/backend/models/log.py)

`Log` 模型，表 `logs`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer | PK |
| `timestamp` | DateTime | 日志发生时间 |
| `level` | String(10) | INFO/WARNING/ERROR/DEBUG（index） |
| `service` | String(50) | 服务名（index） |
| `ip` | String(15) | 来源 IP |
| `message` | Text | 日志消息 |
| `trace_id` | String(8) | 链路追踪 ID（index） |
| `created_at` | DateTime | 入库时间 |

**复合索引**：`idx_logs_time_level(timestamp, level)`、`idx_logs_service_time(service, timestamp)`。

#### 5.3.3 qa_history.py

**路径**：[backend/models/qa_history.py](file:///d:/log-qa-system/backend/models/qa_history.py)

| 名称 | 类型 | 说明 |
|------|------|------|
| `FeedbackType` | Enum | `LIKE`/`DISLIKE`/`NONE` |
| `QAHistory` | ORM Model | 表 `qa_history` |

`QAHistory` 字段：`id`、`user_id`(FK→users.id)、`question`、`answer`、`sources`(Text, JSON)、`feedback`、`created_at`、`conversation_id`(String(64), index，多轮对话分组)、`quality_check`(Text, JSON，质量自检结果)。

- 关系：`user = relationship("User", backref="qa_histories")`（多对一）。
- 多轮对话：同一 `conversation_id` 下的多条 Q&A 记录组成一个会话；NULL 表示独立问答或旧数据。

#### 5.3.4 audit_log.py

**路径**：[backend/models/audit_log.py](file:///d:/log-qa-system/backend/models/audit_log.py)

`AuditLog` 模型，表 `audit_logs`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | Integer | PK |
| `user_id` | Integer | 操作用户 ID（**无 FK 约束**，保留历史） |
| `username` | String(50) | 冗余存储用户名 |
| `action` | String(50) | 操作类型：register/login_success/login_failed/logout/ask/feedback/delete |
| `resource` | String(100) | 操作资源 |
| `details` | Text | 详情（JSON） |
| `ip_address` | String(45) | 客户端 IP（兼容 IPv6） |
| `created_at` | DateTime | 操作时间 |

> 设计说明：`user_id` 不加外键约束 + 冗余 `username`，保证用户删除后审计记录仍可追溯。

#### 5.3.5 conversation.py

**路径**：[backend/models/conversation.py](file:///d:/log-qa-system/backend/models/conversation.py)

**文件为空**。会话持久化已合并到 `qa_history.conversation_id` 字段实现，无需独立 ORM 模型（见 5.3.3）。

---

### 5.4 Pydantic Schema 层 schemas/

#### 5.4.1 auth.py

**路径**：[backend/schemas/auth.py](file:///d:/log-qa-system/backend/schemas/auth.py)

| Schema | 字段 | 校验 |
|--------|------|------|
| `LoginRequest` | username, password | 3-50 / 6-50 字符 |
| `RegisterRequest` | username, password | 同上（`role` 字段被忽略，强制 `user`） |
| `TokenResponse` | access_token, token_type, username, role, user_id | — |
| `UserResponse` | id, username, role, created_at(str) | — |
| `SetRoleRequest` | role | `admin` / `user` |
| `SetRoleResponse` | success, user_id, username, old_role, new_role, message | — |
| `ChangePasswordRequest` | old_password, new_password | 新密码 6-50 字符，不能与旧密码相同 |
| `ChangePasswordResponse` | success, message | — |
| `DeleteUserResponse` | success, user_id, username, deleted_qa_count, message | — |

> 注：`UserResponse.created_at` 为 `str` 类型，需业务层转换；未配置 `orm_mode`，ORM→Schema 转换需手动完成。注册接口的 `role` 入参被服务端强制忽略，统一注册为 `user`，admin 提权通过 `PATCH /api/auth/users/{id}/role`。

#### 5.4.2 qa.py — 问答 Schema

**路径**：[backend/schemas/qa.py](file:///d:/log-qa-system/backend/schemas/qa.py)

已实现问答 API 全部请求/响应 Schema：

| Schema | 用途 |
|--------|------|
| `QARequest` | 问答请求：question / filters / top_k(1-50) / template_type / retriever_type / conversation_id |
| `QASourceRef` | 来源引用：ref_id / log_id / service / timestamp / level / content / score / snippet |
| `QAQualityIssue` | 质量检查单条问题：type / message / penalty / suggestion |
| `QAQualityCheck` | 质量自检结果：passed / score(0-100) / issues[] / warnings[] / suggestions[] |
| `QAResponse` | 问答响应：success / question / answer / sources[] / confidence / retriever_type / total_tokens / retrieval_time / llm_time / total_time / qa_id / conversation_id / quality_check / error |
| `QAHistoryItem` / `QAHistoryListResponse` / `QAHistoryDetailResponse` | 问答历史列表与详情 |
| `FeedbackRequest` / `FeedbackResponse` | 反馈请求/响应 |
| `ConversationItem` / `ConversationListResponse` | 会话列表 |
| `ConversationMessageItem` / `ConversationDetailResponse` / `ConversationDeleteResponse` | 会话详情与删除 |
| `FeedbackStatsItem` / `FeedbackStatsResponse` | 反馈统计（含 scope / like_rate / top_disliked） |

---

### 5.5 API 路由层 api/

#### 5.5.1 auth.py — 认证路由

**路径**：[backend/api/auth.py](file:///d:/log-qa-system/backend/api/auth.py)

路由前缀 `/api/auth`，全部接口在 `auth.router` 中。

**辅助函数**：

| 函数 | 说明 |
|------|------|
| `log_audit(db, user_id, username, action, resource, details, ip)` | 记录审计日志 |
| `get_current_user(db, credentials)` | 依赖注入：从 Bearer Token 解析当前用户，401 时抛异常 |
| `_require_admin(user)` | 校验当前用户是否为 admin，否则抛 403（管理员接口前置守卫） |

**接口清单**：

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/auth/register` | 用户注册（role 强制为 user，忽略入参） | 否 |
| POST | `/api/auth/login` | 用户登录，返回 JWT TokenResponse | 否 |
| GET | `/api/auth/me` | 获取当前用户信息 | 是 |
| POST | `/api/auth/me/password` | 修改自己的密码（验证旧密码） | 是 |
| POST | `/api/auth/logout` | 登出（记录审计日志，客户端清 Token） | 是 |
| GET | `/api/auth/users` | 查询所有用户列表（仅 admin，支持 username 模糊搜索） | admin |
| PATCH | `/api/auth/users/{user_id}/role` | 修改用户角色 admin↔user（仅 admin，不能改自己） | admin |
| DELETE | `/api/auth/users/{user_id}` | 删除用户（仅 admin，不能删自己，不能删最后一个 admin，级联删 QA 历史） | admin |

- 登录失败会记录 `login_failed` 审计日志；成功记录 `login_success`。
- `get_current_user` 作为 FastAPI 依赖，用于保护需要登录的接口；管理员接口在内部调用 `_require_admin` 二次校验。

#### 5.5.2 qa.py — 问答路由

**路径**：[backend/api/qa.py](file:///d:/log-qa-system/backend/api/qa.py)

路由前缀 `/api/qa`，全部接口在 `qa.router` 中，需要登录（`get_current_user`）。

**模块级常量**：

| 名称 | 说明 |
|------|------|
| `MAX_HISTORY_TURNS` | 传给 LLM 的最大历史轮数（1 轮 = 1 user + 1 assistant），默认 5 |
| `_quality_checker` | 进程级 `QualityChecker` 单例（无状态） |

**辅助函数**：

| 函数 | 说明 |
|------|------|
| `_run_quality_check(answer, sources, confidence)` | 调用 `QualityChecker` 并转换为 `QAQualityCheck` Schema，异常时返回 None 不影响主流程 |
| `_build_pipeline(request)` | 构建 `RobustQAPipeline`（每请求新建），采用 OPT2 最优配置 `vector_weight=1.0 / bm25_weight=2.0`（偏 BM25，日志检索场景关键词匹配更重要） |
| `_resolve_conversation_id(db, user_id, conversation_id)` | 解析会话 ID：复用已有会话时校验归属；不传或越权时新建 `conv_<uuid4_hex[:16]>` |
| `_load_conversation_history(db, user_id, conversation_id, max_turns)` | 从 DB 加载多轮历史并转换为 `[{role, content}]`，按时间正序取最近 max_turns 轮 |
| `_sse_event(event, data)` | 格式化单条 SSE 事件为 `event: ...\ndata: ...\n\n` |
| `_parse_sources(sources_json)` / `_parse_quality_check(qc_json)` | 安全解析 JSON 字段 |

**接口清单**：

| 方法 | 路径 | 说明 | 路由 |
|------|------|------|------|
| POST | `/api/qa/ask` | 同步问答：`detect_intent` 路由（聚合类→NL2SQL，其他→RAG），返回 `QAResponse`（含 conversation_id / qa_id / quality_check） | RAG / NL2SQL |
| POST | `/api/qa/ask/stream` | 流式问答（SSE）：事件 `source` / `answer` / `done` / `error`；done 含完整答案 + conversation_id + quality_check | RAG / NL2SQL |
| GET | `/api/qa/history` | 查询当前用户问答历史（分页 / keyword / feedback 过滤） | — |
| GET | `/api/qa/history/{history_id}` | 查询单条历史详情（仅自己的记录，否则 404） | — |
| POST | `/api/qa/feedback/{qa_id}` | 提交点赞/点踩/取消反馈（仅自己的记录） | — |
| GET | `/api/qa/conversations` | 查询会话列表（scope=me / scope=all 仅 admin；非 admin 传 all 降级为 me） | — |
| GET | `/api/qa/conversations/{conversation_id}` | 查询会话详情（admin 可查任意会话并返回 owner_username；普通用户仅自己，否则 404） | — |
| DELETE | `/api/qa/conversations/{conversation_id}` | 删除会话及其全部问答记录（仅自己的会话） | — |
| GET | `/api/qa/feedback/stats` | 反馈统计（scope=me / scope=all 仅 admin；返回 like_rate + top_disliked 10 条） | — |

**关键设计**：

- **路由分发**：`ask` 与 `ask_stream` 在路由层调用 `services.nl2sql.detect_intent`，命中聚合关键词走 NL2SQL 路径，否则走 `RobustQAPipeline` RAG 路径。
- **多轮对话**：路由层负责从 DB 加载历史并传入 `pipeline.ask(history=...)`，每次回答后持久化为 `QAHistory` 记录并携带 `conversation_id`，前端在后续提问中携带该 ID 维持上下文。
- **兜底响应**：`RobustQAPipeline` 在 LLM 超时 / 检索故障重试失败时返回 `confidence="低" 且 source_refs 为空` 的 `QAResult`，路由层据此将响应标记为 `success=False` 并回填 `error` 字段，HTTP 状态码仍为 200（不抛 5xx）。
- **质量自检**：在响应返回前对完整答案执行 `QualityChecker`，结果以 JSON 字符串存入 `qa_history.quality_check`，并同步返回到响应体供前端展示。
- **审计日志**：每次 ask / ask_stream / feedback / delete_conversation 均调用 `log_audit` 记录关键信息（question 摘要、retriever_type、conversation_id、total_time 等）。

---

### 5.6 服务层 services/（核心业务逻辑）

服务层是 RAG 系统的核心，按职责分为：检索服务、LLM 服务、数据处理服务、Pipeline 编排与增强服务。

#### 5.6.1 qa_pipeline.py — 问答流水线（编排核心）★

**路径**：[backend/services/qa_pipeline.py](file:///d:/log-qa-system/backend/services/qa_pipeline.py)

将"检索 + Prompt + LLM"串联为完整问答流水线。

**数据类**：

| 类 | 字段 |
|----|------|
| `SourceReference` | ref_id, log_id, service, timestamp, level, content, score, snippet |
| `QAResult` | question, answer, sources, source_refs, confidence, total_tokens, retrieval_time, llm_time, total_time, retriever_type |
| `StreamChunk` | type(source/answer/source_ref), content, data |

**核心类 `QAPipeline`**：

| 方法 | 说明 |
|------|------|
| `__init__(top_k=5, template_type="evidence_chain", retriever_type="hybrid", max_log_length=300)` | 初始化，按 retriever_type 选择检索器 |
| `_init_retriever(retriever_type)` | 初始化 vector/bm25/hybrid 检索器 |
| `_search_vector / _search_bm25 / _search_hybrid` | 三种检索路径，统一转换为 dict 列表 |
| `_extract_source_refs(answer, sources)` | 从回答解析 `[ID:xxx]` 引用并匹配日志，无引用时自动为前 5 条来源分配 `[n]` |
| `_annotate_answer_with_refs(answer, source_refs)` | 将 `[ID:xxx]` 替换为 `[n]` |
| `ask(question, filters, top_k, template_type, history) -> QAResult` | ★ 同步问答：检索→截断→构造 Prompt（含多轮 history）→调用 LLM→提取来源→标注→估计置信度。历史持久化由调用方（api/qa.py）负责 |
| `ask_stream(question, ..., history) -> Generator[StreamChunk]` | ★ 流式问答，先 yield 来源块，再逐块 yield 答案；支持 history 多轮上下文 |
| `ask_with_context(question, logs, template_type) -> str` | 跳过检索，基于给定日志直接问答 |
| `clear_history()` / `get_history()` | 对话历史管理 |
| `_estimate_confidence(logs, answer) -> str` | 估计"高/中/低"置信度（基于引用数、分段完整性、日志数） |

**工厂函数**：`create_pipeline(top_k, template_type, retriever_type, max_log_length) -> QAPipeline`。

#### 5.6.2 hybrid_retriever.py — 混合检索器（RRF 融合）★

**路径**：[backend/services/hybrid_retriever.py](file:///d:/log-qa-system/backend/services/hybrid_retriever.py)

使用 `asyncio.gather` 并行执行向量检索和 BM25 检索，通过 RRF（Reciprocal Rank Fusion）融合重排。

**数据类**：

| 类 | 字段 |
|----|------|
| `HybridResult` | log_id, payload, vector_score, bm25_score, rrf_score, vector_rank, bm25_rank, metadata |

**核心类 `HybridRetrieverAsync`**：

| 方法 | 说明 |
|------|------|
| `__init__(k=60, top_k=10, vector_weight=1.0, bm25_weight=1.0, max_workers=2)` | 初始化，延迟加载子检索器，创建 ThreadPoolExecutor |
| `vector_retriever` / `bm25_retriever` (property) | 延迟初始化的检索器属性 |
| `_rrf_score(rank) -> float` | RRF 公式：`1.0 / (k + rank)` |
| `_search_vector_async(query, top_k, filter_params)` | 异步向量检索（`run_in_executor` 包装同步方法） |
| `_search_bm25_async(query, top_k, filter_params)` | 异步 BM25 检索 |
| `search_async(query, top_k, filter_params, vector_top_k, bm25_top_k)` | ★ 异步混合检索主入口，并行检索 + RRF 融合 + Top-K 截取 |
| `search(query, ...)` | 同步接口（内部 `asyncio.run`） |
| `search_formatted / search_formatted_async` | 返回带 summary/evidence 的格式化结果 |
| `close()` | 关闭线程池 |

**单例**：`get_hybrid_retriever_async(k, top_k, vector_weight, bm25_weight, max_workers)`。

**便捷函数**：`hybrid_search_async(query, top_k, level, service, source)`、`hybrid_search_async_only(...)`。

#### 5.6.3 retriever.py — 向量检索器

**路径**：[backend/services/retriever.py](file:///d:/log-qa-system/backend/services/retriever.py)

基于 Qdrant 的向量语义检索。

**数据类**：`RetrievalResult`（id, payload, score, metadata），含 `to_dict()`、`get_log_info()`、`to_retrieved_log()`。

**核心类 `LogRetriever`**：

| 方法 | 说明 |
|------|------|
| `__init__(embedder, client, top_k=10, score_threshold=0.0)` | 初始化，确保 Collection 存在 |
| `_ensure_collection_exists()` | 检查/创建 Collection |
| `_build_filter_dict(level, service, source, timestamp_before/after/between, log_id, **kwargs)` | 构造 Qdrant 过滤条件 |
| `search(query, top_k, filter_params, score_threshold) -> List[RetrievalResult]` | ★ 核心向量检索（768 维校验/补零） |
| `search_formatted(...)` | 带格式化的检索 |
| `search_by_level / search_by_service / search_by_time` | 按维度过滤检索 |
| `search_batch(queries)` | 批量检索 |
| `search_by_vector(vector, ...)` | 直接用向量检索 |
| `count_vectors() -> int` | 统计向量数 |

**单例**：`get_retriever()`。**便捷函数**：`search_logs(...)`、`search_logs_formatted(...)`。

#### 5.6.4 bm25_retriever.py — BM25 关键词检索器

**路径**：[backend/services/bm25_retriever.py](file:///d:/log-qa-system/backend/services/bm25_retriever.py)

基于 `rank_bm25.BM25Okapi` 的关键词检索，支持中英文混合分词 + Porter 词干提取 + 中英文同义词映射。

**数据类**：`BM25Result`（log_id, payload, score）。

**核心类 `BM25Retriever`**：

| 方法 | 说明 |
|------|------|
| `__init__(corpus, cache_path="./bm25_index.pkl", use_cache=True)` | 初始化，可选加载缓存索引 |
| `_init_stemmer()` | 初始化 NLTK Porter 词干提取器（自动下载 punkt/stopwords） |
| `_tokenize(text) -> List[str]` | ★ 中英文混合分词 + 词干 + 同义词映射（核心） |
| `_map_chinese_to_english(word)` | 中文→英文同义词映射（内置 90+ 词条） |
| `_get_stopwords() -> set` | 中英文停用词（带缓存） |
| `build_index(corpus)` | 构建 BM25 索引并保存缓存 |
| `search(query, top_k, filter_level/service/source) -> List[BM25Result]` | 执行 BM25 检索 |
| `search_with_filter(query, top_k, filter_params)` | 通用过滤检索 |
| `save_index(path)` / `load_index(path)` | pickle 序列化/反序列化 |
| `get_document_count() -> int` | 文档数 |

**单例**：`get_bm25_retriever(corpus, cache_path)`。**便捷函数**：`bm25_search(query, top_k, level, service, source)`。

#### 5.6.5 qdrant_client.py — Qdrant 客户端封装

**路径**：[backend/services/qdrant_client.py](file:///d:/log-qa-system/backend/services/qdrant_client.py)

| 名称 | 说明 |
|------|------|
| `QdrantRetryableError` | 可重试异常 |
| `QdrantFatalError` | 致命异常 |
| `QdrantClientWrapper` | 客户端封装主类 |

**`QdrantClientWrapper` 关键方法**：

| 方法 | 说明 |
|------|------|
| `__init__()` | 从 env 读取配置，创建 QdrantClient（gRPC, timeout=120） |
| `health_check() -> bool` | 健康检查 |
| `create_collection(recreate=False) -> bool` | 创建 Collection（HNSW m=16, ef_construct=100）+ 6 个 Payload 索引 |
| `_create_payload_indexes()` | 为 log_id/level/service/timestamp/chunk_text/source 建索引 |
| `upsert_vectors(points, batch_size=20) -> bool` | 批量向量入库 |
| `search(query_vector, top_k, score_threshold, filter_conditions)` | 向量检索（兼容新旧版 API） |
| `count() -> int` | 向量总数 |
| `delete_collection()` / `get_collection_info()` | Collection 管理 |

**装饰器**：`retry_on_failure(max_retries=3, delay=2, backoff=2)`（指数退避）。
**工具函数**：`fix_vector_format(vector)`（修复 numpy/二维向量，补零至 768 维）。
**单例**：`get_qdrant_client()`。

#### 5.6.6 embedder.py — BGE 嵌入模型

**路径**：[backend/services/embedder.py](file:///d:/log-qa-system/backend/services/embedder.py)

| 类常量 | 值 |
|--------|-----|
| `MODEL_NAME` | `BAAI/bge-base-zh-v1.5` |
| `VECTOR_SIZE` | 768 |
| `MAX_BATCH_SIZE` | 32 |

**`BGEEmbedder` 关键方法**：

| 方法 | 说明 |
|------|------|
| `__init__(model_name, device)` | 自动选择 cuda/cpu，从 ModelScope 下载或加载本地缓存 |
| `encode(texts, normalize=True, show_progress=False) -> np.ndarray` | 批量编码，返回 (n, 768) |
| `encode_single(text, normalize=True) -> np.ndarray` | 单条编码，返回 (768,) |
| `encode_batch(texts, batch_size=32, ...)` | 分批编码并 `np.vstack` 合并 |
| `get_vector_size() -> int` | 返回 768 |
| `is_available() -> bool` | 模型是否就绪 |

**单例**：`get_embedder()`。

#### 5.6.7 llm_client.py — DeepSeek LLM 客户端

**路径**：[backend/services/llm_client.py](file:///d:/log-qa-system/backend/services/llm_client.py)

**数据类**：`DeepSeekConfig`、`ChatMessage`（role, content）、`ChatResponse`（含 `from_api_response` 类方法）。

**`DeepSeekClient` 关键方法**：

| 方法 | 说明 |
|------|------|
| `__init__(config)` | 校验 API Key |
| `_get_client() -> httpx.Client` | 懒加载 HTTP 客户端（连接池） |
| `_build_request_body(messages, stream, **kwargs)` | 构造请求体 |
| `_handle_api_error(error, attempt) -> bool` | 判断是否可重试（超时/连接错误/429/5xx） |
| `chat(messages, **kwargs) -> ChatResponse` | ★ 同步聊天（含指数退避重试，最多 3 次） |
| `chat_stream(messages, **kwargs) -> Generator[str]` | ★ 流式聊天（SSE 解析 `[DONE]`） |
| `close()` | 关闭 HTTP 客户端 |

**便捷函数**：`get_simple_response(prompt, ...)`、`stream_response(prompt, ...)`。

#### 5.6.8 prompt_templates.py — Prompt 模板

**路径**：[backend/services/prompt_templates.py](file:///d:/log-qa-system/backend/services/prompt_templates.py)

| 方法 | 说明 |
|------|------|
| `PromptTemplates.SYSTEM_PROMPT` | 系统提示词（"你是日志分析助手..."） |
| `evidence_chain_prompt(question, context, chat_history)` | ★ 证据链 Prompt，强制输出五段式：【问题理解】【关键证据】【分析推断】【结论建议】【置信度】 |
| `quick_prompt(question, context)` | 最短快速问答 |
| `short_prompt(question, context)` | 简短问答 |
| `format_logs_as_context(logs)` | 日志列表格式化为紧凑上下文 |
| `format_chat_history(history)` | 格式化对话历史（仅保留最近 6 条） |

**便捷函数**：`build_qa_prompt(question, logs, history, template_type)`（统一入口）。

#### 5.6.9 chunker.py — 文本分块器

**路径**：[backend/services/chunker.py](file:///d:/log-qa-system/backend/services/chunker.py)

**数据类**：`Chunk`（text, chunk_id, start_char, end_char, metadata，`@dataclass(slots=True)`）。

**`LogChunker` 策略**：

| 策略常量 | 值 | 说明 |
|----------|-----|------|
| `STRATEGY_FIXED` | fixed | 固定窗口 |
| `STRATEGY_SENTENCE` | sentence | 句子优先 |
| `STRATEGY_HYBRID` | hybrid | 混合（生产推荐） |

默认 `chunk_size=256, overlap=50, min_chunk_size=20`，内置数字+单位保护（如 `120s`、`500ms` 不被切断）。

**关键方法**：`chunk_text(text, metadata)`、`chunk_logs_iter(logs, text_field)`（生成器，低内存）、`chunk_logs(logs, text_field)`。

#### 5.6.10 formatter.py — 检索结果格式化

**路径**：[backend/services/formatter.py](file:///d:/log-qa-system/backend/services/formatter.py)

**数据类**：`RetrievedLog`（log_id, level, service, timestamp, message, source, score），含 `to_dict()`、`to_markdown()`、`to_evidence()`。

**`ResultFormatter`（静态方法）**：`format_single`、`format_batch`、`to_dict_list`、`to_evidence_text`、`to_markdown_text`、`summarize`（统计 total/levels/services/avg/max/min score）。

**便捷函数**：`format_retrieval_results(...)`、`format_for_llm(results)`。

#### 5.6.11 log_parser.py — 日志解析器

**路径**：[backend/services/log_parser.py](file:///d:/log-qa-system/backend/services/log_parser.py)

**`LogParser`（全 `@classmethod`）**：

- `REQUIRED_FIELDS`：`["timestamp", "level", "service", "ip", "message", "trace_id"]`
- `VALID_LEVELS`：`{INFO, WARNING, ERROR, DEBUG}`
- `parse_line(log_dict) -> Tuple[bool, Optional[str]]`：校验单条日志
- `parse_csv(filepath, encoding) -> Tuple[valid_logs, failed_logs]`：解析 CSV
- `get_statistics(valid_logs, failed_logs)`：按 level/service 统计
- `save_failed_logs(failed_logs, output_path)`：保存失败日志

#### 5.6.12 log_cleaner.py — 日志清洗器

**路径**：[backend/services/log_cleaner.py](file:///d:/log-qa-system/backend/services/log_cleaner.py)

**`LogCleaner`（全 `@classmethod`）**：

- `normalize_level/timestamp/ip/message/trace_id`：单字段标准化
- `clean_single(log)`：单条全字段清洗
- `is_empty(log)`：判断空日志
- `deduplicate(logs) -> Tuple[logs, removed_count]`：按 `(timestamp, level, service, message)` 去重
- `clean_batch(logs) -> Dict`：批量清洗并返回统计
- `print_report(result)`：打印清洗报告

#### 5.6.13 nl2sql.py — 聚合类问题 NL2SQL 路径 ★

**路径**：[backend/services/nl2sql.py](file:///d:/log-qa-system/backend/services/nl2sql.py)

聚合/统计类问题（如"每个服务各多少条日志"、"最常见错误 Top 5"）不检索文档，而是直接在 SQLite `logs` 表上执行 SQL，避免 LLM 基于文档统计产生幻觉。由 `api/qa.py` 的 `detect_intent` 路由分发。

**模块常量**：

| 名称 | 说明 |
|------|------|
| `SCHEMA_HINT` | 提供给 LLM 的 logs 表 schema 提示（字段/索引/数据库） |
| `AGGREGATION_KEYWORDS` | 意图识别关键词列表（统计/数量/占比/Top N/最常见/各服务/按天/趋势/对比 等） |
| `FORBIDDEN_PATTERNS` | SQL 安全校验禁止模式（DROP/DELETE/UPDATE/INSERT/ALTER/CREATE/TRUNCATE 等、多语句、注释） |

**核心函数**：

| 函数 | 说明 |
|------|------|
| `detect_intent(question) -> "nl2sql" / "rag"` | 意图识别：命中聚合关键词返回 `nl2sql`，否则 `rag`（关键词匹配，零成本） |
| `generate_sql(question, llm_client) -> (sql, tokens)` | 调用 DeepSeek 生成 SQL（带 schema 提示 + 安全规则 + 示例），清理 markdown 标记、截断多语句、强制加 LIMIT |
| `validate_sql(sql) -> (is_valid, error_message)` | 安全校验：必须 SELECT 开头、不匹配禁止模式 |
| `execute_sql(sql, db_path="app.db") -> dict` | 以只读模式（`file:...?mode=ro`）执行 SQL，返回 columns/rows/row_count/execution_time/error |
| `format_sql_result(question, sql, result) -> str` | 格式化为五段式答案（与 evidence_chain 模板风格一致），含 SQL 代码块 + Markdown 表格 + 自然语言总结 |
| `_generate_summary(question, cols, rows, n)` | 从结果生成简短自然语言总结（标量/单行/分组分别处理） |
| `ask(question, db_path="app.db") -> QAResult` | ★ NL2SQL 路径入口：生成→校验→执行→格式化，返回 `retriever_type="nl2sql"` 的 `QAResult`（sources 为空，confidence="高"） |

> 设计要点：意图识别采用关键词匹配（快速零成本）；SQL 校验 + 只读模式连接双重保险防写操作；任何阶段失败都返回带 `confidence="低"` 的兜底 `QAResult`，不抛异常。

#### 5.6.14 reranker.py — Cross-Encoder 重排序 ★

**路径**：[backend/services/reranker.py](file:///d:/log-qa-system/backend/services/reranker.py)

基于 BAAI/bge-reranker-base 的 Cross-Encoder 精排器。双塔检索（BGE 向量点积）速度快但精度有限，Cross-Encoder 将 `[query, doc]` 拼接联合编码可捕捉细粒度交互。典型用法：双塔/BM25 取 Top-N（N=20）后用 Cross-Encoder 重排到 Top-K（K=5）。

| 类常量 | 值 |
|--------|-----|
| `MODEL_NAME` | `BAAI/bge-reranker-base`（约 1.1GB，中文优化） |
| `LOCAL_MODEL_ROOT` | `./models_cache/models/BAAI--bge-reranker-base/snapshots/master` |

**`Reranker` 关键方法**：

| 方法 | 说明 |
|------|------|
| `__init__(model_name, device)` | 自动选 cuda/cpu，优先加载本地快照，否则从 ModelScope 下载 |
| `rerank(query, docs, top_k=5, content_field="content") -> List[dict]` | 对文档列表打分排序，返回 Top-K 并注入 `rerank_score` / 保留 `original_score` |
| `is_available() -> bool` | 模型是否就绪 |

**单例**：`get_reranker() -> Reranker`。

> 说明：重排序器为可选组件，目前未在 `_build_pipeline` 默认链路中启用，主要用于离线评估与消融实验。`rerank()` 会将 service/level 拼接到文档内容前以提升重排质量。

#### 5.6.15 quality_checker.py — 回答质量自检

**路径**：[backend/services/quality_checker.py](file:///d:/log-qa-system/backend/services/quality_checker.py)

| 类 | 说明 |
|----|------|
| `QualityCheckResult` (dataclass) | passed, score, issues, warnings, suggestions |
| `QualityChecker` | 质量检查器，注册 6 个子检查器 |
| `QualityAwarePipeline` | 包装 `QAPipeline` 自动质量检查 |

**`QualityChecker` 子检查**（初始 100 分，问题扣分，≥70 且无 issue 即通过）：

1. `_check_source_citation`：来源引用格式检查
2. `_check_hallucination_patterns`：幻觉模式检测（"通常"、"一般来说"等）
3. `_check_confidence_alignment`：置信度与证据匹配
4. `_check_evidence_sufficiency`：证据充分性
5. `_check_reasoning_consistency`：逻辑矛盾检测
6. `_check_section_completeness`：四段完整性检查

**便捷函数**：`create_quality_pipeline(...)`、`calculate_self_check_pass_rate(results)`。

#### 5.6.16 error_handler.py — 异常处理

**路径**：[backend/services/error_handler.py](file:///d:/log-qa-system/backend/services/error_handler.py)

| 类 | 说明 |
|----|------|
| `ErrorResponse` (dataclass) | success, error_code, message, suggestions, details |
| `ErrorHandler` | 统一错误处理器，按异常类型分发到 8 个私有处理方法 |
| `RobustQAPipeline` | 包装 `QAPipeline` 自动处理异常 |

**`ErrorHandler.handle(error, context)`** 分发：`NoSearchResultsError`→建议放宽条件；`LLMTimeoutError`→建议重试；`LLMServiceError`→检查 API Key；`RetrieverError`→建议切换检索方式；`InvalidQueryError`→建议输入具体问题；`RateLimitError`→建议等待；`ConversationNotFoundError`；`QASystemError`；未知异常兜底。

**装饰器**：`handle_errors(fallback_message, log_error)`。
**便捷函数**：`create_robust_pipeline(top_k, retriever_type, template_type, timeout)`。

#### 5.6.17 exceptions.py — 自定义异常

**路径**：[backend/services/exceptions.py](file:///d:/log-qa-system/backend/services/exceptions.py)

异常继承链：

```
QASystemError(Exception)                      # 基础异常，error_code="QA_ERROR"
├── NoSearchResultsError                      # 检索无结果
├── LLMTimeoutError                           # LLM 超时
├── LLMServiceError                           # LLM 服务异常
├── RetrieverError                            # 检索器异常
├── InvalidQueryError                         # 无效查询
├── RateLimitError                            # 限流（retry_after）
└── ConversationNotFoundError                 # 对话不存在
```

每个异常均带 `message`、`error_code`、`details` 属性。

---

### 5.7 脚本层 scripts/

脚本层分为两类：运维数据脚本（导入/向量化/生成日志）与功能测试脚本（针对 services 和 api 层的端到端验证）。

**运维/数据脚本**：

| 脚本 | 用途 | 运行方式 |
|------|------|----------|
| `import_logs.py` | 将 `logs_cleaned.csv` 批量导入 SQLite，按 (message, service) 去重，支持 `--csv/--batch-size/--stats/--clear` | `python scripts/import_logs.py` |
| `batch_vectorize.py` | 从 DB 读取日志→分块→向量化→写入 Qdrant，支持断点续传（`vectorize_checkpoint.json`，每 30s 存档）、重建、干跑 | `python scripts/batch_vectorize.py --rebuild` |
| `generate_logs.py` | 生成 10000 条模拟日志到 `logs.csv`（5 个服务、4 个级别） | `python scripts/generate_logs.py` |
| `check_db.py` | 列出 SQLite 表名（注意：写死 `logs.db`，与默认 `app.db` 不同，详见第 12 章） | `python scripts/check_db.py` |
| `debug_bm25.py` | 调试 BM25 分词与匹配效果 | `python scripts/debug_bm25.py` |
| `visualize_retrieval.py` | 三种检索（向量/BM25/混合）结果对比可视化（ANSI 彩色） | `python scripts/visualize_retrieval.py` |

**功能测试脚本**（直接 `python scripts/test_*.py` 运行，无需 pytest）：

| 脚本 | 验证内容 |
|------|----------|
| `test_admin_view_conversation.py` | admin 查看他人会话详情、普通用户越权访问返回 404 |
| `test_role_security.py` | 角色权限安全：非 admin 调管理接口返回 403、admin 不能改自己角色/删自己/删最后一个 admin |
| `test_feedback_stats.py` | 反馈统计接口、scope=all 降级、like_rate 计算、top_disliked 返回 |
| `test_multi_turn.py` | 多轮对话：conversation_id 复用、历史加载、跨用户越权新建会话 |
| `test_qa_pipeline.py` | QAPipeline 端到端问答、来源标注 |
| `test_quality_check.py` | QualityChecker 各子检查器 |
| `test_source_tracking.py` | 来源引用解析（保留脚本，对应服务已合并到 QAPipeline） |
| `test_error_handling.py` | RobustQAPipeline 异常兜底 |
| `test_bm25.py` / `test_hybrid.py` / `test_retrieval.py` | 各检索器功能 |
| `test_cleaner.py` / `test_parser.py` / `test_formatter.py` | 数据处理组件 |
| `test_llm.py` | DeepSeekClient 调用 |
| `test_performance.py` | 性能测试 |

### 5.8 评估模块 evaluation/ ★

**路径**：[backend/evaluation/](file:///d:/log-qa-system/backend/evaluation/)

新增的 RAGAS 评估框架，用于量化问答质量并指导检索/Prompt 参数调优。结论已反哺生产配置（`_build_pipeline` 的 OPT2 权重即来自此处消融实验）。

**模块结构**：

| 路径 | 说明 |
|------|------|
| `eval_core.py` | 评估核心逻辑：对测试集逐条跑 QAPipeline，收集 QAResult 与检索证据 |
| `ragas_config.py` | RAGAS 评估指标配置（faithfulness / answer_relevancy / context_precision / context_recall 等） |
| `testset_loader.py` | 加载 `data/testset.json`（60 条标注 QA，含 question / ground_truth / expected_sources） |
| `data/testset.json` | 60 条人工标注 QA 测试集 |
| `data/ablation_*.json` / `*_raw.jsonl` | 各消融配置的评估结果（A0~A5 / OPT / OPT2） |
| `data/ablation_summary.json` | 消融实验汇总 |
| `docs/` | 评估报告与设计文档（`ablation_design.md` / `baseline_analysis.md` / `optimization_report_v2.md` / `reports/ablation_*.md`） |
| `scripts/run_baseline.py` | 基线评估 |
| `scripts/run_ablation.py` | 消融实验主脚本（A0~A5 + OPT/OPT2） |
| `scripts/eval_split.py` | 分路径评估（vector / bm25 / hybrid / nl2sql） |
| `scripts/build_testset.py` | 测试集构建脚本 |
| `scripts/test_ragas.py` | RAGAS 集成验证 |

**消融实验配置**（`data/ablation_summary.json` 汇总）：

- A0~A5：检索器组合、权重、是否重排序、Prompt 模板等单变量对照
- OPT / OPT2：综合最优配置，其中 **OPT2（vector_weight=1.0 / bm25_weight=2.0）** 在日志检索场景下 `context_precision` / `answer_relevancy` 最优，已采纳为生产默认配置

**运行方式**：

```bash
cd backend
python -m evaluation.scripts.run_baseline          # 基线评估
python -m evaluation.scripts.run_ablation          # 全量消融实验
python -m evaluation.scripts.eval_split            # 分路径评估
```

---

### 5.9 测试层 tests/

**pytest 配置**（`pytest.ini`）：

- `testpaths = tests`，匹配 `test_*.py` / `Test*` 类 / `test_*` 函数
- markers：`unit`、`integration`（需 `INTEGRATION_TEST=true`）、`slow`（需 `RUN_SLOW_TESTS=true`）、`performance`、`smoke`

**`conftest.py` fixtures**：`embedder`(session)、`qdrant_client`(session)、`retriever`(function)、`sample_logs`、`test_queries`。

| 测试文件 | 内容 |
|----------|------|
| `test_auth.py` | 注册/登录/JWT/密码哈希/审计日志/User 模型，使用 SQLite 内存库 + 事务回滚隔离 |
| `test_qa_pipeline_unit.py` | QAPipeline 初始化/QAResult/StreamChunk/异常/RobustPipeline/集成(@integration)/性能(@performance) |
| `test_qdrant_connection.py` | Qdrant 连通性验证（脚本式） |
| `test_retrieval.py` | 向量/BM25/混合检索 + Formatter 综合测试，无数据时 `pytest.skip` |
| `test_retriever.py` | `LogRetriever` 向量检索单元测试（含性能 < 300ms 断言） |

**运行示例**：

```bash
cd backend
pytest tests/ -v                                  # 全部
pytest tests/test_qa_pipeline_unit.py -m "not integration"   # 跳过集成
pytest tests/test_qa_pipeline_unit.py -m integration          # 仅集成
INTEGRATION_TEST=true pytest tests/ -m integration              # 启用集成
```

---

### 5.9 工具层 utils/

- `utils/__init__.py`、`utils/logger.py`：**均为空文件**。当前各模块通过 `logging.basicConfig` 局部配置 logger，未使用统一日志工具。

---

### 5.11 数据文件 data/

- `logs.csv` / `logs_cleaned.csv`：列结构 `timestamp, level, service, ip, message, trace_id`
- 服务：`auth-service`、`order-service`、`payment-service`、`user-service`、`notification-service`
- `trace_id` 为 8 位十六进制短 ID

---

## 6. 前端模块详解

### 6.1 入口与路由

**入口** [frontend/src/main.jsx](file:///d:/log-qa-system/frontend/src/main.jsx)：`ReactDOM.createRoot` 挂载 `<App />`，包裹 `React.StrictMode`。

**路由** [frontend/src/App.jsx](file:///d:/log-qa-system/frontend/src/App.jsx)：

```
BrowserRouter
└─ AuthProvider
   └─ Routes
      ├─ /login         → <Login />
      ├─ /register      → <Register />
      ├─ /dashboard      → <ProtectedRoute><Dashboard /></ProtectedRoute>
      ├─ /admin/users    → <ProtectedRoute><AdminRoute><UserManagement /></AdminRoute></ProtectedRoute>
      └─ /              → <Navigate to="/dashboard" replace />
```

### 6.2 API 层

**[api/client.js](file:///d:/log-qa-system/frontend/src/api/client.js)**：axios 实例 `apiClient`
- `baseURL`：`import.meta.env.VITE_API_BASE_URL`
- `timeout`：30000ms
- **请求拦截器**：从 `localStorage` 读 `access_token`，自动加 `Authorization: Bearer`
- **响应拦截器**：401 时清 `access_token`/`user` 并跳转 `/login`

**[api/auth.js](file:///d:/log-qa-system/frontend/src/api/auth.js)**：认证 + 用户管理 + 改密 API 封装

| 函数 | 端点 |
|------|------|
| `register(username, password)` | POST `/api/auth/register` |
| `login(username, password)` | POST `/api/auth/login` |
| `getCurrentUser()` | GET `/api/auth/me` |
| `changePassword(old, new)` | POST `/api/auth/me/password` |
| `getAllUsers(username?)` | GET `/api/auth/users`（admin） |
| `setUserRole(userId, role)` | PATCH `/api/auth/users/{id}/role`（admin） |
| `deleteUser(userId)` | DELETE `/api/auth/users/{id}`（admin） |
| `logout()` | 本地清理（不调后端） |

**[api/qa.js](file:///d:/log-qa-system/frontend/src/api/qa.js)**：★ 问答 API 封装

| 函数 | 端点 | 说明 |
|------|------|------|
| `askQuestion(params)` | POST `/api/qa/ask` | 同步问答，返回 `QAResponse`（含 `conversation_id`） |
| `askStreamQuestion(params, handlers)` | POST `/api/qa/ask/stream` | ★ SSE 流式问答：用原生 `fetch` + `ReadableStream` 消费，回调 `onSource` / `onAnswer` / `onDone` / `onError`；axios 对流式响应支持不佳故单独用 fetch |
| `getHistoryList(params)` | GET `/api/qa/history` | 历史列表（分页 / keyword / feedback） |
| `getHistoryDetail(id)` | GET `/api/qa/history/{id}` | 单条历史详情 |
| `submitFeedback(qaId, feedback)` | POST `/api/qa/feedback/{qaId}` | 点赞/点踩/取消 |
| `getConversations()` | GET `/api/qa/conversations` | 会话列表 |
| `getConversationDetail(id)` | GET `/api/qa/conversations/{id}` | 会话详情（完整多轮） |
| `deleteConversation(id)` | DELETE `/api/qa/conversations/{id}` | 删除会话 |
| `getFeedbackStats(params)` | GET `/api/qa/feedback/stats` | 反馈统计（scope=me/all） |

> 内部 `_parseSseEvent(block)`：按 SSE 协议解析单个事件块（`event:` / `data:` 行），返回 `{type, data}`。

### 6.3 状态管理

**[context/AuthContext.jsx](file:///d:/log-qa-system/frontend/src/context/AuthContext.jsx)**：全局认证 Context
- State：`user`、`loading`、`error`
- 初始化时从 `localStorage` 恢复 token 并调 `getCurrentUser()` 校验
- `login(username, password)`：调 API，存 token 到 localStorage，构造 user 对象
- `register(username, password)`、`logout()`
- 暴露：`{ user, loading, error, login, register, logout, isAuthenticated }`
- 自定义 Hook：`useAuth()`（在 Provider 外使用抛错）

### 6.4 路由守卫

**[components/ProtectedRoute.jsx](file:///d:/log-qa-system/frontend/src/components/ProtectedRoute.jsx)**：
- `loading` 时显示加载动画
- 未认证 → `<Navigate to="/login" replace />`
- 已认证 → 渲染 `children`

**[components/AdminRoute.jsx](file:///d:/log-qa-system/frontend/src/components/AdminRoute.jsx)**：★ admin 角色守卫
- 非 admin 用户 → 跳转 `/dashboard`（或显示无权限提示）
- admin → 渲染 `children`
- 配合 `ProtectedRoute` 嵌套使用，先验证登录再验证角色

### 6.5 组件

| 组件 | 路径 | 说明 |
|------|------|------|
| `Chat` | [components/Chat.jsx](file:///d:/log-qa-system/frontend/src/components/Chat.jsx) | ★ 核心问答界面：SSE 流式输出（调 `askStreamQuestion`）、来源卡片展示、点赞/点踩反馈按钮、质量自检结果显示、多轮上下文（携带 `conversation_id`） |
| `ConversationSidebar` | [components/ConversationSidebar.jsx](file:///d:/log-qa-system/frontend/src/components/ConversationSidebar.jsx) | ★ 会话列表侧边栏：展示历史会话、切换/删除会话、新建会话 |
| `ChangePasswordModal` | [components/ChangePasswordModal.jsx](file:///d:/log-qa-system/frontend/src/components/ChangePasswordModal.jsx) | ★ 修改密码弹窗（验证旧密码 + 新密码确认） |
| `ProtectedRoute` | [components/ProtectedRoute.jsx](file:///d:/log-qa-system/frontend/src/components/ProtectedRoute.jsx) | 通用路由守卫（见 6.4） |
| `AdminRoute` | [components/AdminRoute.jsx](file:///d:/log-qa-system/frontend/src/components/AdminRoute.jsx) | admin 角色守卫（见 6.4） |

### 6.6 页面

| 页面 | 状态 | 说明 |
|------|------|------|
| [Login.jsx](file:///d:/log-qa-system/frontend/src/pages/Login.jsx) | 完成 | 登录表单，页脚提示测试账号 `admin / admin123` |
| [Register.jsx](file:///d:/log-qa-system/frontend/src/pages/Register.jsx) | 完成 | 注册表单（用户名≥3、密码≥6、确认密码），成功后跳登录 |
| [Dashboard.jsx](file:///d:/log-qa-system/frontend/src/pages/Dashboard.jsx) | 完成 | 主问答界面：顶部用户名/角色/登出 + 改密入口；主体为 `<Chat />` + `<ConversationSidebar />` 组合 |
| [UserManagement.jsx](file:///d:/log-qa-system/frontend/src/pages/UserManagement.jsx) | 完成 | ★ 管理员用户管理界面（admin 专属）：用户列表 + 模糊搜索 + 改角色 + 删用户 |

### 6.7 构建配置

**[vite.config.js](file:///d:/log-qa-system/frontend/vite.config.js)**：仅启用 `@vitejs/plugin-react`，未配置端口/代理/别名。跨域由后端 CORS 解决。

**package.json scripts**：`dev`（vite）、`build`（vite build）、`lint`（oxlint）、`preview`（vite preview）。

---

## 7. 核心数据流与处理流程

### 7.1 数据入库流程（离线）

```
1. generate_logs.py        → 生成 logs.csv（10000 条模拟日志）
2. (手动清洗)              → logs_cleaned.csv
3. import_logs.py          → 去重导入 SQLite app.db 的 logs 表
4. batch_vectorize.py      →
     ├─ fetch_logs_from_db（分页读取 + 修复 source 字段）
     ├─ LogChunker.chunk_logs（hybrid 策略，chunk_size=256, overlap=50）
     ├─ BGEEmbedder.encode_batch（向量化，768 维）
     └─ QdrantClientWrapper.upsert_vectors（写入 Qdrant，含 payload）
        ├─ 每 30s 保存 vectorize_checkpoint.json
        └─ 支持 --resume 断点续传 / --rebuild 重建
```

### 7.2 问答流程（在线）

```
用户提问（POST /api/qa/ask 或 /api/qa/ask/stream）
  │
  ▼
api/qa.py 路由层
  │
  ├─ 0. 解析会话 ID（_resolve_conversation_id）
  │     ├─ 传 conversation_id 且属于当前用户 → 复用
  │     └─ 不传 / 越权 → 新建 conv_<uuid4_hex[:16]>
  │
  ├─ 1. 从 DB 加载多轮历史（_load_conversation_history，最近 5 轮）
  │
  ├─ 2. 意图路由（services.nl2sql.detect_intent）
  │     ├─ 聚合/统计类 → NL2SQL 路径：
  │     │     ├─ generate_sql（DeepSeek 生成 SQL + schema 提示）
  │     │     ├─ validate_sql（禁写校验 + 强制 LIMIT）
  │     │     ├─ execute_sql（只读模式连 app.db logs 表）
  │     │     └─ format_sql_result（五段式答案 + Markdown 表格）
  │     │     → 返回 retriever_type="nl2sql" 的 QAResult（无 sources）
  │     │
  │     └─ 其他问题 → RAG 路径（_build_pipeline → RobustQAPipeline.ask）
  │           ├─ 检索（HybridRetrieverAsync.search）
  │           │     ├─ asyncio.gather 并行：
  │           │     │   ├─ LogRetriever.search（BGE 向量化 → Qdrant 检索）
  │           │     │   └─ BM25Retriever.search（jieba 分词 → BM25Okapi）
  │           │     ├─ RRF 融合：rrf_score = w_v/(k+rank_v) + w_b/(k+rank_b)
  │           │     │   （OPT2 默认 w_v=1.0 / w_b=2.0）
  │           │     └─ 按 rrf_score 排序取 Top-K
  │           ├─ 截断过长日志（max_log_length=300）
  │           ├─ 构造 Prompt（build_qa_prompt, evidence_chain 模板）
  │           │     ├─ SYSTEM_PROMPT
  │           │     ├─ format_chat_history（DB 加载的历史）
  │           │     └─ format_logs_as_context（日志列表）
  │           ├─ 调用 LLM（DeepSeekClient.chat / chat_stream）
  │           ├─ 提取来源（_extract_source_refs：[ID:xxx] → 匹配日志 → [n]）
  │           ├─ 标注回答（_annotate_answer_with_refs：[ID:xxx] → [n]）
  │           └─ 估计置信度（_estimate_confidence：高/中/低）
  │           （异常时 RobustQAPipeline 兜底返回 confidence="低" 的 QAResult）
  │
  ├─ 3. 质量自检（_run_quality_check，QualityChecker）
  │     → 6 个子检查：来源引用 / 幻觉模式 / 置信度对齐 / 证据充分 / 逻辑一致 / 分段完整
  │
  ├─ 4. 持久化 QAHistory（含 conversation_id + quality_check JSON）+ 审计日志
  │
  └─ 返回 QAResponse
        ├─ answer（带 [n] 标注）
        ├─ sources（QASourceRef 列表）
        ├─ confidence / retriever_type / total_tokens
        ├─ qa_id / conversation_id
        ├─ quality_check
        └─ retrieval_time / llm_time / total_time
        （兜底时 success=False + error 字段，HTTP 仍 200）
```

### 7.3 认证流程

```
登录：
  Login.jsx → AuthContext.login → POST /api/auth/login
    → 后端 verify_password → create_access_token
    → 返回 {access_token, username, role, user_id}
    → 存 localStorage → 跳 /dashboard

请求：
  axios 请求拦截器 → 自动加 Authorization: Bearer <token>

校验：
  应用初始化 → AuthContext.useEffect
    → 从 localStorage 取 token → GET /api/auth/me
    → 有效则设置 user，无效则清存储

登出：
  POST /api/auth/logout（记审计日志）→ 清 localStorage
  或 401 响应拦截器 → 自动清存储 + 跳 /login
```

---

## 8. 关键类与函数索引

### 8.1 后端核心类索引

| 类名 | 文件 | 职责 |
|------|------|------|
| `Settings` | core/config.py | 应用配置 |
| `User` / `UserRole` | models/user.py | 用户模型 |
| `Log` | models/log.py | 日志模型 |
| `QAHistory` / `FeedbackType` | models/qa_history.py | 问答历史 |
| `AuditLog` | models/audit_log.py | 审计日志 |
| `QAPipeline` | services/qa_pipeline.py | ★ 问答流水线编排 |
| `QAResult` / `SourceReference` / `StreamChunk` | services/qa_pipeline.py | 问答结果数据类 |
| `HybridRetrieverAsync` / `HybridResult` | services/hybrid_retriever.py | ★ 混合检索 |
| `LogRetriever` / `RetrievalResult` | services/retriever.py | 向量检索 |
| `BM25Retriever` / `BM25Result` | services/bm25_retriever.py | BM25 检索 |
| `QdrantClientWrapper` | services/qdrant_client.py | Qdrant 客户端 |
| `BGEEmbedder` | services/embedder.py | 嵌入模型 |
| `DeepSeekClient` / `ChatMessage` / `ChatResponse` | services/llm_client.py | LLM 客户端 |
| `LogChunker` / `Chunk` | services/chunker.py | 文本分块 |
| `ResultFormatter` / `RetrievedLog` | services/formatter.py | 结果格式化 |
| `LogParser` | services/log_parser.py | 日志解析 |
| `LogCleaner` | services/log_cleaner.py | 日志清洗 |
| `Reranker` | services/reranker.py | ★ Cross-Encoder 重排序（可选） |
| `QualityChecker` / `QualityAwarePipeline` | services/quality_checker.py | 质量自检 |
| `ErrorHandler` / `RobustQAPipeline` | services/error_handler.py | 异常处理 |
| `QASystemError` 及子类 | services/exceptions.py | 自定义异常 |

> 说明：`detect_intent` / `generate_sql` / `validate_sql` / `execute_sql` / `format_sql_result` / `ask` 等 NL2SQL 函数定义在 `services/nl2sql.py`（模块级函数，非类）。早期 `services/conversation.py` 的 `ConversationBufferMemory` / `ConversationAwarePipeline` 与 `services/source_tracking.py` 的 `SourceTracker` / `SourceAwareQAPipeline` 已删除（2026-07-26），多轮对话改用 DB `qa_history.conversation_id`，来源溯源合并到 `QAPipeline` 内部。

### 8.2 单例函数索引

| 函数 | 返回 | 文件 |
|------|------|------|
| `get_retriever()` | `LogRetriever` | services/retriever.py |
| `get_bm25_retriever(corpus, cache_path)` | `BM25Retriever` | services/bm25_retriever.py |
| `get_qdrant_client()` | `QdrantClientWrapper` | services/qdrant_client.py |
| `get_embedder()` | `BGEEmbedder` | services/embedder.py |
| `get_hybrid_retriever_async(...)` | `HybridRetrieverAsync` | services/hybrid_retriever.py |
| `get_reranker()` | `Reranker` | services/reranker.py |

### 8.3 工厂函数索引

| 函数 | 返回 |
|------|------|
| `create_pipeline(...)` | `QAPipeline` |
| `create_quality_pipeline(...)` | `QualityAwarePipeline` |
| `create_robust_pipeline(...)` | `RobustQAPipeline`（★ 生产路径使用，`api/qa.py._build_pipeline` 调用） |

> 已废弃：`create_conversation_pipeline` / `create_source_aware_pipeline`（对应服务文件已删除）。

### 8.4 前端核心组件/Hook 索引

| 名称 | 文件 | 职责 |
|------|------|------|
| `App` | App.jsx | 根组件 + 路由（含 /admin/users） |
| `AuthProvider` / `useAuth` | context/AuthContext.jsx | 全局认证状态 |
| `ProtectedRoute` | components/ProtectedRoute.jsx | 通用路由守卫（已登录） |
| `AdminRoute` | components/AdminRoute.jsx | ★ admin 角色守卫 |
| `Chat` | components/Chat.jsx | ★ SSE 流式问答界面 |
| `ConversationSidebar` | components/ConversationSidebar.jsx | ★ 会话列表侧边栏 |
| `ChangePasswordModal` | components/ChangePasswordModal.jsx | ★ 改密弹窗 |
| `Login` / `Register` / `Dashboard` / `UserManagement` | pages/ | 页面（UserManagement 为 admin 专属） |
| `apiClient` | api/client.js | axios 实例 |
| `login/register/getCurrentUser/logout/changePassword/getAllUsers/setUserRole/deleteUser` | api/auth.js | 认证 + 用户管理 + 改密 API |
| `askQuestion/askStreamQuestion/getHistoryList/getHistoryDetail/submitFeedback/getConversations/getConversationDetail/deleteConversation/getFeedbackStats` | api/qa.js | ★ 问答 API 封装 |

---

## 9. 依赖关系总览

### 9.1 后端模块依赖图

```
main.py
  ├─ api.auth ──┬─ core.database (get_db)
  │             ├─ core.security (JWT/bcrypt)
  │             ├─ models.user / models.audit_log / models.qa_history
  │             └─ schemas.auth
  ├─ api.qa ───┬─ core.database (get_db)
  │            ├─ api.auth (get_current_user / log_audit)
  │            ├─ models.qa_history / models.user
  │            ├─ schemas.qa
  │            ├─ services.qa_pipeline (QAResult)
  │            ├─ services.error_handler (create_robust_pipeline / RobustQAPipeline)
  │            ├─ services.quality_checker (QualityChecker)
  │            └─ services.nl2sql (detect_intent / ask)  ← 延迟导入
  └─ (warmup) services.embedder / bm25_retriever / qdrant_client / hybrid_retriever

services.qa_pipeline
  ├─ services.llm_client (DeepSeekClient)
  ├─ services.prompt_templates (build_qa_prompt)
  ├─ services.retriever (LogRetriever)        ──┐
  ├─ services.bm25_retriever (BM25Retriever)    │
  └─ services.hybrid_retriever ─────────────────┤
                                                │
services.nl2sql
  ├─ services.llm_client (DeepSeekClient)
  ├─ services.qa_pipeline (QAResult)
  └─ sqlite3 (只读连 app.db logs 表)

services.hybrid_retriever                       │
  ├─ services.retriever ────────────────────────┤
  ├─ services.bm25_retriever ──────────────────┤
  └─ services.formatter                        │
                                                │
services.retriever                              │
  ├─ services.embedder (BGEEmbedder)            │
  ├─ services.qdrant_client ───────────────────┘
  ├─ services.formatter
  └─ core.config

services.reranker（可选，未默认启用）
  ├─ sentence_transformers (CrossEncoder)
  ├─ torch
  └─ modelscope (模型下载)

services.bm25_retriever
  ├─ jieba (中文分词)
  ├─ rank_bm25 (BM25Okapi)
  ├─ nltk (PorterStemmer)
  └─ pickle (索引缓存)

services.embedder
  ├─ sentence_transformers (SentenceTransformer)
  ├─ torch
  ├─ numpy
  └─ modelscope (模型下载)

services.llm_client
  └─ httpx (HTTP 客户端)

services.{quality_checker,error_handler}
  └─ services.qa_pipeline (延迟导入)

evaluation/（离线评估，独立模块）
  ├─ services.qa_pipeline / services.nl2sql
  ├─ ragas（评估指标）
  └─ scripts/run_*.py

外部服务：
  ├─ Qdrant 云（向量库，QDRANT_URL）
  └─ DeepSeek API（LLM，DEEPSEEK_BASE_URL）
```

> 已删除模块：`services/conversation.py`、`services/source_tracking.py`（2026-07-26 删除），原依赖关系不再生效。

### 9.2 数据库表关系

```
users (1) ──── (N) qa_history      [FK: qa_history.user_id → users.id]
users (1) ──── (N) audit_logs      [弱关联，无 FK，冗余 username]
logs                              [独立表，无外键]
```

### 9.3 前后端依赖

```
前端 axios / fetch ──HTTP/JWT──→ 后端 FastAPI
  /api/auth/register
  /api/auth/login
  /api/auth/me
  /api/auth/me/password
  /api/auth/logout
  /api/auth/users（admin）
  /api/auth/users/{id}/role（admin）
  /api/auth/users/{id}（admin）
  /api/qa/ask
  /api/qa/ask/stream（SSE，用 fetch）
  /api/qa/history
  /api/qa/history/{id}
  /api/qa/feedback/{qa_id}
  /api/qa/feedback/stats
  /api/qa/conversations
  /api/qa/conversations/{id}
```

---

## 10. 项目运行方式

### 10.1 环境准备

**后端**：

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
# 额外依赖（requirements.txt 未列出）
pip install jieba rank_bm25 nltk httpx modelscope
# 可选：启用 Cross-Encoder 重排序（评估场景）需 sentence_transformers 已装
# 可选：运行 evaluation/ 评估脚本需 pip install ragas
# 首次运行 nltk 会自动下载 punkt/stopwords
```

**前端**：

```bash
cd frontend
npm install
```

### 10.2 配置环境变量

在 `backend/` 下创建 `.env`（参考 [core/config.py](file:///d:/log-qa-system/backend/core/config.py)）：

```env
# DeepSeek LLM
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro   # 或 deepseek-v4-flash；deepseek-chat 已废弃

# Qdrant 向量库
QDRANT_URL=https://your-qdrant-cluster-url
QDRANT_API_KEY=your-qdrant-api-key
QDRANT_COLLECTION_NAME=log_knowledge   # 注：qdrant_client.py 默认 log_vectors，需在 .env 显式统一

# JWT
SECRET_KEY=your-secret-key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# 切片
LOG_CHUNK_SIZE=500
LOG_CHUNK_OVERLAP=50
```

在 `frontend/` 下创建 `.env`：

```env
VITE_API_BASE_URL=http://localhost:8000
```

> 提示：`docs/frontend/.env` 有示例可参考。`.gitignore` 会忽略 `.env`，但保留 `.env.example`。配置不一致问题详见第 12 章。

### 10.3 数据初始化

```bash
cd backend

# 1. 生成测试日志（可选，已有 logs.csv 可跳过）
python scripts/generate_logs.py

# 2. 清洗日志（手动或通过脚本，生成 logs_cleaned.csv）

# 3. 导入 SQLite
python scripts/import_logs.py                     # 默认导入 data/logs_cleaned.csv
python scripts/import_logs.py --stats             # 查看统计

# 4. 向量化并写入 Qdrant
python scripts/batch_vectorize.py --rebuild       # 首次需重建 Collection
python scripts/batch_vectorize.py --resume        # 断点续传（默认）
```

### 10.4 启动服务

**后端**（在 `backend/` 目录）：

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- API 文档（Swagger）：`http://localhost:8000/docs`
- 健康检查：`http://localhost:8000/health`

**前端**（在 `frontend/` 目录）：

```bash
npm run dev          # 开发服务器，默认 http://localhost:5173
npm run build        # 生产构建到 dist/
npm run preview      # 预览构建产物
```

### 10.5 测试账号

登录页提示测试账号：`admin / admin123`（需先通过注册接口创建）。

### 10.6 运行测试

```bash
cd backend
pytest tests/ -v                                  # 全部单元测试
pytest tests/test_auth.py -v                      # 认证测试
pytest tests/ -m "not integration"                # 跳过集成测试
INTEGRATION_TEST=true pytest tests/ -m integration # 启用集成测试（需 Qdrant 数据）
```

> 注：检索相关测试在 Qdrant 无数据时会 `pytest.skip`，需先运行 `batch_vectorize.py` 入库。

### 10.7 调试与可视化工具

```bash
python scripts/check_db.py              # 检查数据库表
python scripts/debug_bm25.py             # 调试 BM25 分词
python scripts/visualize_retrieval.py    # 三种检索结果对比（交互式）
```

---

## 11. 环境变量配置

### 11.1 后端环境变量

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `DEEPSEEK_API_KEY` | (空) | DeepSeek API 密钥（**必填**） |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | DeepSeek API 地址 |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | LLM 模型名（`deepseek-chat` 已废弃，应使用 `deepseek-v4-pro` 或 `deepseek-v4-flash`） |
| `QDRANT_URL` | (空) | Qdrant 集群地址（**必填**） |
| `QDRANT_API_KEY` | (空) | Qdrant API Key（**必填**） |
| `QDRANT_COLLECTION_NAME` | `log_knowledge` | Collection 名（注：qdrant_client.py 默认 `log_vectors`，**两处不一致**） |
| `SECRET_KEY` | `dev-secret-key` | JWT 密钥 |
| `ALGORITHM` | `HS256` | JWT 算法 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Token 过期时间 |
| `LOG_CHUNK_SIZE` | `500` | 日志切片大小 |
| `LOG_CHUNK_OVERLAP` | `50` | 切片重叠 |

### 11.2 前端环境变量

| 变量 | 用途 |
|------|------|
| `VITE_API_BASE_URL` | 后端 API 基础地址（如 `http://localhost:8000`） |

---

## 12. 已知问题与注意事项

### 12.1 权限与安全约束（硬约束）

以下硬约束源自项目内存（`project_memory.md`），在权限相关开发中必须严格遵守：

- **数据隔离**：用户只能访问自己的 QA 历史和反馈数据。`/api/qa/history`、`/api/qa/history/{id}`、`/api/qa/feedback/{qa_id}` 均通过 `QAHistory.user_id == current_user.id` 过滤，越权访问返回 404（不区分"不存在"与"不属于你"，避免泄露存在性）。
- **scope 降级**：非 admin 用户在 `/api/qa/conversations` 与 `/api/qa/feedback/stats` 使用 `scope=all` 时，自动降级为 `scope=me`（不报错，静默降级）。
- **会话详情越权**：非 admin 用户访问他人会话详情返回 404；admin 可访问任意会话详情，响应中额外返回 `owner_username` 便于识别归属。
- **角色管理**：admin 不能修改自己的角色（避免唯一管理员被降级后无人管理）。
- **用户删除**：用户不能删除自己；最后一个 admin 不能被删除（避免无人管理系统）；删除用户时级联删除其 `qa_history` 记录，但保留 `audit_log` 便于追溯。
- **注册角色固定**：前端注册固定为 `user` 角色，注册接口（`POST /api/auth/register`）的 `role` 入参被服务端强制忽略。
- **统一错误响应**：错误响应统一返回 HTTP 200 + `success=false`，不抛 5xx（`RobustQAPipeline` 兜底）；鉴权类错误（401/403/404/422）仍走标准 HTTP 状态码。

### 12.2 配置不一致

- **QDRANT_COLLECTION_NAME**：`core/config.py` 默认 `log_knowledge`，而 `services/qdrant_client.py` 默认 `log_vectors`，需在 `.env` 显式统一（生产建议 `log_knowledge`）。
- **DEEPSEEK_MODEL**：`core/config.py` 默认 `deepseek-v4-pro`，但 `llm_client.py` 的 `DeepSeekConfig` 历史默认 `deepseek-chat`。**`deepseek-chat` 已废弃**，应使用 `deepseek-v4-pro` 或 `deepseek-v4-flash`；以 `core/config.py` 的 `settings.DEEPSEEK_MODEL` 为准，确保在 `.env` 显式配置。
- **数据库路径**：实际 app DB 为 `backend/app.db`（不是 `log_qa.db` 或 `logs.db`）；`logs` 表内容字段名为 `message`（不是 `content`）。NL2SQL 的 `SCHEMA_HINT` 与 ORM 模型均使用 `message`，正确无误。

### 12.3 数据库文件不统一

- `scripts/check_db.py` 写死 `logs.db`，而 `core/database.py` 默认 `app.db`，两者指向不同数据库文件。运行 `check_db.py` 查看的是 `logs.db` 而非实际应用库 `app.db`，使用时需注意。

### 12.4 空文件 / 占位

- `models/conversation.py`：空占位文件（会话持久化已合并到 `qa_history.conversation_id`，无需独立模型）。
- `utils/__init__.py`、`utils/logger.py`：空文件，各模块通过 `logging.basicConfig` 局部配置 logger。
- `schemas/__init__.py`：空文件。
- `docs/API.md`、`docs/DEPLOY.md`、根 `README.md`：空文件。
- `frontend/src/App.css`：Vite 模板残留，未被业务使用。

### 12.5 依赖未列入 requirements.txt

`jieba`、`rank_bm25`、`nltk`、`httpx`、`modelscope` 需手动安装。运行 `evaluation/` 评估脚本需额外 `pip install ragas`。启用 `services/reranker.py` 需 `sentence_transformers`（已在 requirements.txt）+ `torch`，并下载 `BAAI/bge-reranker-base` 模型。

### 12.6 时间戳策略

所有 ORM 模型使用 Python 端 `datetime.now`，而非数据库端 `func.now()`，多实例部署可能产生时间偏差。

### 12.7 `docs/frontend/` 目录

存在一份与 `frontend/` 几乎相同的前端副本（含 `.env`），疑似开发快照，**实际使用的是根 `frontend/` 目录**。`docs/frontend/.env` 可作为配置参考，但不应作为运行目录。

### 12.8 检索测试数据依赖

多数检索测试需 Qdrant 有数据，否则 `pytest.skip`；集成测试需 `INTEGRATION_TEST=true`。功能测试脚本（`scripts/test_*.py`）多需后端服务运行中且已初始化数据。

### 12.9 CORS 配置

后端允许 `localhost:5173`、`localhost:5174`、`localhost:3000`，生产部署需调整。

### 12.10 已废弃模块

以下早期模块已删除（2026-07-26），相关文档描述如仍提及均为历史信息：

- `services/conversation.py`（`ConversationBufferMemory` / `ConversationAwarePipeline`）→ 多轮对话改由 DB `qa_history.conversation_id` 实现
- `services/source_tracking.py`（`SourceTracker` / `SourceAwareQAPipeline`）→ 来源溯源合并到 `QAPipeline` 内部
- 对应工厂函数 `create_conversation_pipeline` / `create_source_aware_pipeline` 同步废弃

> `scripts/test_source_tracking.py` 仍保留，用于验证来源引用解析逻辑（现由 `QAPipeline._extract_source_refs` 承担）。

---

> **文档结束**
>
> 本 Code Wiki 基于代码库静态分析生成。如需了解某模块的运行时行为，建议结合 `scripts/visualize_retrieval.py`、`scripts/debug_bm25.py` 等调试工具实际运行验证。
