import apiClient from './client';

// 注册（角色由后端强制为 user，不再传 role）
export const register = async (username, password) => {
  const response = await apiClient.post('/api/auth/register', {
    username,
    password,
  });
  return response.data;
};

// 登录 - 使用 JSON 格式
export const login = async (username, password) => {
  const response = await apiClient.post('/api/auth/login', {
    username,
    password,
  });
  return response.data;
};

// 获取当前用户信息
export const getCurrentUser = async () => {
  const response = await apiClient.get('/api/auth/me');
  return response.data;
};

// 登出
export const logout = () => {
  localStorage.removeItem('access_token');
  localStorage.removeItem('user');
  window.location.href = '/login';
};

// ============================================================
// 当前用户自己的接口
// ============================================================

/**
 * 修改自己的密码（需提供旧密码验证）
 * @param {string} oldPassword - 旧密码
 * @param {string} newPassword - 新密码（6-50 字符，不能与旧密码相同）
 * @returns {Promise<Object>} { success, message }
 */
export const changePassword = async (oldPassword, newPassword) => {
  const response = await apiClient.post('/api/auth/me/password', {
    old_password: oldPassword,
    new_password: newPassword,
  });
  return response.data;
};

// ============================================================
// 管理员专用接口
// ============================================================

/**
 * 查询所有用户列表（仅 admin 可调用，支持按用户名模糊搜索）
 * @param {string} [username] - 可选，按用户名模糊搜索（包含匹配，大小写不敏感）
 * @returns {Promise<Object>} { success, total, items[] }
 *   items[]: { id, username, role, created_at }
 */
export const getAllUsers = async (username) => {
  const params = username && username.trim() ? { username: username.trim() } : {};
  const response = await apiClient.get('/api/auth/users', { params });
  return response.data;
};

/**
 * 修改指定用户的角色（仅 admin 可调用）
 * @param {number} userId - 被修改的用户 ID
 * @param {'admin' | 'user'} role - 目标角色
 * @returns {Promise<Object>} { success, user_id, username, old_role, new_role, message }
 */
export const setUserRole = async (userId, role) => {
  const response = await apiClient.patch(`/api/auth/users/${userId}/role`, { role });
  return response.data;
};

/**
 * 删除指定用户（仅 admin 可调用，级联删除其问答记录）
 * @param {number} userId - 被删除的用户 ID
 * @returns {Promise<Object>} { success, user_id, username, deleted_qa_count, message }
 */
export const deleteUser = async (userId) => {
  const response = await apiClient.delete(`/api/auth/users/${userId}`);
  return response.data;
};

// 统一导出
export default {
  register,
  login,
  getCurrentUser,
  logout,
  changePassword,
  getAllUsers,
  setUserRole,
  deleteUser,
};