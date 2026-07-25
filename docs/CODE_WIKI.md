# 日志智能问答系统 · Code Wiki

> 本文档是对 `log-qa-system` 项目仓库的结构化代码百科，涵盖项目整体架构、主要模块职责、关键类与函数说明、依赖关系以及项目运行方式等关键信息。
>
> 文档基于代码库静态分析生成，反映截至 2026-07-24 的代码状态。

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
  - [5.8 测试层 tests/](#58-测试层-tests)
  - [5.9 工具层 utils/](#59-工具层-utils)
  - [5.10 数据文件 data/](#510-数据文件-data)
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
- 用户认证与授权（JWT + RBAC）
- 日志数据解析、清洗、分块、向量化入库
- 混合检索（向量语义检索 + BM25 关键词检索 + RRF 融合重排）
- 基于 DeepSeek LLM 的证据链问答（含流式输出）
- 多轮对话记忆、来源溯源、回答质量自检、统一异常处理
- 审计日志记录

**技术栈速览**：

| 层 | 技术 |
|----|------|
| 后端框架 | FastAPI 0.104 + Uvicorn |
| ORM | SQLAlchemy 2.0（SQLite） |
| 认证 | JWT（python-jose） + bcrypt（passlib） |
| 向量数据库 | Qdrant（qdrant-client 1.7） |
| 嵌入模型 | BAAI/bge-base-zh-v1.5（sentence-transformers + PyTorch CPU） |
| 关键词检索 | rank_bm25（BM25Okapi） + jieba 中文分词 + NLTK 词干 |
| LLM | DeepSeek API（httpx 同步/流式） |
| 数据处理 | pandas |
| 前端框架 | React 19 + Vite 8 |
| 前端路由 | react-router-dom 7 |
| 前端 HTTP | axios |
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
│  │  api/auth.py  │   │  api/qa.py (占位，问答路由未接入)              │  │
│  │  注册/登录/me  │   └────────────────────────────────────────────┘  │
│  └──────┬───────┘                          │                          │
│         │                                   │                          │
│         ▼                                   ▼                          │
│  ┌──────────────┐            ┌──────────────────────────────┐        │
│  │ core/security│            │    services/qa_pipeline.py    │        │
│  │  JWT + bcrypt│            │     QAPipeline (编排核心)      │        │
│  └──────┬───────┘            └──┬─────────┬──────────┬──────┘        │
│         │                       │         │          │                │
│         ▼                       ▼         ▼          ▼                │
│  ┌──────────────┐   ┌──────────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ core/database │   │hybrid_retriev│ │llm_client│ │prompt_templates│ │
│  │  SQLAlchemy   │   │   RRF 融合    │ │ DeepSeek │ │  证据链模板    │  │
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
  ▼ HybridRetrieverAsync 并行检索
  │     ├─ LogRetriever（向量检索，Qdrant）
  │     └─ BM25Retriever（关键词检索，本地索引）
  ▼ RRF 融合重排（1/(k+rank)）
  ▼ PromptTemplates 构造证据链 Prompt
  ▼ DeepSeekClient 调用 LLM（同步 / 流式）
  ▼ SourceTracker 来源标注（[ID:xxx] → [n]）
  ▼ QualityChecker 质量自检（幻觉检测等）
  ▼ ErrorHandler 异常兜底
  ▼
  返回 QAResult（答案 + 来源 + 置信度 + 耗时）
```

### 2.3 装饰器式 Pipeline 增强

`QAPipeline` 为基础问答流水线，项目通过装饰器模式叠加四类增强能力，可自由组合：

```
RobustQAPipeline        ← 异常兜底（最外层）
  └─ QualityAwarePipeline   ← 质量自检
       └─ SourceAwareQAPipeline  ← 来源溯源
            └─ ConversationAwarePipeline  ← 多轮对话记忆
                 └─ QAPipeline  ← 基础流水线（检索+Prompt+LLM）
```

---

## 3. 目录结构

```
log-qa-system/
├── backend/                         # 后端 FastAPI 服务
│   ├── api/                         # API 路由层
│   │   ├── __init__.py
│   │   ├── auth.py                  # 认证路由（注册/登录/me/登出）
│   │   └── qa.py                    # 问答路由（占位，未实现）
│   ├── core/                        # 核心配置层
│   │   ├── __init__.py
│   │   ├── config.py                # 应用配置类 Settings
│   │   ├── database.py              # SQLAlchemy 引擎与会话
│   │   └── security.py              # JWT + bcrypt 密码工具
│   ├── data/                        # 日志数据 CSV
│   │   ├── logs.csv
│   │   └── logs_cleaned.csv
│   ├── models/                      # SQLAlchemy ORM 模型
│   │   ├── __init__.py              # 统一导出
│   │   ├── user.py                  # User + UserRole
│   │   ├── log.py                   # Log
│   │   ├── qa_history.py            # QAHistory + FeedbackType
│   │   ├── audit_log.py             # AuditLog
│   │   └── conversation.py          # 空占位文件
│   ├── schemas/                     # Pydantic 请求/响应 Schema
│   │   ├── __init__.py              # 空
│   │   ├── auth.py                  # LoginRequest/RegisterRequest/TokenResponse/UserResponse
│   │   └── qa.py                    # 空占位文件
│   ├── scripts/                     # 运维/数据脚本
│   │   ├── import_logs.py           # 日志批量入库
│   │   ├── batch_vectorize.py       # 批量向量化入库 Qdrant
│   │   ├── generate_logs.py         # 生成测试日志
│   │   ├── check_db.py              # 检查数据库表
│   │   ├── debug_bm25.py            # BM25 分词调试
│   │   └── visualize_retrieval.py    # 检索结果可视化对比
│   ├── services/                    # 核心业务服务层（RAG 核心）
│   │   ├── __init__.py
│   │   ├── qa_pipeline.py            # ★ 问答流水线编排
│   │   ├── hybrid_retriever.py       # ★ 混合检索器（RRF 融合）
│   │   ├── retriever.py              # 向量检索器
│   │   ├── bm25_retriever.py         # BM25 关键词检索器
│   │   ├── qdrant_client.py          # Qdrant 客户端封装
│   │   ├── embedder.py               # BGE 嵌入模型封装
│   │   ├── llm_client.py             # DeepSeek LLM 客户端
│   │   ├── prompt_templates.py       # Prompt 模板
│   │   ├── chunker.py                # 日志文本分块器
│   │   ├── formatter.py              # 检索结果格式化
│   │   ├── log_parser.py             # 日志解析器
│   │   ├── log_cleaner.py            # 日志清洗器
│   │   ├── conversation.py           # 多轮对话记忆
│   │   ├── source_tracking.py        # 来源溯源
│   │   ├── quality_checker.py        # 回答质量自检
│   │   ├── error_handler.py          # 统一异常处理
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
│   └── requirements.txt
├── frontend/                        # 前端 React 应用
│   ├── public/
│   │   ├── favicon.svg
│   │   └── icons.svg
│   ├── src/
│   │   ├── api/
│   │   │   ├── client.js            # axios 实例 + 拦截器
│   │   │   └── auth.js              # 认证 API 封装
│   │   ├── assets/
│   │   ├── components/
│   │   │   └── ProtectedRoute.jsx   # 路由守卫
│   │   ├── context/
│   │   │   └── AuthContext.jsx      # 全局认证 Context
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx        # 主问答界面（占位骨架）
│   │   │   ├── Dashboard.css
│   │   │   ├── Login.jsx            # 登录页
│   │   │   ├── Login.css
│   │   │   └── Register.jsx         # 注册页
│   │   ├── App.jsx                  # 根组件 + 路由
│   │   ├── App.css
│   │   ├── index.css
│   │   └── main.jsx                 # 入口
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── README.md
├── docs/                            # 文档
│   ├── frontend/                    # 前端目录副本（含 .env 示例）
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

1. **应用生命周期管理**（`lifespan`）：启动时执行 `warmup()` 系统预热，关闭时释放混合检索器线程池。
2. **系统预热 `warmup()`**：依次预加载 jieba 词典、BGE 模型、BM25 索引、Qdrant 连接、混合检索器，避免首次请求冷启动延迟。
3. **CORS 中间件**：允许 `http://localhost:5173`、`http://localhost:3000`。
4. **路由注册**：仅注册 `api.auth`（前缀 `/api/auth`）；问答路由 `api.qa` 尚未接入。
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

`QAHistory` 字段：`id`、`user_id`(FK→users.id)、`question`、`answer`、`sources`(Text, JSON)、`feedback`、`created_at`。

- 关系：`user = relationship("User", backref="qa_histories")`（多对一）。

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

**文件为空**，会话持久化模型未实现（当前对话记忆仅在内存中，见 `services/conversation.py`）。

---

### 5.4 Pydantic Schema 层 schemas/

#### 5.4.1 auth.py

**路径**：[backend/schemas/auth.py](file:///d:/log-qa-system/backend/schemas/auth.py)

| Schema | 字段 | 校验 |
|--------|------|------|
| `LoginRequest` | username, password | 3-50 / 6-50 字符 |
| `RegisterRequest` | username, password, role(默认"user") | 同上 |
| `TokenResponse` | access_token, token_type(默认"bearer"), username, role | — |
| `UserResponse` | id, username, role, created_at(str) | — |

> 注：`UserResponse.created_at` 为 `str` 类型，需业务层转换；未配置 `orm_mode`，ORM→Schema 转换需手动完成。

#### 5.4.2 qa.py / __init__.py

均为空文件，问答 API 的请求/响应 Schema 尚未定义。

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

**接口清单**：

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | `/api/auth/register` | 用户注册，返回 UserResponse | 否 |
| POST | `/api/auth/login` | 用户登录，返回 JWT TokenResponse | 否 |
| GET | `/api/auth/me` | 获取当前用户信息 | 是 |
| POST | `/api/auth/logout` | 登出（记录审计日志，客户端清 Token） | 是 |

- 登录失败会记录 `login_failed` 审计日志；成功记录 `login_success`。
- `get_current_user` 作为 FastAPI 依赖，用于保护需要登录的接口。

#### 5.5.2 qa.py — 问答路由

**路径**：[backend/api/qa.py](file:///d:/log-qa-system/backend/api/qa.py)

**文件为空**，问答 HTTP 接口尚未接入 `QAPipeline`。当前 `QAPipeline` 仅可通过脚本/测试调用。

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
| `ask(question, filters, top_k, template_type) -> QAResult` | ★ 同步问答：检索→截断→构造 Prompt→调用 LLM→提取来源→标注→估计置信度→保存历史 |
| `ask_stream(question, ...) -> Generator[StreamChunk]` | ★ 流式问答，先 yield 来源块，再逐块 yield 答案 |
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

#### 5.6.13 conversation.py — 多轮对话记忆

**路径**：[backend/services/conversation.py](file:///d:/log-qa-system/backend/services/conversation.py)

| 类 | 说明 |
|----|------|
| `Message` (dataclass) | role, content, timestamp |
| `Conversation` (dataclass) | id, messages, created_at, updated_at, metadata |
| `ConversationBufferMemory` | ★ 对话缓冲区记忆，支持滑动窗口与摘要压缩 |
| `ConversationAwarePipeline` | 包装 `QAPipeline` 添加对话记忆 |

**`ConversationBufferMemory` 关键方法**：`create_conversation`、`get_conversation`、`add_message`、`get_history`、`get_context_for_llm`（自动 token 估算截断，约 2.5 字符/token）、`set_summary`、`clear`、`delete`、`list_conversations`、`to_dict`/`from_dict`。

**便捷函数**：`create_conversation_pipeline(top_k, retriever_type, template_type, max_messages, enable_summary)`。

#### 5.6.14 source_tracking.py — 来源溯源

**路径**：[backend/services/source_tracking.py](file:///d:/log-qa-system/backend/services/source_tracking.py)

| 类 | 说明 |
|----|------|
| `SourceReference` (dataclass) | ref_id, log_id, service, timestamp, level, content, score, snippet |
| `SourceAnnotatedAnswer` (dataclass) | question, answer, sources, confidence, total_tokens |
| `SourceTracker` | 来源追踪器，支持双向追溯（回答→日志，日志→回答） |
| `SourceAwareQAPipeline` | 包装 `QAPipeline` 自动添加引用标注 |

**`SourceTracker` 关键方法**：`add_source`、`get_ref`、`get_refs_for_log`、`annotate_answer`（`[ID:xxx]`→`[n]`）、`get_reference_list`、`format_reference_list(markdown/json/text)`。

**便捷函数**：`create_source_aware_pipeline(top_k, retriever_type, template_type)`。

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

| 脚本 | 用途 | 运行方式 |
|------|------|----------|
| `import_logs.py` | 将 `logs_cleaned.csv` 批量导入 SQLite，按 (message, service) 去重，支持 `--csv/--batch-size/--stats/--clear` | `python scripts/import_logs.py` |
| `batch_vectorize.py` | 从 DB 读取日志→分块→向量化→写入 Qdrant，支持断点续传（`vectorize_checkpoint.json`，每 30s 存档）、重建、干跑 | `python scripts/batch_vectorize.py --rebuild` |
| `generate_logs.py` | 生成 10000 条模拟日志到 `logs.csv`（5 个服务、4 个级别） | `python scripts/generate_logs.py` |
| `check_db.py` | 列出 `logs.db` 表名（注意：写死 `logs.db`，与默认 `app.db` 不同） | `python scripts/check_db.py` |
| `debug_bm25.py` | 调试 BM25 分词与匹配效果 | `python scripts/debug_bm25.py` |
| `visualize_retrieval.py` | 三种检索（向量/BM25/混合）结果对比可视化（ANSI 彩色） | `python scripts/visualize_retrieval.py` |

---

### 5.8 测试层 tests/

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

### 5.10 数据文件 data/

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
      ├─ /login        → <Login />
      ├─ /register     → <Register />
      ├─ /dashboard    → <ProtectedRoute><Dashboard /></ProtectedRoute>
      └─ /             → <Navigate to="/dashboard" replace />
```

### 6.2 API 层

**[api/client.js](file:///d:/log-qa-system/frontend/src/api/client.js)**：axios 实例 `apiClient`
- `baseURL`：`import.meta.env.VITE_API_BASE_URL`
- `timeout`：30000ms
- **请求拦截器**：从 `localStorage` 读 `access_token`，自动加 `Authorization: Bearer`
- **响应拦截器**：401 时清 `access_token`/`user` 并跳转 `/login`

**[api/auth.js](file:///d:/log-qa-system/frontend/src/api/auth.js)**：

| 函数 | 端点 |
|------|------|
| `register(username, password)` | POST `/api/auth/register` |
| `login(username, password)` | POST `/api/auth/login` |
| `getCurrentUser()` | GET `/api/auth/me` |
| `logout()` | 本地清理（不调后端） |

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

### 6.5 页面

| 页面 | 状态 | 说明 |
|------|------|------|
| [Login.jsx](file:///d:/log-qa-system/frontend/src/pages/Login.jsx) | ✅ 完成 | 登录表单，页脚提示测试账号 `admin / admin123` |
| [Register.jsx](file:///d:/log-qa-system/frontend/src/pages/Register.jsx) | ✅ 完成 | 注册表单（用户名≥3、密码≥6、确认密码），成功后跳登录 |
| [Dashboard.jsx](file:///d:/log-qa-system/frontend/src/pages/Dashboard.jsx) | ⚠️ 占位 | 顶部显示用户名/角色/登出；主体为占位卡片"问答界面开发中..."，**实际 QA 聊天界面未实现** |

### 6.6 构建配置

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
用户提问
  │
  ▼
QAPipeline.ask(question, filters, top_k)
  │
  ├─ 1. 检索（HybridRetrieverAsync.search）
  │     ├─ asyncio.gather 并行：
  │     │   ├─ LogRetriever.search（BGE 向量化 → Qdrant 检索）
  │     │   └─ BM25Retriever.search（jieba 分词 → BM25Okapi）
  │     ├─ RRF 融合：rrf_score = w_v/(k+rank_v) + w_b/(k+rank_b)
  │     └─ 按 rrf_score 排序取 Top-K
  │
  ├─ 2. 截断过长日志（max_log_length=300）
  │
  ├─ 3. 构造 Prompt（build_qa_prompt, evidence_chain 模板）
  │     ├─ SYSTEM_PROMPT
  │     ├─ format_chat_history（最近 6 轮）
  │     └─ format_logs_as_context（日志列表）
  │
  ├─ 4. 调用 LLM（DeepSeekClient.chat）
  │     └─ messages = [system, user] → response
  │
  ├─ 5. 提取来源（_extract_sources）
  │
  ├─ 6. 解析引用（_extract_source_refs：[ID:xxx] → 匹配日志 → [n]）
  │
  ├─ 7. 标注回答（_annotate_answer_with_refs：[ID:xxx] → [n]）
  │
  ├─ 8. 估计置信度（_estimate_confidence：高/中/低）
  │
  ├─ 9. 保存对话历史（conversation_history）
  │
  └─ 返回 QAResult
        ├─ answer（带 [n] 标注）
        ├─ source_refs（来源列表）
        ├─ confidence
        └─ retrieval_time / llm_time / total_time
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
| `ConversationBufferMemory` / `ConversationAwarePipeline` | services/conversation.py | 对话记忆 |
| `SourceTracker` / `SourceAwareQAPipeline` | services/source_tracking.py | 来源溯源 |
| `QualityChecker` / `QualityAwarePipeline` | services/quality_checker.py | 质量自检 |
| `ErrorHandler` / `RobustQAPipeline` | services/error_handler.py | 异常处理 |
| `QASystemError` 及子类 | services/exceptions.py | 自定义异常 |

### 8.2 单例函数索引

| 函数 | 返回 | 文件 |
|------|------|------|
| `get_retriever()` | `LogRetriever` | services/retriever.py |
| `get_bm25_retriever(corpus, cache_path)` | `BM25Retriever` | services/bm25_retriever.py |
| `get_qdrant_client()` | `QdrantClientWrapper` | services/qdrant_client.py |
| `get_embedder()` | `BGEEmbedder` | services/embedder.py |
| `get_hybrid_retriever_async(...)` | `HybridRetrieverAsync` | services/hybrid_retriever.py |

### 8.3 工厂函数索引

| 函数 | 返回 |
|------|------|
| `create_pipeline(...)` | `QAPipeline` |
| `create_conversation_pipeline(...)` | `ConversationAwarePipeline` |
| `create_source_aware_pipeline(...)` | `SourceAwareQAPipeline` |
| `create_quality_pipeline(...)` | `QualityAwarePipeline` |
| `create_robust_pipeline(...)` | `RobustQAPipeline` |

### 8.4 前端核心组件/Hook 索引

| 名称 | 文件 | 职责 |
|------|------|------|
| `App` | App.jsx | 根组件 + 路由 |
| `AuthProvider` / `useAuth` | context/AuthContext.jsx | 全局认证状态 |
| `ProtectedRoute` | components/ProtectedRoute.jsx | 路由守卫 |
| `Login` / `Register` / `Dashboard` | pages/ | 页面 |
| `apiClient` | api/client.js | axios 实例 |
| `login/register/getCurrentUser/logout` | api/auth.js | 认证 API |

---

## 9. 依赖关系总览

### 9.1 后端模块依赖图

```
main.py
  ├─ api.auth ──┬─ core.database (get_db)
  │             ├─ core.security (JWT/bcrypt)
  │             ├─ models.user / models.audit_log
  │             └─ schemas.auth
  └─ (warmup) services.embedder / bm25_retriever / qdrant_client / hybrid_retriever

services.qa_pipeline
  ├─ services.llm_client (DeepSeekClient)
  ├─ services.prompt_templates (build_qa_prompt)
  ├─ services.retriever (LogRetriever)        ──┐
  ├─ services.bm25_retriever (BM25Retriever)    │
  └─ services.hybrid_retriever ─────────────────┤
                                                │
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

services.{conversation,source_tracking,quality_checker,error_handler}
  └─ services.qa_pipeline (延迟导入，装饰器增强)

外部服务：
  ├─ Qdrant 云（向量库，QDRANT_URL）
  └─ DeepSeek API（LLM，DEEPSEEK_BASE_URL）
```

### 9.2 数据库表关系

```
users (1) ──── (N) qa_history      [FK: qa_history.user_id → users.id]
users (1) ──── (N) audit_logs      [弱关联，无 FK，冗余 username]
logs                              [独立表，无外键]
```

### 9.3 前后端依赖

```
前端 axios ──HTTP/JWT──→ 后端 FastAPI
  /api/auth/register
  /api/auth/login
  /api/auth/me
  /api/auth/logout
  (问答接口待开发)
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
DEEPSEEK_MODEL=deepseek-chat

# Qdrant 向量库
QDRANT_URL=https://your-qdrant-cluster-url
QDRANT_API_KEY=your-qdrant-api-key
QDRANT_COLLECTION_NAME=log_vectors

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

> 提示：`docs/frontend/.env` 有示例可参考。`.gitignore` 会忽略 `.env`，但保留 `.env.example`。

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
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | LLM 模型名 |
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

1. **问答 API 未接入**：`api/qa.py` 为空，`QAPipeline` 目前仅能通过脚本/测试调用，前端 Dashboard 问答界面为占位骨架。HTTP 接口层与前端聊天 UI 是待补全的核心功能。

2. **配置不一致**：
   - `QDRANT_COLLECTION_NAME` 在 `core/config.py` 默认 `log_knowledge`，而 `services/qdrant_client.py` 默认 `log_vectors`，需统一或在 `.env` 显式配置。
   - `DEEPSEEK_MODEL` 在 `core/config.py` 默认 `deepseek-v4-pro`，但 `llm_client.py` 的 `DeepSeekConfig` 默认 `deepseek-chat`，以 `llm_client.py` 实际生效为准。

3. **数据库文件不统一**：`scripts/check_db.py` 写死 `logs.db`，而 `core/database.py` 默认 `app.db`，两者可能指向不同数据库文件。

4. **空文件/未实现**：
   - `models/conversation.py`、`schemas/qa.py`、`schemas/__init__.py`、`utils/logger.py`、`utils/__init__.py` 为空。
   - `docs/API.md`、`docs/DEPLOY.md`、根 `README.md` 为空。
   - `frontend/src/App.css` 为 Vite 模板残留，未被业务使用。

5. **依赖未列入 requirements.txt**：`jieba`、`rank_bm25`、`nltk`、`httpx`、`modelscope` 需手动安装。

6. **时间戳策略**：所有 ORM 模型使用 Python 端 `datetime.now`，而非数据库端 `func.now()`，多实例部署可能产生时间偏差。

7. **对话记忆未持久化**：`Conversation` 模型为空，对话历史仅在内存（`QAPipeline.conversation_history`），服务重启即丢失。

8. **`docs/frontend/` 目录**：存在一份与 `frontend/` 几乎相同的前端副本（含 `.env`），疑似开发快照，实际使用的是根 `frontend/` 目录。

9. **检索测试数据依赖**：多数检索测试需 Qdrant 有数据，否则 `pytest.skip`；集成测试需 `INTEGRATION_TEST=true`。

10. **CORS 配置**：后端仅允许 `localhost:5173` 和 `localhost:3000`，生产部署需调整。

---

> **文档结束**
>
> 本 Code Wiki 基于代码库静态分析生成。如需了解某模块的运行时行为，建议结合 `scripts/visualize_retrieval.py`、`scripts/debug_bm25.py` 等调试工具实际运行验证。
