import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { getConversations, deleteConversation } from '../api/qa';
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

  const handleFeedbackNav = () => {
    setUserMenuOpen(false);
    onClose?.();
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
            <Link
              to="/feedback"
              className="conv-menu-item"
              onClick={handleFeedbackNav}
            >
              反馈统计
            </Link>
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
    </div>
  );
};

export default ConversationSidebar;
