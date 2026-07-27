import apiClient from './client';

/**
 * 日志入库管理 API（仅 admin 可用）
 */

// 触发模拟日志生成 + 入库流水线
export async function generateLogs({ count = 10000, vectorize = true, rebuildVector = false } = {}) {
  const res = await apiClient.post('/api/ingest/generate', {
    count,
    vectorize,
    rebuild_vector: rebuildVector,
  });
  return res.data;
}

// 上传日志文件并入库（支持 .csv / .log / .txt）
export async function uploadLog(file, { vectorize = true, rebuildVector = false, maxLogs = 0 } = {}) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await apiClient.post('/api/ingest/upload', formData, {
    params: {
      vectorize,
      rebuild_vector: rebuildVector,
      max_logs: maxLogs,
    },
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000, // 大日志文件可能很大，给 5 分钟
  });
  return res.data;
}

/**
 * 查询指定任务状态（支持 task_token 鉴权）
 *
 * @param {string} taskId - 任务 ID
 * @param {string} [taskToken] - 任务专用长期 token（7 天有效）。
 *   传入则优先用 task_token，避免登录 token 过期后无法轮询。
 *   不传则回退到普通 admin token（依赖 apiClient 默认 Authorization 头）。
 */
export async function getTaskStatus(taskId, taskToken) {
  const headers = {};
  if (taskToken) {
    // 用 task_token 覆盖默认的 Authorization 头
    headers.Authorization = `Bearer ${taskToken}`;
  }
  const res = await apiClient.get(`/api/ingest/tasks/${taskId}`, { headers });
  return res.data;
}

// 列出最近任务
export async function listTasks(limit = 20) {
  const res = await apiClient.get('/api/ingest/tasks', { params: { limit } });
  return res.data;
}

// 数据库 + 向量库统计
export async function getStats() {
  const res = await apiClient.get('/api/ingest/stats');
  return res.data;
}

// 支持的日志格式列表
export async function getSupportedFormats() {
  const res = await apiClient.get('/api/ingest/formats');
  return res.data;
}
