import React, { createContext, useState, useContext, useEffect } from 'react';
import { getCurrentUser, login as apiLogin, register as apiRegister } from '../api/auth';

const AuthContext = createContext(null);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // 初始化时从 localStorage 恢复用户信息
  useEffect(() => {
    const initAuth = async () => {
      const token = localStorage.getItem('access_token');
      const savedUser = localStorage.getItem('user');
      
      if (token && savedUser) {
        try {
          // 验证 token 是否有效
          const userData = await getCurrentUser();
          setUser(userData);
          localStorage.setItem('user', JSON.stringify(userData));
        } catch (err) {
          // Token 无效，清除存储
          localStorage.removeItem('access_token');
          localStorage.removeItem('user');
          setUser(null);
        }
      }
      setLoading(false);
    };
    
    initAuth();
  }, []);

  // 登录
  const login = async (username, password) => {
    try {
      setError(null);
      const data = await apiLogin(username, password);
      
      // 保存 Token
      localStorage.setItem('access_token', data.access_token);
      
      // 保存用户信息（从登录响应中获取）
      const userData = {
        id: data.user_id,
        username: data.username,
        role: data.role,
        created_at: data.created_at,
      };
      setUser(userData);
      localStorage.setItem('user', JSON.stringify(userData));
      
      return { success: true };
    } catch (err) {
      const errorMsg = err.response?.data?.detail || '登录失败，请重试';
      setError(errorMsg);
      return { success: false, error: errorMsg };
    }
  };

  // 注册
  const register = async (username, password) => {
    try {
      setError(null);
      const data = await apiRegister(username, password);
      return { success: true, data };
    } catch (err) {
      const errorMsg = err.response?.data?.detail || '注册失败，请重试';
      setError(errorMsg);
      return { success: false, error: errorMsg };
    }
  };

  // 登出
  const logout = () => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('user');
    setUser(null);
  };

  const value = {
    user,
    loading,
    error,
    login,
    register,
    logout,
    isAuthenticated: !!user,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};