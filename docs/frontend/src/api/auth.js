import apiClient from './client';

// 注册
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