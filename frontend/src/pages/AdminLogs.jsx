import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import {
  generateLogs,
  uploadLog,
  getTaskStatus,
  listTasks,
  getStats,
} from '../api/ingest';
import './AdminLogs.css';

const POLL_INTERVAL_MS = 3000; // 任务进行中每 3 秒轮询一次

const AdminLogs = () => {
  const { user } = useAuth();

  // 统计数据
  const [stats, setStats] = useState(null);
  const [statsLoading, setStatsLoading] = useState(true);

  // 生成模式表单
  const [genCount, setGenCount] = useState(10000);
  const [genVectorize, setGenVectorize] = useState(true);
  const [genRebuild, setGenRebuild] = useState(false);

  // 上传模式
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadVectorize, setUploadVectorize] = useState(true);
  const [uploadRebuild, setUploadRebuild] = useState(false);
  const [uploadMaxLogs, setUploadMaxLogs] = useState(10000); // 默认限制 1 万条

  // 任务列表
  const [tasks, setTasks] = useState([]);
  // 当前活跃任务（轮询用）
  const [activeTaskId, setActiveTaskId] = useState(null);
  const [activeTaskToken, setActiveTaskToken] = useState(null); // 任务专用长期 token
  const activeTaskRef = useRef(null);

  // UI 状态
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // ============ 数据加载 ============
  const fetchStats = useCallback(async () => {
    try {
      const data = await getStats();
      if (data.success) setStats(data.data);
    } catch (err) {
      console.error('加载统计失败:', err);
    } finally {
      setStatsLoading(false);
    }
  }, []);

  const fetchTasks = useCallback(async () => {
    try {
      const data = await listTasks(20);
      if (data.success) {
        setTasks(data.data || []);
        // 找出正在运行的任务
        const running = (data.data || []).find(
          (t) => t.status === 'running' || t.status === 'pending'
        );
        if (running) {
          setActiveTaskId(running.task_id);
        }
      }
    } catch (err) {
      console.error('加载任务列表失败:', err);
    }
  }, []);

  useEffect(() => {
    fetchStats();
    fetchTasks();
  }, [fetchStats, fetchTasks]);

  // ============ 任务轮询 ============
  useEffect(() => {
    if (!activeTaskId) return;
    activeTaskRef.current = activeTaskId;

    const poll = async () => {
      try {
        // 优先用 task_token 轮询，避免登录 token 过期后无法查询
        const data = await getTaskStatus(activeTaskRef.current, activeTaskToken);
        if (!data.success) return;
        const task = data.data;

        // 更新任务列表中的对应项
        setTasks((prev) =>
          prev.map((t) => (t.task_id === task.task_id ? task : t))
        );

        if (task.status === 'done' || task.status === 'failed') {
          // 任务结束，停止轮询
          setActiveTaskId(null);
          setActiveTaskToken(null);
          activeTaskRef.current = null;
          // 刷新统计
          fetchStats();
          if (task.status === 'done') {
            showToast('入库任务已完成');
          } else {
            setError(`任务失败: ${task.error || '未知错误'}`);
          }
        }
      } catch (err) {
        console.error('轮询任务状态失败:', err);
        // 401 时如果是 task_token 也失败了，停止轮询避免刷屏
        if (err.response?.status === 401) {
          setActiveTaskId(null);
          setActiveTaskToken(null);
          setError('任务状态查询鉴权失败，请刷新页面查看任务列表');
        }
      }
    };

    // 立即跑一次，然后定时跑
    poll();
    const timer = setInterval(poll, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [activeTaskId, activeTaskToken, fetchStats]);

  // ============ 交互 ============
  const showToast = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(''), 3500);
  };

  const handleGenerate = async (e) => {
    e.preventDefault();
    if (submitting) return;
    setError('');
    setSubmitting(true);
    try {
      const res = await generateLogs({
        count: genCount,
        vectorize: genVectorize,
        rebuildVector: genRebuild,
      });
      if (res.success) {
        setActiveTaskId(res.task_id);
        setActiveTaskToken(res.task_token || null);
        // 把新任务塞进列表头部
        setTasks((prev) => [
          {
            task_id: res.task_id,
            task_type: 'generate',
            status: 'pending',
            current_step: null,
            steps: {},
            started_at: new Date().toISOString(),
          },
          ...prev,
        ]);
        showToast(`任务已启动: ${res.task_id}`);
      }
    } catch (err) {
      const msg = err.response?.data?.detail || '启动生成任务失败';
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (submitting) return;
    if (!uploadFile) {
      setError('请先选择日志文件');
      return;
    }
    setError('');
    setSubmitting(true);
    try {
      const res = await uploadLog(uploadFile, {
        vectorize: uploadVectorize,
        rebuildVector: uploadRebuild,
        maxLogs: uploadMaxLogs,
      });
      if (res.success) {
        setActiveTaskId(res.task_id);
        setActiveTaskToken(res.task_token || null);
        setTasks((prev) => [
          {
            task_id: res.task_id,
            task_type: 'upload',
            status: 'pending',
            current_step: null,
            steps: {},
            started_at: new Date().toISOString(),
            artifacts: { filename: uploadFile.name },
          },
          ...prev,
        ]);
        showToast(`文件已上传，任务已启动: ${res.task_id}`);
        setUploadFile(null);
        // 重置 file input
        const fileInput = document.getElementById('ingest-file-input');
        if (fileInput) fileInput.value = '';
      }
    } catch (err) {
      const msg = err.response?.data?.detail || '上传失败';
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleFileChange = (e) => {
    const f = e.target.files?.[0];
    if (f) {
      // 校验后缀
      const name = f.name.toLowerCase();
      const isSupported = name.endsWith('.csv') || name.endsWith('.log') || name.endsWith('.txt');
      if (!isSupported) {
        setError('仅支持 .csv / .log / .txt 文件');
        return;
      }
      setError('');
      setUploadFile(f);
    }
  };

  // ============ 渲染辅助 ============
  const isBusy = !!activeTaskId || submitting;

  const renderStepProgress = (task) => {
    const steps = ['convert', 'parse', 'clean', 'import', 'vectorize'];
    const labels = {
      convert: '转换',
      parse: '解析',
      clean: '清洗',
      import: '入库',
      vectorize: '向量化',
    };
    return (
      <div className="task-steps">
        {steps.map((name) => {
          const sp = task.steps?.[name] || {};
          let detail = '';
          if (name === 'convert' && sp.detail) {
            if (sp.status === 'skipped') detail = 'CSV 直入';
            else if (sp.detail.generated) detail = `生成 ${sp.detail.generated}`;
            else if (sp.detail.valid !== undefined) {
              detail = `格式 ${sp.detail.format || '?'} / 有效 ${sp.detail.valid}`;
              if (sp.detail.failed) detail += ` / 失败 ${sp.detail.failed}`;
            }
          } else if (name === 'parse' && sp.detail) {
            detail = sp.detail.failed
              ? `有效 ${sp.detail.valid || 0} / 失败 ${sp.detail.failed}`
              : `有效 ${sp.detail.valid || 0}`;
          } else if (name === 'clean' && sp.detail?.output !== undefined) {
            detail = `保留 ${sp.detail.output}`;
            if (sp.detail.removed_duplicate) detail += ` / 去重 ${sp.detail.removed_duplicate}`;
          } else if (name === 'import' && sp.detail?.inserted !== undefined) {
            detail = `插入 ${sp.detail.inserted}`;
            if (sp.detail.skipped_duplicate) detail += ` / 跳过 ${sp.detail.skipped_duplicate}`;
          } else if (name === 'vectorize') {
            if (sp.status === 'skipped') detail = '已跳过';
            else if (sp.detail?.total) detail = `${sp.detail.processed || 0} / ${sp.detail.total}`;
            else if (sp.status === 'done') detail = '完成';
          }
          return (
            <span key={name} className={`step-pill step-${sp.status || 'pending'}`}>
              <span className="step-name">{labels[name]}</span>
              {detail && <span className="step-detail">{detail}</span>}
            </span>
          );
        })}
      </div>
    );
  };

  const renderStatusBadge = (status) => {
    const map = {
      pending: '待开始',
      running: '运行中',
      done: '完成',
      failed: '失败',
    };
    return <span className={`status-badge status-${status}`}>{map[status] || status}</span>;
  };

  return (
    <div className="admin-logs-container">
      {/* 顶部导航 */}
      <header className="admin-logs-header">
        <div className="admin-logs-title-row">
          <Link to="/dashboard" className="back-link">← 返回</Link>
          <h1>日志管理</h1>
        </div>
        <div className="admin-logs-user">
          <span>{user?.username}</span>
          <span className="role-pill role-admin">管理员</span>
        </div>
      </header>

      <main className="admin-logs-main">
        {error && <div className="admin-logs-error">{error}</div>}
        {toast && <div className="admin-logs-toast">{toast}</div>}

        {/* 统计概览 */}
        <section className="stats-section">
          <h2 className="section-title">统计概览</h2>
          {statsLoading ? (
            <div className="loading-placeholder">加载统计中...</div>
          ) : stats ? (
            <div className="stats-grid">
              <div className="stat-card">
                <div className="stat-label">数据库日志</div>
                <div className="stat-value">{stats.db_total ?? 0}</div>
              </div>
              <div className="stat-card">
                <div className="stat-label">向量库日志</div>
                <div className="stat-value">
                  {stats.qdrant_total < 0 ? '连接失败' : stats.qdrant_total}
                </div>
              </div>
              <div className="stat-card">
                <div className="stat-label">最近入库</div>
                <div className="stat-value stat-time">
                  {stats.last_ingest_at || '—'}
                </div>
              </div>
              <div className="stat-card stat-card-wide">
                <div className="stat-label">按级别分布</div>
                <div className="stat-distribution">
                  {Object.entries(stats.by_level || {}).map(([k, v]) => (
                    <span key={k} className={`dist-pill dist-${k.toLowerCase()}`}>
                      {k}: {v}
                    </span>
                  ))}
                </div>
              </div>
              <div className="stat-card stat-card-wide">
                <div className="stat-label">按服务分布</div>
                <div className="stat-distribution">
                  {Object.entries(stats.by_service || {}).map(([k, v]) => (
                    <span key={k} className="dist-pill">{k}: {v}</span>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="loading-placeholder">无法加载统计</div>
          )}
        </section>

        {/* 生成模拟日志 */}
        <section className="action-section">
          <h2 className="section-title">生成模拟日志</h2>
          <p className="section-hint">
            生成指定条数的模拟日志，自动走完整入库流水线（解析 → 清洗 → 入库 → 向量化）。主要用于快速测试。
          </p>
          <form className="action-form" onSubmit={handleGenerate}>
            <label className="form-field">
              <span className="form-label">生成条数</span>
              <input
                type="number"
                min="1"
                max="100000"
                value={genCount}
                onChange={(e) => setGenCount(Number(e.target.value))}
                disabled={isBusy}
              />
            </label>
            <label className="form-checkbox">
              <input
                type="checkbox"
                checked={genVectorize}
                onChange={(e) => setGenVectorize(e.target.checked)}
                disabled={isBusy}
              />
              <span>入库后向量化</span>
            </label>
            <label className="form-checkbox">
              <input
                type="checkbox"
                checked={genRebuild}
                onChange={(e) => setGenRebuild(e.target.checked)}
                disabled={isBusy}
              />
              <span>重建向量索引（清空 Qdrant）</span>
            </label>
            <button type="submit" className="action-btn" disabled={isBusy}>
              {submitting ? '提交中...' : '开始生成'}
            </button>
          </form>
        </section>

        {/* 上传日志文件 */}
        <section className="action-section">
          <h2 className="section-title">上传日志文件入库</h2>
          <p className="section-hint">
            上传真实日志文件，走完整入库流水线。<strong>CSV 文件</strong>需包含字段：
            <code>timestamp, level, service, ip, message, trace_id</code>。
            <strong>.log / .txt 文件</strong>会自动识别格式并转换（当前支持 HDFS Loghub 数据集）。文件上限 200MB。
          </p>
          <form className="action-form" onSubmit={handleUpload}>
            <label className="form-field form-field-file">
              <span className="form-label">日志文件</span>
              <input
                id="ingest-file-input"
                type="file"
                accept=".csv,.log,.txt"
                onChange={handleFileChange}
                disabled={isBusy}
              />
              {uploadFile && (
                <span className="file-name">
                  {uploadFile.name} ({(uploadFile.size / 1024).toFixed(1)} KB)
                </span>
              )}
            </label>
            <label className="form-field">
              <span className="form-label">最大转换条数（仅 .log）</span>
              <input
                type="number"
                min="0"
                value={uploadMaxLogs}
                onChange={(e) => setUploadMaxLogs(Number(e.target.value))}
                disabled={isBusy}
                title="0 表示不限制。建议先用 10000 条测试"
              />
            </label>
            <label className="form-checkbox">
              <input
                type="checkbox"
                checked={uploadVectorize}
                onChange={(e) => setUploadVectorize(e.target.checked)}
                disabled={isBusy}
              />
              <span>入库后向量化</span>
            </label>
            <label className="form-checkbox">
              <input
                type="checkbox"
                checked={uploadRebuild}
                onChange={(e) => setUploadRebuild(e.target.checked)}
                disabled={isBusy}
              />
              <span>重建向量索引</span>
            </label>
            <button type="submit" className="action-btn" disabled={isBusy || !uploadFile}>
              {submitting ? '上传中...' : '开始上传'}
            </button>
          </form>
        </section>

        {/* 任务历史 */}
        <section className="tasks-section">
          <h2 className="section-title">任务历史</h2>
          {tasks.length === 0 ? (
            <div className="empty-placeholder">暂无入库任务</div>
          ) : (
            <div className="task-list">
              {tasks.map((t) => (
                <div key={t.task_id} className={`task-card task-card-${t.status}`}>
                  <div className="task-card-header">
                    <span className="task-type">
                      {t.task_type === 'upload' ? '上传入库' : '模拟生成'}
                    </span>
                    {renderStatusBadge(t.status)}
                    <span className="task-id">{t.task_id}</span>
                    <span className="task-time">{t.started_at || '—'}</span>
                  </div>
                  {renderStepProgress(t)}
                  {t.error && <div className="task-error">{t.error}</div>}
                  {t.artifacts?.filename && (
                    <div className="task-artifact">文件: {t.artifacts.filename}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
};

export default AdminLogs;
