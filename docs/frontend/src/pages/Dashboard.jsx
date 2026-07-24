import React from 'react';
import { useAuth } from '../context/AuthContext';
import './Dashboard.css';

const Dashboard = () => {
  const { user, logout } = useAuth();

  return (
    <div className="dashboard-container">
      <header className="dashboard-header">
        <h1>📊 日志智能问答系统</h1>
        <div className="user-info">
          <span>👤 {user?.username}</span>
          <span className="role-badge">{user?.role || 'user'}</span>
          <button onClick={logout} className="logout-btn">
            退出登录
          </button>
        </div>
      </header>
      
      <main className="dashboard-main">
        <div className="welcome-card">
          <h2>欢迎回来，{user?.username}！</h2>
          <p>系统已准备就绪，请开始提问。</p>
        </div>
        
        {/* 这里后续添加问答界面 */}
        <div className="placeholder-card">
          <p>💡 问答界面开发中...</p>
          <p className="hint">第6周将实现完整的聊天界面</p>
        </div>
      </main>
    </div>
  );
};

export default Dashboard;