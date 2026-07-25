import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { getAllUsers, setUserRole, deleteUser } from '../api/auth';
import './UserManagement.css';

const UserManagement = () => {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');

  // 搜索关键字
  const [keyword, setKeyword] = useState('');
  // 已提交的搜索关键字（避免每次输入都触发请求）
  const [submittedKeyword, setSubmittedKeyword] = useState('');
  // 是否搜索结果为空（用于显示不同提示）
  const [searchedEmpty, setSearchedEmpty] = useState(false);

  // 待确认的操作（角色变更 / 删除用户）
  const [pendingChange, setPendingChange] = useState(null);
  // 删除操作确认
  const [pendingDelete, setPendingDelete] = useState(null);
  // 删除中（防止重复点击）
  const [deleting, setDeleting] = useState(false);

  // 拉取用户列表（支持搜索）
  const fetchUsers = useCallback(async (searchKey) => {
    setLoading(true);
    setError('');
    try {
      const data = await getAllUsers(searchKey);
      setUsers(data.items || []);
      setSearchedEmpty(!!searchKey && (data.items || []).length === 0);
    } catch (err) {
      const msg = err.response?.data?.detail || '加载用户列表失败';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUsers('');
  }, [fetchUsers]);

  // 闪现提示
  const showToast = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(''), 3000);
  };

  // 提交搜索
  const handleSearch = (e) => {
    e.preventDefault();
    const kw = keyword.trim();
    setSubmittedKeyword(kw);
    fetchUsers(kw);
  };

  // 清空搜索
  const handleClearSearch = () => {
    setKeyword('');
    setSubmittedKeyword('');
    fetchUsers('');
  };

  // 点击「提升为管理员 / 降级为普通用户」按钮
  const handleClickRole = (u) => {
    const targetRole = u.role === 'admin' ? 'user' : 'admin';
    const action = targetRole === 'admin' ? '提升为管理员' : '降级为普通用户';
    setPendingChange({ user: u, targetRole, action });
  };

  // 确认执行角色变更
  const handleConfirmChange = async () => {
    if (!pendingChange) return;
    const { user, targetRole } = pendingChange;
    setPendingChange(null);
    try {
      const result = await setUserRole(user.id, targetRole);
      showToast(result.message);
      fetchUsers(submittedKeyword);
    } catch (err) {
      const msg = err.response?.data?.detail || '角色变更失败';
      setError(msg);
      setTimeout(() => setError(''), 4000);
    }
  };

  const handleCancelChange = () => setPendingChange(null);

  // 点击「删除用户」按钮
  const handleClickDelete = (u) => {
    setPendingDelete({ user: u });
  };

  // 确认删除用户
  const handleConfirmDelete = async () => {
    if (!pendingDelete) return;
    const { user } = pendingDelete;
    setDeleting(true);
    try {
      const result = await deleteUser(user.id);
      showToast(result.message);
      setPendingDelete(null);
      fetchUsers(submittedKeyword);
    } catch (err) {
      const msg = err.response?.data?.detail || '删除用户失败';
      setError(msg);
      setTimeout(() => setError(''), 4000);
      setPendingDelete(null);
    } finally {
      setDeleting(false);
    }
  };

  const handleCancelDelete = () => setPendingDelete(null);

  const stats = {
    total: users.length,
    admins: users.filter((u) => u.role === 'admin').length,
    users: users.filter((u) => u.role === 'user').length,
  };

  return (
    <div className="user-mgmt-container">
      {/* 顶部导航 */}
      <header className="user-mgmt-header">
        <div className="user-mgmt-title-row">
          <h1>用户管理</h1>
          <div className="user-mgmt-nav">
            <Link to="/dashboard" className="back-link">
              返回工作台
            </Link>
          </div>
        </div>
      </header>

      <main className="user-mgmt-main">
        {/* 统计卡片 */}
        <div className="user-mgmt-stats">
          <div className="user-mgmt-stat-card">
            <div className="stat-value">{stats.total}</div>
            <div className="stat-label">总用户数</div>
          </div>
          <div className="user-mgmt-stat-card stat-admin">
            <div className="stat-value">{stats.admins}</div>
            <div className="stat-label">管理员</div>
          </div>
          <div className="user-mgmt-stat-card stat-user">
            <div className="stat-value">{stats.users}</div>
            <div className="stat-label">普通用户</div>
          </div>
        </div>

        {/* 用户列表 */}
        <div className="user-mgmt-card">
          <div className="user-mgmt-card-header">
            <h2>用户列表</h2>
            <button
              className="refresh-btn"
              onClick={() => fetchUsers(submittedKeyword)}
              disabled={loading}
            >
              {loading ? '加载中' : '刷新'}
            </button>
          </div>

          {/* 搜索框 */}
          <form className="user-search-bar" onSubmit={handleSearch}>
            <input
              type="text"
              className="user-search-input"
              placeholder="按用户名搜索（支持模糊匹配）"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              autoComplete="off"
              maxLength={50}
            />
            <button type="submit" className="user-search-btn" disabled={loading}>
              搜索
            </button>
            {submittedKeyword && (
              <button
                type="button"
                className="user-search-clear"
                onClick={handleClearSearch}
                disabled={loading}
              >
                清空
              </button>
            )}
          </form>

          {/* 搜索结果提示 */}
          {submittedKeyword && !loading && !error && (
            <div className="user-search-result">
              {searchedEmpty
                ? `未找到匹配「${submittedKeyword}」的用户`
                : `匹配「${submittedKeyword}」的用户：${users.length} 条`}
            </div>
          )}

          {error && <div className="user-mgmt-error">{error}</div>}
          {toast && <div className="user-mgmt-toast">{toast}</div>}

          {loading ? (
            <div className="user-mgmt-loading">加载用户数据中...</div>
          ) : users.length === 0 ? (
            <div className="user-mgmt-empty">
              {searchedEmpty ? '没有匹配的用户' : '暂无用户'}
            </div>
          ) : (
            <table className="user-mgmt-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>用户名</th>
                  <th>角色</th>
                  <th>注册时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const isSelf = u.id === currentUser?.id;
                  return (
                    <tr key={u.id} className={isSelf ? 'row-self' : ''}>
                      <td className="cell-id">{u.id}</td>
                      <td className="cell-username">
                        {u.username}
                        {isSelf && <span className="self-tag">（我自己）</span>}
                      </td>
                      <td className="cell-role">
                        <span className={`role-pill role-${u.role}`}>
                          {u.role === 'admin' ? '管理员' : '普通用户'}
                        </span>
                      </td>
                      <td className="cell-time">{u.created_at}</td>
                      <td className="cell-action">
                        <div className="action-group">
                          {isSelf ? (
                            <span className="action-disabled" title="不允许修改自己的角色">
                              不可修改
                            </span>
                          ) : (
                            <button
                              className={`role-toggle-btn ${
                                u.role === 'admin' ? 'btn-downgrade' : 'btn-promote'
                              }`}
                              onClick={() => handleClickRole(u)}
                              disabled={deleting}
                            >
                              {u.role === 'admin' ? '降级' : '提升'}
                            </button>
                          )}
                          {!isSelf && (
                            <button
                              className="delete-btn"
                              onClick={() => handleClickDelete(u)}
                              disabled={deleting}
                              title="删除该用户（同时清理其问答记录）"
                            >
                              删除
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}

          <div className="user-mgmt-tip">
            安全约束：不允许修改自己的角色 / 删除自己 / 删除最后一个管理员。
            删除用户将级联清理其全部问答记录，操作不可恢复，且会被记录到审计日志。
          </div>
        </div>
      </main>

      {/* 角色变更确认弹窗 */}
      {pendingChange && (
        <div className="confirm-overlay" onClick={handleCancelChange}>
          <div className="confirm-dialog" onClick={(e) => e.stopPropagation()}>
            <h3>确认{pendingChange.action}</h3>
            <p>
              即将把用户 <strong>{pendingChange.user.username}</strong>（ID: {pendingChange.user.id}）
              的角色从 <strong>{pendingChange.user.role}</strong> 修改为{' '}
              <strong>{pendingChange.targetRole}</strong>。
            </p>
            <p className="confirm-warn">
              此操作将影响该用户的权限，且会被记录到审计日志。
            </p>
            <div className="confirm-actions">
              <button className="cancel-btn" onClick={handleCancelChange}>
                取消
              </button>
              <button
                className="confirm-btn confirm-btn-primary"
                onClick={handleConfirmChange}
              >
                确认{pendingChange.action}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 删除用户确认弹窗 */}
      {pendingDelete && (
        <div className="confirm-overlay" onClick={handleCancelDelete}>
          <div className="confirm-dialog confirm-dialog-danger" onClick={(e) => e.stopPropagation()}>
            <h3>确认删除用户</h3>
            <p>
              即将删除用户 <strong>{pendingDelete.user.username}</strong>（ID: {pendingDelete.user.id}，
              角色: {pendingDelete.user.role}）。
            </p>
            <p className="confirm-warn">
              该操作不可恢复：将同时清理该用户的全部问答记录（qa_history），
              保留审计日志以便追溯。请确认你已知晓后果。
            </p>
            <div className="confirm-actions">
              <button className="cancel-btn" onClick={handleCancelDelete} disabled={deleting}>
                取消
              </button>
              <button
                className="confirm-btn btn-danger"
                onClick={handleConfirmDelete}
                disabled={deleting}
              >
                {deleting ? '删除中' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default UserManagement;
