import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { register as registerApi } from '../api/auth';
import './Login.css';

const Register = () => {
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');

    // 验证
    if (!username.trim() || username.length < 3) {
      setError('用户名至少3个字符');
      return;
    }
    if (!password.trim() || password.length < 6) {
      setError('密码至少6个字符');
      return;
    }
    if (password !== confirmPassword) {
      setError('两次输入的密码不一致');
      return;
    }

    setLoading(true);
    try {
      // 后端会强制把新注册用户的角色设为 user，
      // 如需 admin 角色需登录后由现有 admin 通过用户管理接口提升。
      await registerApi(username, password);
      setSuccess('注册成功！默认为普通用户角色。即将跳转到登录页...');
      setTimeout(() => {
        navigate('/login');
      }, 2000);
    } catch (err) {
      const msg = err.response?.data?.detail || '注册失败，请重试';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-card">
        <div className="login-header">
          <h1>日志智能问答系统</h1>
          <p>创建新账号</p>
        </div>

        <form onSubmit={handleSubmit} className="login-form">
          <div className="form-group">
            <label htmlFor="username">用户名</label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="请输入用户名（至少3个字符）"
              disabled={loading}
              autoComplete="username"
              autoFocus
            />
          </div>

          <div className="form-group">
            <label htmlFor="password">密码</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入密码（至少6个字符）"
              disabled={loading}
              autoComplete="new-password"
            />
          </div>

          <div className="form-group">
            <label htmlFor="confirmPassword">确认密码</label>
            <input
              id="confirmPassword"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="请再次输入密码"
              disabled={loading}
              autoComplete="new-password"
            />
          </div>

          {/* 角色说明：注册时无法选择角色，避免越权 */}
          <div className="role-info-box">
            <strong>角色说明</strong>
            <p>新注册用户默认为 <strong>普通用户（user）</strong>。</p>
            <p>如需 <strong>管理员（admin）</strong> 权限，请先注册并联系现有管理员在系统内提升你的角色。</p>
          </div>

          {error && <div className="error-message">{error}</div>}
          {success && <div className="success-message">{success}</div>}

          <button
            type="submit"
            className="login-btn"
            disabled={loading}
          >
            {loading ? '注册中...' : '注 册'}
          </button>
        </form>

        <div className="login-footer">
          已有账号？<Link to="/login">返回登录</Link>
        </div>
      </div>
    </div>
  );
};

export default Register;