import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import {
  generateLogs,
  uploadLog,
  getTaskStatus,
  cancelTask,
  listTasks,
  getStats,
  rebuildIndexes,
} from '../api/ingest';
import './AdminLogs.css';

const POLL_INTERVAL_MS = 2000; // 任务进行中每 2 秒轮询一次

const AdminLogs = () => {
  const { user } = useAuth();

  // 统计数据
  const [stats, setStats] = useState(null);
  const [statsLoading, setStatsLoading] = useState(true);

  // 生成模式表单
  const [genCount, setGenCount] = useState(10000);
  const [genRebuild, setGenRebuild] = useState(false);

  // 上传模式
  const [uploadFile, setUploadFile] = useState(null);
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
            const doneMsg = task.task_type === 'rebuild'
              ? '索引重建任务已完成'
              : '入库任务已完成';
            showToast(doneMsg);
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
        vectorize: true,
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
        vectorize: true,
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

  const handleCancelTask = async () => {
    if (!activeTaskId) return;
    try {
      const res = await cancelTask(activeTaskId);
      if (res.success) {
        showToast('取消请求已发送，等待当前批次完成...');
      } else {
        setError(res.detail || '取消失败');
      }
    } catch (err) {
      setError('取消请求失败: ' + (err.response?.data?.detail || err.message));
    }
  };

  // 补建索引（失败任务恢复或事后补建 BM25）
  // mode: 'vector' | 'bm25' | 'both'
  const handleRebuild = async (mode) => {
    try {
      const res = await rebuildIndexes({ mode, rebuildVector: false });
      if (res.success) {
        setActiveTaskId(res.task_id);
        setActiveTaskToken(res.task_token || null);
        // 把重建任务塞进列表头部
        setTasks((prev) => [
          {
            task_id: res.task_id,
            task_type: 'rebuild',
            status: 'pending',
            current_step: null,
            steps: {},
            started_at: new Date().toISOString(),
          },
          ...prev,
        ]);
        showToast(res.message || '索引重建任务已启动');
      } else {
        setError(res.detail || '重建失败');
      }
    } catch (err) {
      setError('重建请求失败: ' + (err.response?.data?.detail || err.message));
    }
  };

  // 计算当前任务总进度百分比
  const getOverallProgress = (task) => {
    if (!task?.steps) return null;
    const vec = task.steps.vectorize;
    if (vec?.status === 'running' && vec.detail?.total > 0) {
      // 向量化阶段：用 processed/total
      return Math.round(((vec.detail.processed || 0) / vec.detail.total) * 100);
    }
    const parse = task.steps.parse;
    const convert = task.steps.convert;
    if (parse?.status === 'running' || parse?.status === 'done') {
      // 解析/入库阶段：用 valid_so_far 估算（无法精确知道总数，用 convert 的 valid 作参考）
      const soFar = parse.detail?.valid_so_far ?? parse.detail?.valid ?? 0;
      const total = convert?.detail?.valid || 0;
      if (total > 0 && soFar > 0) {
        // 入库阶段占总进度 0-90%，向量化占 90-100%
        return Math.min(90, Math.round((soFar / total) * 90));
      }
    }
    if (convert?.status === 'running') return 5;
    return null;
  };

  // 计算已用时间
  const getElapsedTime = (task) => {
    if (!task?.started_at) return '';
    const start = new Date(task.started_at).getTime();
    const now = Date.now();
    const sec = Math.floor((now - start) / 1000);
    if (sec < 60) return `${sec} 秒`;
    if (sec < 3600) return `${Math.floor(sec / 60)} 分 ${sec % 60} 秒`;
    return `${Math.floor(sec / 3600)} 时 ${Math.floor((sec % 3600) / 60)} 分`;
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
          const status = sp.status || 'pending';
          let detail = '';

          if (name === 'convert') {
            if (status === 'skipped') detail = 'CSV 直入';
            else if (sp.detail?.generated) detail = `生成 ${sp.detail.generated}`;
            else if (sp.detail?.valid !== undefined) {
              detail = `${sp.detail.format || '?'} / ${sp.detail.valid} 条`;
              if (sp.detail.failed) detail += ` / 失败 ${sp.detail.failed}`;
            } else if (status === 'running') {
              detail = sp.detail?.sub_step === 'detecting' ? '识别格式...' : '转换中...';
            }
          } else if (name === 'parse') {
            if (status === 'running') {
              // 流式模式实时数据
              const v = sp.detail?.valid_so_far ?? sp.detail?.valid;
              const f = sp.detail?.failed_so_far ?? sp.detail?.failed;
              const chunks = sp.detail?.chunks;
              if (v !== undefined) {
                detail = `已解析 ${v.toLocaleString()} 条`;
                if (f) detail += ` / 失败 ${f}`;
                if (chunks) detail += ` / 第 ${chunks} 批`;
              } else {
                detail = '解析中...';
              }
            } else if (status === 'done') {
              detail = `${(sp.detail?.valid || 0).toLocaleString()} 条`;
              if (sp.detail?.failed) detail += ` / 失败 ${sp.detail.failed}`;
              if (sp.detail?.chunks) detail += ` / ${sp.detail.chunks} 批`;
            }
          } else if (name === 'clean') {
            if (status === 'running') {
              detail = '同步清洗中...';
            } else if (status === 'done') {
              detail = `保留 ${(sp.detail?.output || 0).toLocaleString()}`;
              if (sp.detail?.removed_empty) detail += ` / 空值 ${sp.detail.removed_empty}`;
              if (sp.detail?.removed_duplicate) detail += ` / 去重 ${sp.detail.removed_duplicate.toLocaleString()}`;
            }
          } else if (name === 'import') {
            if (status === 'running') {
              const ins = sp.detail?.inserted_so_far ?? sp.detail?.inserted;
              detail = ins !== undefined ? `已入库 ${ins.toLocaleString()} 条` : '入库中...';
            } else if (status === 'done') {
              detail = `插入 ${(sp.detail?.inserted || 0).toLocaleString()}`;
              if (sp.detail?.skipped_duplicate) detail += ` / 跳过 ${sp.detail.skipped_duplicate.toLocaleString()}`;
            }
          } else if (name === 'vectorize') {
            if (status === 'skipped') {
              detail = '已跳过';
            } else if (status === 'running') {
              // 区分子步骤：向量补建 vs BM25 重建
              if (sp.detail?.sub_step === 'bm25') {
                if (sp.detail.phase === 'loading' && sp.detail.total > 0) {
                  const pct = Math.round(((sp.detail.processed || 0) / sp.detail.total) * 100);
                  detail = `BM25 加载 ${sp.detail.processed.toLocaleString()} / ${sp.detail.total.toLocaleString()} (${pct}%)`;
                } else if (sp.detail.phase === 'building') {
                  detail = `BM25 构建中（${(sp.detail.total || 0).toLocaleString()} 条）...`;
                } else {
                  detail = 'BM25 重建中...';
                }
              } else if (sp.detail?.sub_step === 'vector' && sp.detail?.total > 0) {
                const pct = Math.round(((sp.detail.processed || 0) / sp.detail.total) * 100);
                detail = `${(sp.detail.processed || 0).toLocaleString()} / ${sp.detail.total.toLocaleString()} (${pct}%)`;
              } else if (sp.detail?.total > 0) {
                // 兼容旧格式（无 sub_step）
                const pct = Math.round(((sp.detail.processed || 0) / sp.detail.total) * 100);
                detail = `${(sp.detail.processed || 0).toLocaleString()} / ${sp.detail.total.toLocaleString()} (${pct}%)`;
              } else {
                detail = '向量化中...';
              }
            } else if (status === 'done') {
              detail = sp.detail?.total ? `${sp.detail.total.toLocaleString()} 条完成` : '完成';
            }
          }

          return (
            <span key={name} className={`step-pill step-${status}`}>
              <span className="step-name">{labels[name]}</span>
              {detail && <span className="step-detail">{detail}</span>}
              {name === 'vectorize' && status === 'running' && sp.detail?.total > 0 && (
                <span className="step-bar">
                  <span
                    className="step-bar-fill"
                    style={{ width: `${Math.round(((sp.detail.processed || 0) / sp.detail.total) * 100)}%` }}
                  />
                </span>
              )}
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
          <h1>日志管理</h1>
          <Link to="/dashboard" className="back-link">返回工作台</Link>
          
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
            <strong>.log / .txt 文件</strong>会自动识别格式并转换（当前支持 HDFS Loghub 数据集）
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

        {/* 当前任务（仅运行中/等待中时显示） */}
        {(() => {
          const activeTask = tasks.find(
            (t) => t.task_id === activeTaskId && (t.status === 'running' || t.status === 'pending')
          );
          if (!activeTask) return null;
          const progress = getOverallProgress(activeTask);
          return (
            <section className="current-task-section">
              <h2 className="section-title">当前任务</h2>
              <div className="current-task-card">
                <div className="current-task-header">
                  <span className="task-type">
                    {activeTask.task_type === 'upload' ? '上传入库'
                      : activeTask.task_type === 'rebuild' ? '索引重建'
                      : '模拟生成'}
                  </span>
                  {renderStatusBadge(activeTask.status)}
                  <span className="task-id">{activeTask.task_id}</span>
                  <span className="current-task-elapsed">已用时 {getElapsedTime(activeTask)}</span>
                </div>

                {/* 总进度条 */}
                {progress !== null && (
                  <div className="overall-progress">
                    <div className="overall-progress-bar">
                      <div className="overall-progress-fill" style={{ width: `${progress}%` }} />
                    </div>
                    <span className="overall-progress-text">{progress}%</span>
                  </div>
                )}

                {/* 步骤详情 */}
                {renderStepProgress(activeTask)}

                {/* 文件清单 */}
                <div className="current-task-files">
                  {activeTask.artifacts?.filename && (
                    <span className="file-tag">源文件: {activeTask.artifacts.filename}</span>
                  )}
                  {activeTask.artifacts?.converted_csv && (
                    <span className="file-tag file-tag-temp">中间文件: converted_{activeTask.task_id}.csv</span>
                  )}
                  {activeTask.artifacts?.source_file && (
                    <span className="file-tag file-tag-temp">上传路径: {activeTask.artifacts.source_file}</span>
                  )}
                </div>

                {/* 错误信息 */}
                {activeTask.error && <div className="task-error">{activeTask.error}</div>}

                {/* 取消按钮 */}
                <div className="current-task-actions">
                  <button className="cancel-btn" onClick={handleCancelTask}>
                    取消任务
                  </button>
                </div>
              </div>
            </section>
          );
        })()}

        {/* 任务历史（仅已完成/失败） */}
        <section className="tasks-section">
          <h2 className="section-title">任务历史</h2>
          {(() => {
            const historyTasks = tasks.filter(
              (t) => t.status === 'done' || t.status === 'failed'
            );
            if (historyTasks.length === 0) {
              return <div className="empty-placeholder">暂无已完成的任务</div>;
            }
            return (
              <div className="task-list">
                {historyTasks.map((t) => {
                  const taskTypeLabel = {
                    upload: '上传入库',
                    generate: '模拟生成',
                    rebuild: '索引重建',
                  }[t.task_type] || t.task_type;
                  // 失败任务可恢复的条件：vectorize 步骤失败或未完成
                  const vecStep = t.steps?.vectorize;
                  const canRetryVector = t.status === 'failed' && vecStep?.status === 'failed';
                  const canRebuildBm25 = t.status === 'failed' || t.status === 'done';
                  return (
                    <div key={t.task_id} className={`task-card task-card-${t.status}`}>
                      <div className="task-card-header">
                        <span className="task-type">{taskTypeLabel}</span>
                        {renderStatusBadge(t.status)}
                        <span className="task-id">{t.task_id}</span>
                        <span className="task-time">{t.started_at || '—'}</span>
                      </div>
                      {renderStepProgress(t)}
                      {t.error && <div className="task-error">{t.error}</div>}
                      {t.artifacts?.filename && (
                        <div className="task-artifact">文件: {t.artifacts.filename}</div>
                      )}
                      {/* 失败任务恢复操作 */}
                      {canRetryVector && (
                        <div className="task-actions">
                          <button
                            className="rebuild-btn"
                            onClick={() => handleRebuild('vector')}
                          >
                            重试向量化
                          </button>
                          <button
                            className="rebuild-btn"
                            onClick={() => handleRebuild('both')}
                          >
                            重试向量化 + 重建 BM25
                          </button>
                        </div>
                      )}
                      {!canRetryVector && canRebuildBm25 && t.task_type !== 'rebuild' && (
                        <div className="task-actions">
                          <button
                            className="rebuild-btn"
                            onClick={() => handleRebuild('bm25')}
                          >
                            重建 BM25 索引
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            );
          })()}
        </section>
      </main>
    </div>
  );
};

export default AdminLogs;
