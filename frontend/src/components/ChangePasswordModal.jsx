import React, { useState, useEffect, useRef } from 'react';
import { changePassword } from '../api/auth';
import './ChangePasswordModal.css';

/**
 * 修改密码弹窗
 * - 需提供旧密码验证
 * - 新密码 6-50 字符，不能与旧密码相同
 * - 两次输入新密码需一致
 * - 修改成功后自动登出，要求用户使用新密码重新登录
 */
const ChangePasswordModal = ({ open, onClose, onSuccess }) => {
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showOld, setShowOld] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const oldInputRef = useRef(null);

  // 弹窗打开时自动聚焦旧密码输入框，并重置所有状态
  useEffect(() => {
    if (open) {
      setOldPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setError('');
      setSuccess('');
      setShowOld(false);
      setShowNew(false);
      setShowConfirm(false);
      // 延迟聚焦，等渲染稳定
      setTimeout(() => oldInputRef.current?.focus(), 50);
    }
  }, [open]);

  // ESC 键关闭
  useEffect(() => {
    if (!open) return;
    const handleKey = (e) => {
      if (e.key === 'Escape' && !submitting) {
        onClose?.();
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [open, submitting, onClose]);

  if (!open) return null;

  // 表单校验
  const validate = () => {
    if (!oldPassword) return '请输入旧密码';
    if (!newPassword) return '请输入新密码';
    if (newPassword.length < 6 || newPassword.length > 50) {
      return '新密码长度需 6-50 字符';
    }
    if (oldPassword === newPassword) return '新密码不能与旧密码相同';
    if (newPassword !== confirmPassword) return '两次输入的新密码不一致';
    return '';
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    setError('');
    setSubmitting(true);
    try {
      const result = await changePassword(oldPassword, newPassword);
      setSuccess(result.message || '密码修改成功');
      // 1.5s 后触发成功回调（通常用于登出并跳转登录页）
      setTimeout(() => {
        onSuccess?.(result);
      }, 1500);
    } catch (err) {
      const msg = err.response?.data?.detail || '密码修改失败，请重试';
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="cp-overlay" onClick={() => !submitting && !success && onClose?.()}>
      <div className="cp-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="cp-header">
          <h3>修改密码</h3>
          {!submitting && !success && (
            <button className="cp-close" onClick={onClose} title="关闭">
              关闭
            </button>
          )}
        </div>

        {success ? (
          <div className="cp-success">
            <div className="cp-success-icon">完成</div>
            <p>{success}</p>
            <p className="cp-success-tip">即将退出登录，请使用新密码重新登录</p>
          </div>
        ) : (
          <form className="cp-form" onSubmit={handleSubmit}>
            {error && <div className="cp-error">{error}</div>}

            <div className="cp-field">
              <label htmlFor="cp-old">旧密码</label>
              <div className="cp-input-wrap">
                <input
                  id="cp-old"
                  ref={oldInputRef}
                  type={showOld ? 'text' : 'password'}
                  value={oldPassword}
                  onChange={(e) => setOldPassword(e.target.value)}
                  placeholder="请输入当前密码"
                  maxLength={50}
                  autoComplete="current-password"
                  disabled={submitting}
                />
                <button
                  type="button"
                  className="cp-toggle"
                  onClick={() => setShowOld((s) => !s)}
                  tabIndex={-1}
                  title={showOld ? '隐藏' : '显示'}
                >
                  {showOld ? '隐藏' : '显示'}
                </button>
              </div>
            </div>

            <div className="cp-field">
              <label htmlFor="cp-new">新密码</label>
              <div className="cp-input-wrap">
                <input
                  id="cp-new"
                  type={showNew ? 'text' : 'password'}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="6-50 字符，不能与旧密码相同"
                  maxLength={50}
                  autoComplete="new-password"
                  disabled={submitting}
                />
                <button
                  type="button"
                  className="cp-toggle"
                  onClick={() => setShowNew((s) => !s)}
                  tabIndex={-1}
                  title={showNew ? '隐藏' : '显示'}
                >
                  {showNew ? '隐藏' : '显示'}
                </button>
              </div>
            </div>

            <div className="cp-field">
              <label htmlFor="cp-confirm">确认新密码</label>
              <div className="cp-input-wrap">
                <input
                  id="cp-confirm"
                  type={showConfirm ? 'text' : 'password'}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="再次输入新密码"
                  maxLength={50}
                  autoComplete="new-password"
                  disabled={submitting}
                />
                <button
                  type="button"
                  className="cp-toggle"
                  onClick={() => setShowConfirm((s) => !s)}
                  tabIndex={-1}
                  title={showConfirm ? '隐藏' : '显示'}
                >
                  {showConfirm ? '隐藏' : '显示'}
                </button>
              </div>
            </div>

            <div className="cp-actions">
              <button
                type="button"
                className="cp-cancel"
                onClick={onClose}
                disabled={submitting}
              >
                取消
              </button>
              <button type="submit" className="cp-submit" disabled={submitting}>
                {submitting ? '提交中' : '确认修改'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};

export default ChangePasswordModal;
