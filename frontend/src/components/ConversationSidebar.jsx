import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { getConversations, deleteConversation, getFeedbackStats } from '../api/qa';
import './ConversationSidebar.css';

const ConversationSidebar = ({
  currentConversationId,
  onSelect,
  onNew,
  refreshKey,
  onClose,
  onOpenPasswordModal,
}) => {
  const { user, logout } = useAuth();
  const [conversations, setConversations] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  // 用户菜单展开状态
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef(null);

  // 反馈统计面板状态
  const [statsOpen, setStatsOpen] = useState(false);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsData, setStatsData] = useState(null);
  const [statsScope, setStatsScope] = useState('me');

  const isAdmin = user?.role === 'admin';

  const fetchConversations = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getConversations();
      setConversations(data.items || []);
    } catch (err) {
      console.error('加载会话列表失败:', err);
      setError('加载会话列表失败');
    } finally {
      setLoading(false);
    }
  };

  // 初始加载 + refreshKey 变化时刷新
  useEffect(() => {
    fetchConversations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  // 点击外部关闭用户菜单
  useEffect(() => {
    if (!userMenuOpen) return;
    const handleClickOutside = (e) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target)) {
        setUserMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [userMenuOpen]);

  const handleSelect = (conv) => {
    onSelect?.(conv.conversation_id);
    onClose?.();
  };

  const handleNew = () => {
    onNew?.();
    onClose?.();
  };

  const handleDelete = async (e, conversationId) => {
    e.stopPropagation();
    if (!window.confirm('确定要删除这个会话吗？所有问答记录将一并删除，且不可恢复。')) {
      return;
    }
    setDeletingId(conversationId);
    try {
      await deleteConversation(conversationId);
      if (conversationId === currentConversationId) {
        onNew?.();
      }
      fetchConversations();
    } catch (err) {
      console.error('删除会话失败:', err);
      alert('删除会话失败');
    } finally {
      setDeletingId(null);
    }
  };

  const formatDate = (isoStr) => {
    if (!isoStr) return '';
    try {
      const d = new Date(isoStr);
      const now = new Date();
      const diff = (now - d) / 1000;
      if (diff < 60) return '刚刚';
      if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
      if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
      if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`;
      return d.toLocaleDateString('zh-CN');
    } catch {
      return '';
    }
  };

  const handleToggleUserMenu = () => {
    setUserMenuOpen((v) => !v);
  };

  const handleOpenPassword = () => {
    setUserMenuOpen(false);
    onClose?.();
    onOpenPasswordModal?.();
  };

  const handleUserMgmt = () => {
    setUserMenuOpen(false);
    onClose?.();
  };

  const handleLogsMgmt = () => {
    setUserMenuOpen(false);
    onClose?.();
  };

  const handleLogout = () => {
    setUserMenuOpen(false);
    logout();
  };

  // 反馈统计
  const loadStats = async (scope) => {
    setStatsLoading(true);
    try {
      const data = await getFeedbackStats({ scope });
      setStatsData(data);
    } catch (err) {
      console.error('加载反馈统计失败:', err);
    } finally {
      setStatsLoading(false);
    }
  };

  const handleOpenStats = () => {
    setUserMenuOpen(false);
    onClose?.();
    setStatsOpen(true);
    loadStats(statsScope);
  };

  const handleSwitchScope = (newScope) => {
    if (newScope === statsScope) return;
    setStatsScope(newScope);
    loadStats(newScope);
  };

  const handleJumpToConversation = (convId) => {
    if (!convId) return;
    setStatsOpen(false);
    onSelect?.(convId);
  };

  // 用户名首字母作为头像
  const initial = (user?.username || '?').charAt(0).toUpperCase();

  return (
    <div className="conv-sidebar">
      {/* 会话列表模块标签 + 新会话按钮 */}
      <div className="conv-section-header">
        <span className="conv-section-label">会话列表</span>
        <button
          className="conv-new-btn"
          onClick={handleNew}
          title="开启新会话"
          aria-label="开启新会话"
        >
          +
        </button>
      </div>

      <div className="conv-list">
        {loading && conversations.length === 0 && (
          <div className="conv-empty">加载中...</div>
        )}
        {error && <div className="conv-error">{error}</div>}
        {!loading && !error && conversations.length === 0 && (
          <div className="conv-empty">
            还没有会话，开启新会话开始提问吧
          </div>
        )}

        {conversations.map((conv) => (
          <div
            key={conv.conversation_id}
            className={`conv-item ${
              conv.conversation_id === currentConversationId ? 'conv-item-active' : ''
            }`}
            onClick={() => handleSelect(conv)}
            title={conv.title || conv.last_question}
          >
            <div className="conv-item-title">
              {conv.title || '(未命名会话)'}
            </div>
            <div className="conv-item-meta">
              <span className="conv-item-count">{conv.message_count} 轮</span>
              <span className="conv-item-time">{formatDate(conv.updated_at)}</span>
            </div>
            <button
              className="conv-delete-btn"
              onClick={(e) => handleDelete(e, conv.conversation_id)}
              disabled={deletingId === conv.conversation_id}
              title="删除会话"
            >
              {deletingId === conv.conversation_id ? '删除中' : '删除'}
            </button>
          </div>
        ))}
      </div>

      {/* 底部用户卡片 + 弹出菜单 */}
      <div className="conv-user-area" ref={userMenuRef}>
        <button
          className={`conv-user-card ${userMenuOpen ? 'conv-user-card-open' : ''}`}
          onClick={handleToggleUserMenu}
          title="点击查看更多操作"
        >
          <div className="conv-user-avatar">{initial}</div>
          <div className="conv-user-info">
            <div className="conv-user-name">{user?.username || '未知用户'}</div>
            <div className="conv-user-role">
              <span className={`role-pill role-${user?.role || 'user'}`}>
                {user?.role === 'admin' ? '管理员' : '普通用户'}
              </span>
            </div>
          </div>
          <span className={`conv-user-chevron ${userMenuOpen ? 'chevron-up' : 'chevron-down'}`}>
            {userMenuOpen ? '收起' : '展开'}
          </span>
        </button>

        {userMenuOpen && (
          <div className="conv-user-menu">
            <button
              type="button"
              className="conv-menu-item"
              onClick={handleOpenStats}
            >
              反馈统计
            </button>
            <button
              type="button"
              className="conv-menu-item"
              onClick={handleOpenPassword}
            >
              修改密码
            </button>
            {isAdmin && (
              <Link
                to="/admin/users"
                className="conv-menu-item"
                onClick={handleUserMgmt}
              >
                用户管理
              </Link>
            )}
            {isAdmin && (
              <Link
                to="/admin/logs"
                className="conv-menu-item"
                onClick={handleLogsMgmt}
              >
                日志管理
              </Link>
            )}
            <div className="conv-menu-divider" />
            <button
              type="button"
              className="conv-menu-item conv-menu-danger"
              onClick={handleLogout}
            >
              退出登录
            </button>
          </div>
        )}
      </div>

      {/* 反馈统计面板（在 sidebar 末层渲染，遮罩全屏） */}
      {statsOpen && (
        <FeedbackStatsPanel
          loading={statsLoading}
          data={statsData}
          scope={statsScope}
          isAdmin={isAdmin}
          onClose={() => setStatsOpen(false)}
          onRefresh={() => loadStats(statsScope)}
          onSwitchScope={handleSwitchScope}
          onJumpToConversation={handleJumpToConversation}
        />
      )}
    </div>
  );
};

// ============================================================
// 反馈统计面板组件
// ============================================================
const FeedbackStatsPanel = ({
  loading,
  data,
  scope,
  isAdmin,
  onClose,
  onRefresh,
  onSwitchScope,
  onJumpToConversation,
}) => {
  const likeRate = data?.like_rate ?? 0;
  const likeRatePct = (likeRate * 100).toFixed(1);
  const totalRated = (data?.total_likes ?? 0) + (data?.total_dislikes ?? 0);
  const showAll = data?.scope === 'all';

  return (
    <div className="stats-overlay" onClick={onClose}>
      <div className="stats-panel" onClick={(e) => e.stopPropagation()}>
        <div className="stats-header">
          <h3>反馈统计{showAll ? '（全平台）' : '（我的）'}</h3>
          <div className="stats-actions">
            {isAdmin && (
              <div className="stats-scope-toggle">
                <button
                  className={`stats-scope-btn ${scope === 'me' ? 'active' : ''}`}
                  onClick={() => onSwitchScope('me')}
                  disabled={loading}
                >
                  我的
                </button>
                <button
                  className={`stats-scope-btn ${scope === 'all' ? 'active' : ''}`}
                  onClick={() => onSwitchScope('all')}
                  disabled={loading}
                >
                  全平台
                </button>
              </div>
            )}
            <button className="stats-refresh-btn" onClick={onRefresh} disabled={loading} title="刷新">
              {loading ? '加载中' : '刷新'}
            </button>
            <button className="stats-close-btn" onClick={onClose} title="关闭">
              关闭
            </button>
          </div>
        </div>

        {loading && !data ? (
          <div className="stats-loading">加载中...</div>
        ) : !data ? (
          <div className="stats-empty">暂无数据</div>
        ) : (
          <>
            <div className="stats-cards">
              <div className="stat-card">
                <div className="stat-value">{data.total_qa ?? 0}</div>
                <div className="stat-label">总问答数</div>
              </div>
              <div className="stat-card stat-card-like">
                <div className="stat-value">{data.total_likes ?? 0}</div>
                <div className="stat-label">点赞数</div>
              </div>
              <div className="stat-card stat-card-dislike">
                <div className="stat-value">{data.total_dislikes ?? 0}</div>
                <div className="stat-label">点踩数</div>
              </div>
              <div className="stat-card stat-card-rate">
                <div className="stat-value">{likeRatePct}%</div>
                <div className="stat-label">好评率 ({totalRated} 评价)</div>
              </div>
            </div>

            <div className="stats-section">
              <h4>差评问题 Top 10</h4>
              {(!data.top_disliked || data.top_disliked.length === 0) ? (
                <div className="stats-empty-list">暂无差评记录</div>
              ) : (
                <div className="stats-disliked-list">
                  {data.top_disliked.map((item) => (
                    <div
                      key={item.qa_id}
                      className={`disliked-item ${item.conversation_id ? 'clickable' : ''}`}
                      onClick={() =>
                        item.conversation_id && onJumpToConversation(item.conversation_id)
                      }
                      title={
                        item.conversation_id
                          ? '点击跳转到原会话查看完整上下文'
                          : '该问答无关联会话'
                      }
                    >
                      <div className="disliked-question">
                        <span className="disliked-badge">!</span>
                        <span className="disliked-q-text">{item.question}</span>
                      </div>
                      <div className="disliked-answer">{item.answer}</div>
                      <div className="disliked-meta">
                        <span className="disliked-time">{item.created_at}</span>
                        {showAll && item.username && (
                          <span className="disliked-username">{item.username}</span>
                        )}
                        {item.conversation_id && (
                          <span className="disliked-jump-hint">查看会话</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default ConversationSidebar;
