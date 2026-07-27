import React, { useState, useRef, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { askStreamQuestion, submitFeedback, getConversationDetail, getFilterOptions } from '../api/qa';
import './Chat.css';

// 新会话的初始欢迎消息
const WELCOME_MESSAGE = {
  id: 'welcome',
  role: 'assistant',
  content: '你好！我是日志智能问答助手。你可以问我任何关于应用运行日志的问题，例如「数据库连接失败的原因」「用户登录失败的常见错误」等。',
  sources: [],
  streaming: false,
  feedback: 'none',
  qaId: null,
};

const buildWelcomeMessages = () => [WELCOME_MESSAGE];

// 将后端返回的会话详情转换为前端消息列表
const conversationDetailToMessages = (detail) => {
  const messages = [];
  for (const item of detail.items || []) {
    messages.push({
      id: `u-${item.id}`,
      role: 'user',
      content: item.question,
      sources: [],
      streaming: false,
    });
    messages.push({
      id: `a-${item.id}`,
      role: 'assistant',
      content: item.answer,
      sources: item.sources || [],
      streaming: false,
      feedback: item.feedback || 'none',
      qaId: item.id,
      qualityCheck: item.quality_check || null,
    });
  }
  return messages;
};

const Chat = ({ conversationId, onConversationChanged, onSidebarToggle }) => {
  const { user } = useAuth();
  const [messages, setMessages] = useState(buildWelcomeMessages());
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  // 当前查看的会话归属（admin 查看他人会话时显示提示）
  const [viewingOwner, setViewingOwner] = useState('');
  // 当前会话标题（显示在 chat-header）
  const [conversationTitle, setConversationTitle] = useState('新会话');

  // 检索过滤条件（level / service / 时间范围）
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [filterLevel, setFilterLevel] = useState('');
  const [filterService, setFilterService] = useState('');
  const [filterTimeAfter, setFilterTimeAfter] = useState(''); // datetime-local 字符串
  const [filterTimeBefore, setFilterTimeBefore] = useState('');

  // 过滤器可选值（从后端动态加载，避免硬编码不匹配真实数据）
  const [levelOptions, setLevelOptions] = useState([]);
  const [serviceOptions, setServiceOptions] = useState([]);

  // 组件挂载时拉取过滤器可选值
  useEffect(() => {
    (async () => {
      try {
        const data = await getFilterOptions();
        // level 按固定优先级排序（ERROR 优先），其余按字典序
        const levelOrder = ['ERROR', 'WARNING', 'INFO', 'DEBUG'];
        const levels = (data.levels || []).slice().sort((a, b) => {
          const ia = levelOrder.indexOf(a);
          const ib = levelOrder.indexOf(b);
          if (ia !== -1 && ib !== -1) return ia - ib;
          if (ia !== -1) return -1;
          if (ib !== -1) return 1;
          return a.localeCompare(b);
        });
        setLevelOptions(levels);
        setServiceOptions(data.services || []);
      } catch (err) {
        console.error('加载过滤器选项失败:', err);
      }
    })();
  }, []);

  // 将 datetime-local 字符串（YYYY-MM-DDTHH:MM）转为后端期望的 "YYYY-MM-DD HH:MM:SS"
  const formatDateTime = (dt) => {
    if (!dt) return '';
    // 浏览器 datetime-local 通常给 "YYYY-MM-DDTHH:MM"，补 ":00" 即可
    const normalized = dt.length === 16 ? `${dt}:00` : dt;
    return normalized.replace('T', ' ');
  };

  // 当前已激活的过滤条件数（用于按钮徽标）
  const activeFilterCount = [
    filterLevel,
    filterService,
    filterTimeAfter,
    filterTimeBefore,
  ].filter(Boolean).length;

  // 构造提交给后端的 filters 对象（仅包含非空字段）
  const buildFiltersPayload = () => {
    const payload = {};
    if (filterLevel) payload.level = filterLevel;
    if (filterService) payload.service = filterService;
    const after = formatDateTime(filterTimeAfter);
    const before = formatDateTime(filterTimeBefore);
    if (after) payload.timestamp_after = after;
    if (before) payload.timestamp_before = before;
    return payload;
  };

  const clearFilters = () => {
    setFilterLevel('');
    setFilterService('');
    setFilterTimeAfter('');
    setFilterTimeBefore('');
  };

  // 自动滚动到底部
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // 当 conversationId 变化时加载历史会话内容
  useEffect(() => {
    if (!conversationId) {
      // 新会话：重置为欢迎消息
      setMessages(buildWelcomeMessages());
      setViewingOwner('');
      setConversationTitle('新会话');
      return;
    }

    let cancelled = false;
    const loadHistory = async () => {
      setLoadingHistory(true);
      try {
        const detail = await getConversationDetail(conversationId);
        if (cancelled) return;
        const msgs = conversationDetailToMessages(detail);
        // 如果会话为空（不应发生但防御），回退到欢迎语
        setMessages(msgs.length > 0 ? msgs : buildWelcomeMessages());
        // admin 模式：记录正在查看的会话归属用户
        setViewingOwner(detail.owner_username || '');
        // 设置会话标题
        setConversationTitle(detail.title || '未命名会话');
      } catch (err) {
        console.error('加载会话历史失败:', err);
        if (!cancelled) {
          setMessages(buildWelcomeMessages());
          setViewingOwner('');
          setConversationTitle('未命名会话');
        }
      } finally {
        if (!cancelled) setLoadingHistory(false);
      }
    };
    loadHistory();
    return () => {
      cancelled = true;
    };
  }, [conversationId]);

  // 提交问题
  const handleSubmit = async (e) => {
    e.preventDefault();
    const question = input.trim();
    if (!question || loading) return;

    // 1. 立即加入用户消息 + 占位 AI 消息
    const userMsgId = `u-${Date.now()}`;
    const aiMsgId = `a-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { id: userMsgId, role: 'user', content: question, sources: [], streaming: false },
      { id: aiMsgId, role: 'assistant', content: '', sources: [], streaming: true, feedback: 'none', qaId: null },
    ]);
    setInput('');
    setLoading(true);

    // 2. 流式调用，携带 conversation_id 以支持多轮上下文，并附带检索过滤条件
    try {
      await askStreamQuestion(
        {
          question,
          conversation_id: conversationId || null,
          filters: buildFiltersPayload(),
        },
        {
          onSource: (data) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === aiMsgId ? { ...m, sources: data.sources || [] } : m
              )
            );
          },
          onAnswer: (data) => {
            // 逐字追加内容
            setMessages((prev) =>
              prev.map((m) =>
                m.id === aiMsgId ? { ...m, content: m.content + (data.content || '') } : m
              )
            );
          },
          onDone: (data) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === aiMsgId
                  ? {
                      ...m,
                      streaming: false,
                      qaId: data.qa_id,
                      qualityCheck: data.quality_check || null,
                    }
                  : m
              )
            );
            // 通知父组件当前会话 ID（新建或保持），触发侧边栏刷新
            onConversationChanged?.(data.conversation_id);
          },
          onError: (data) => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === aiMsgId
                  ? { ...m, streaming: false, content: `⚠️ ${data.message || '问答异常'}` }
                  : m
              )
            );
          },
        }
      );
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === aiMsgId
            ? { ...m, streaming: false, content: `⚠️ 请求失败: ${err.message}` }
            : m
        )
      );
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  // 反馈处理
  const handleFeedback = async (msgId, qaId, feedback) => {
    if (!qaId) return;
    try {
      await submitFeedback(qaId, feedback);
      setMessages((prev) =>
        prev.map((m) => (m.id === msgId ? { ...m, feedback } : m))
      );
    } catch (err) {
      console.error('反馈提交失败:', err);
    }
  };

  // 清空当前对话内容（仅前端，不删除后端记录）
  const handleClear = () => {
    setMessages(buildWelcomeMessages());
  };

  return (
    <div className="chat-container">
      <div className="chat-header">
        <span className="chat-title" title={conversationTitle}>{conversationTitle}</span>
        <button
          className="chat-icon-btn"
          onClick={handleClear}
          disabled={loading || loadingHistory}
          title="清空当前显示"
          aria-label="清空当前显示"
        >
          ⟲
        </button>
      </div>

      {/* admin 查看他人会话时的提示横幅 */}
      {viewingOwner && viewingOwner !== user?.username && (
        <div className="chat-viewing-banner" title="管理员查看模式">
          管理员查看模式 · 正在查看用户 <strong>{viewingOwner}</strong> 的会话
          <span className="chat-viewing-sub">（仅查看，不能在此发送新消息）</span>
        </div>
      )}

      <div className="messages-list">
        {loadingHistory && (
          <div className="chat-loading-banner">加载历史会话中...</div>
        )}
        {messages.map((msg) => (
          <Message
            key={msg.id}
            message={msg}
            onFeedback={(fb) => handleFeedback(msg.id, msg.qaId, fb)}
          />
        ))}
        <div ref={messagesEndRef} />
      </div>

      <form className="chat-input-area" onSubmit={handleSubmit}>
        {/* 检索过滤面板（折叠/展开） */}
        <div className="filter-bar">
          <button
            type="button"
            className={`filter-toggle-btn ${filtersOpen ? 'filter-toggle-open' : ''} ${activeFilterCount > 0 ? 'filter-toggle-active' : ''}`}
            onClick={() => setFiltersOpen((v) => !v)}
            aria-expanded={filtersOpen}
            title={filtersOpen ? '收起过滤条件' : '展开过滤条件'}
          >
            <span className="filter-toggle-icon">{filtersOpen ? '▾' : '▸'}</span>
            <span className="filter-toggle-text">过滤</span>
            {activeFilterCount > 0 && (
              <span className="filter-count-badge">{activeFilterCount}</span>
            )}
          </button>
          {activeFilterCount > 0 && (
            <button
              type="button"
              className="filter-clear-btn"
              onClick={clearFilters}
              title="清空全部过滤条件"
            >
              清空
            </button>
          )}
        </div>

        {filtersOpen && (
          <div className="filter-panel">
            <div className="filter-row">
              <label className="filter-field">
                <span className="filter-label">级别</span>
                <select
                  className="filter-select"
                  value={filterLevel}
                  onChange={(e) => setFilterLevel(e.target.value)}
                >
                  <option value="">全部</option>
                  {levelOptions.map((lvl) => (
                    <option key={lvl} value={lvl}>{lvl}</option>
                  ))}
                </select>
              </label>

              <label className="filter-field">
                <span className="filter-label">服务</span>
                <select
                  className="filter-select"
                  value={filterService}
                  onChange={(e) => setFilterService(e.target.value)}
                >
                  <option value="">全部</option>
                  {serviceOptions.map((svc) => (
                    <option key={svc} value={svc}>{svc}</option>
                  ))}
                </select>
              </label>
            </div>

            <div className="filter-row">
              <label className="filter-field">
                <span className="filter-label">开始时间</span>
                <input
                  type="datetime-local"
                  className="filter-input"
                  value={filterTimeAfter}
                  onChange={(e) => setFilterTimeAfter(e.target.value)}
                />
              </label>
              <label className="filter-field">
                <span className="filter-label">结束时间</span>
                <input
                  type="datetime-local"
                  className="filter-input"
                  value={filterTimeBefore}
                  onChange={(e) => setFilterTimeBefore(e.target.value)}
                />
              </label>
            </div>
          </div>
        )}

        <div className="chat-input-row">
          <input
            ref={inputRef}
            type="text"
            className="chat-input"
            placeholder={
              viewingOwner && viewingOwner !== user?.username
                ? '管理员查看模式：不能在此会话中发送消息'
                : '输入你的问题，例如：数据库连接失败的原因...'
            }
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={loading || (!!viewingOwner && viewingOwner !== user?.username)}
            maxLength={500}
            autoComplete="off"
          />
          <button
            type="submit"
            className="chat-send-btn"
            disabled={
              !input.trim() ||
              loading ||
              (!!viewingOwner && viewingOwner !== user?.username)
            }
          >
            {loading ? '回答中...' : '发送'}
          </button>
        </div>
      </form>
    </div>
  );
};

// ============================================================
// 单条消息组件
// ============================================================
const Message = ({ message, onFeedback }) => {
  const isUser = message.role === 'user';
  // 来源信息折叠状态：默认折叠
  const [sourcesOpen, setSourcesOpen] = useState(false);
  // 质量检查详情折叠状态：默认折叠
  const [qualityOpen, setQualityOpen] = useState(false);

  return (
    <div className={`message ${isUser ? 'message-user' : 'message-assistant'}`}>
      <div className="message-avatar">
        {isUser ? 'U' : 'A'}
      </div>
      <div className="message-body">
        <div className="message-content">
          {message.content || (message.streaming && <span className="typing-cursor">|</span>)}
          {message.streaming && message.content && <span className="typing-cursor">|</span>}
        </div>

        {/* 来源列表（仅 AI 消息）- 折叠下拉 */}
        {!isUser && message.sources && message.sources.length > 0 && (
          <div className="message-sources-wrap">
            <button
              type="button"
              className={`sources-toggle-btn ${sourcesOpen ? 'sources-toggle-open' : ''}`}
              onClick={() => setSourcesOpen((v) => !v)}
              title={sourcesOpen ? '收起来源' : '展开来源'}
            >
              <span className="sources-toggle-icon">{sourcesOpen ? '▾' : '▸'}</span>
              <span className="sources-toggle-text">
                来源 ({message.sources.length})
              </span>
            </button>
            {sourcesOpen && (
              <div className="message-sources">
                {message.sources.map((src, idx) => (
                  <div key={idx} className="source-item">
                    <span className="source-ref">{src.ref_id}</span>
                    <span className="source-service">{src.service}</span>
                    <span className={`source-level source-level-${(src.level || '').toLowerCase()}`}>
                      {src.level}
                    </span>
                    <span className="source-time">{src.timestamp}</span>
                    <div className="source-content">{src.snippet || src.content}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* 质量自检结果（仅 AI 消息且已完成流式） */}
        {!isUser && !message.streaming && message.qualityCheck && (
          <QualityCheckBadge
            qualityCheck={message.qualityCheck}
            open={qualityOpen}
            onToggle={() => setQualityOpen((v) => !v)}
          />
        )}

        {/* 反馈按钮（仅 AI 消息且非流式中） */}
        {!isUser && !message.streaming && message.qaId && (
          <div className="message-actions">
            <button
              className={`feedback-btn feedback-like ${message.feedback === 'like' ? 'active' : ''}`}
              onClick={() => onFeedback('like')}
              title="有用"
              aria-label="有用"
            >
              <ThumbsUpIcon filled={message.feedback === 'like'} />
            </button>
            <button
              className={`feedback-btn feedback-dislike ${message.feedback === 'dislike' ? 'active' : ''}`}
              onClick={() => onFeedback('dislike')}
              title="无用"
              aria-label="无用"
            >
              <ThumbsDownIcon filled={message.feedback === 'dislike'} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

// ============================================================
// 质量自检徽章组件
// ============================================================
const QualityCheckBadge = ({ qualityCheck, open, onToggle }) => {
  const score = Number(qualityCheck.score ?? 0);
  const passed = !!qualityCheck.passed;
  // 三档：高 >=85 / 中 70-84 / 低 <70
  const tier = score >= 85 ? 'high' : score >= 70 ? 'mid' : 'low';

  const issues = qualityCheck.issues || [];
  const warnings = qualityCheck.warnings || [];
  const suggestions = qualityCheck.suggestions || [];
  const detailCount = issues.length + warnings.length + suggestions.length;

  return (
    <div className={`quality-wrap quality-tier-${tier}`}>
      <button
        type="button"
        className={`quality-toggle-btn ${open ? 'quality-toggle-open' : ''}`}
        onClick={onToggle}
        title={open ? '收起质量详情' : '展开质量详情'}
        aria-expanded={open}
      >
        <span className="quality-score-badge">
          <span className="quality-score-label">质量</span>
          <span className="quality-score-value">{score}</span>
          <span className="quality-score-unit">/100</span>
        </span>
        <span className={`quality-status quality-status-${passed ? 'pass' : 'fail'}`}>
          {passed ? '通过' : '未通过'}
        </span>
        {detailCount > 0 && (
          <span className="quality-detail-count">
            {open ? '收起' : `详情 ${detailCount}`}
          </span>
        )}
      </button>
      {open && detailCount > 0 && (
        <div className="quality-details">
          {issues.length > 0 && (
            <div className="quality-section quality-section-issue">
              <div className="quality-section-title">问题</div>
              {issues.map((issue, idx) => (
                <div key={`i-${idx}`} className="quality-item">
                  <div className="quality-item-message">{issue.message}</div>
                  {issue.suggestion && (
                    <div className="quality-item-suggestion">
                      建议：{issue.suggestion}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
          {warnings.length > 0 && (
            <div className="quality-section quality-section-warning">
              <div className="quality-section-title">警告</div>
              {warnings.map((w, idx) => (
                <div key={`w-${idx}`} className="quality-item">
                  <div className="quality-item-message">{w}</div>
                </div>
              ))}
            </div>
          )}
          {suggestions.length > 0 && (
            <div className="quality-section quality-section-suggestion">
              <div className="quality-section-title">建议</div>
              {suggestions.map((s, idx) => (
                <div key={`s-${idx}`} className="quality-item">
                  <div className="quality-item-message">{s}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ============================================================
// 反馈图标组件（空心 / 实心）
// ============================================================

const ThumbsUpIcon = ({ filled }) => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill={filled ? 'currentColor' : 'none'}
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" />
  </svg>
);

const ThumbsDownIcon = ({ filled }) => (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill={filled ? 'currentColor' : 'none'}
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3" />
  </svg>
);

export default Chat;
