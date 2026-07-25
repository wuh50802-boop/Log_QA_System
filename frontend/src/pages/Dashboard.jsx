import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import Chat from '../components/Chat';
import ConversationSidebar from '../components/ConversationSidebar';
import ChangePasswordModal from '../components/ChangePasswordModal';
import './Dashboard.css';

const Dashboard = () => {
  const { user, logout } = useAuth();

  // 多轮对话状态：当前选中的会话 ID（null 表示新会话）
  const [conversationId, setConversationId] = useState(null);
  // 触发侧边栏刷新的计数器（每次提问或删除后递增）
  const [sidebarRefreshKey, setSidebarRefreshKey] = useState(0);
  // 移动端侧边栏开关
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // 修改密码弹窗开关
  const [passwordModalOpen, setPasswordModalOpen] = useState(false);

  // 切换到指定会话
  const handleSelectConversation = (id) => {
    setConversationId(id);
  };

  // 开启新会话
  const handleNewConversation = () => {
    setConversationId(null);
  };

  // Chat 组件通知会话 ID 变化（首次提问时后端生成）
  const handleConversationChanged = (newId) => {
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
