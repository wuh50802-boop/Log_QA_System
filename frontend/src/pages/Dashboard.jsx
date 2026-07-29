import React, { useState, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import Chat from '../components/Chat';
import ConversationSidebar from '../components/ConversationSidebar';
import ChangePasswordModal from '../components/ChangePasswordModal';
import './Dashboard.css';

const CONV_STORAGE_KEY = 'log_qa_active_conversation';

const Dashboard = () => {
  const { user, logout } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();

  // 标记当前会话是否来自 URL 参数（如从反馈统计页跳转查看他人会话）
  // 来自 URL 的会话不应持久化到 sessionStorage，避免污染用户自己的活跃会话
  const isFromUrlRef = useRef(!!searchParams.get('conv'));

  // 多轮对话状态：优先从 URL ?conv= 恢复（如从反馈统计页跳转），其次从 sessionStorage 恢复
  const [conversationId, setConversationId] = useState(() => {
    const urlConv = searchParams.get('conv');
    if (urlConv) return urlConv;
    return sessionStorage.getItem(CONV_STORAGE_KEY) || null;
  });
  // 触发侧边栏刷新的计数器（每次提问或删除后递增）
  const [sidebarRefreshKey, setSidebarRefreshKey] = useState(0);
  // 移动端侧边栏开关
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // 修改密码弹窗开关
  const [passwordModalOpen, setPasswordModalOpen] = useState(false);

  // 持久化当前会话到 sessionStorage（仅用户自己的活跃会话，排除 URL 跳转的临时查看）
  useEffect(() => {
    if (isFromUrlRef.current) return;
    if (conversationId) {
      sessionStorage.setItem(CONV_STORAGE_KEY, conversationId);
    } else {
      sessionStorage.removeItem(CONV_STORAGE_KEY);
    }
  }, [conversationId]);

  // 如果 URL 中有 ?conv= 参数，消费后清除（避免刷新时重复）
  useEffect(() => {
    if (searchParams.get('conv')) {
      setSearchParams({}, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 切换到指定会话（用户主动操作，恢复持久化）
  const handleSelectConversation = (id) => {
    isFromUrlRef.current = false;
    setConversationId(id);
  };

  // 开启新会话
  const handleNewConversation = () => {
    isFromUrlRef.current = false;
    setConversationId(null);
  };

  // Chat 组件通知会话 ID 变化（首次提问时后端生成）
  const handleConversationChanged = (newId) => {
    isFromUrlRef.current = false;
    setConversationId(newId);
    // 刷新侧边栏列表（更新最近提问/时间）
    setSidebarRefreshKey((k) => k + 1);
  };

  // 修改密码成功后，自动登出并跳转登录页
  const handlePasswordChanged = () => {
    logout();
  };

  // 侧边栏透传：打开修改密码弹窗
  const handleOpenPasswordModal = () => {
    setPasswordModalOpen(true);
  };

  return (
    <div className="dashboard-container">
      {/* 顶部品牌栏（贯穿全宽） */}
      <header className="dashboard-topbar">
        <span className="dashboard-brand">日志智能问答</span>
      </header>

      <main className="dashboard-main">
        <div className={`dashboard-sidebar ${sidebarOpen ? 'dashboard-sidebar-open' : ''}`}>
          <ConversationSidebar
            currentConversationId={conversationId}
            onSelect={handleSelectConversation}
            onNew={handleNewConversation}
            refreshKey={sidebarRefreshKey}
            onClose={() => setSidebarOpen(false)}
            onOpenPasswordModal={handleOpenPasswordModal}
          />
        </div>

        {sidebarOpen && (
          <div
            className="dashboard-sidebar-overlay"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        <div className="dashboard-chat-wrap">
          <Chat
            conversationId={conversationId}
            onConversationChanged={handleConversationChanged}
            onSidebarToggle={() => setSidebarOpen(true)}
          />
        </div>
      </main>

      <ChangePasswordModal
        open={passwordModalOpen}
        onClose={() => setPasswordModalOpen(false)}
        onSuccess={handlePasswordChanged}
      />
    </div>
  );
};

export default Dashboard;
