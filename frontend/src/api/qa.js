import apiClient from './client';

// ============================================================
// 问答接口
// ============================================================

/**
 * 同步问答
 * @param {Object} params - { question, filters?, top_k?, template_type?, retriever_type?, conversation_id? }
 * @returns {Promise<Object>} QAResponse（含 conversation_id）
 */
export const askQuestion = async (params) => {
  const response = await apiClient.post('/api/qa/ask', {
    question: params.question,
    filters: params.filters || {},
    top_k: params.top_k ?? 5,
    template_type: params.template_type || '',
    retriever_type: params.retriever_type || 'hybrid',
    conversation_id: params.conversation_id || null,
  });
  return response.data;
};

/**
 * 流式问答 (SSE)
 *
 * 通过原生 fetch + ReadableStream 消费 SSE 事件，
 * axios 对流式响应支持不佳，故单独使用 fetch。
 *
 * @param {Object} params - { question, filters?, top_k?, template_type?, retriever_type?, conversation_id? }
 * @param {Object} handlers - 事件回调
 * @param {(data: Object) => void} [handlers.onSource] - 检索完成事件
 * @param {(data: Object) => void} [handlers.onAnswer] - 逐字输出事件 { content }
 * @param {(data: Object) => void} [handlers.onDone] - 流结束事件（含 conversation_id）
 * @param {(data: Object) => void} [handlers.onError] - 异常事件
 * @returns {Promise<void>} 流结束后 resolve
 */
export const askStreamQuestion = async (params, handlers = {}) => {
  const { onSource, onAnswer, onDone, onError } = handlers;

  const token = localStorage.getItem('access_token');
  const baseURL = import.meta.env.VITE_API_BASE_URL;

  const response = await fetch(`${baseURL}/api/qa/ask/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({
      question: params.question,
      filters: params.filters || {},
      top_k: params.top_k ?? 5,
      template_type: params.template_type || '',
      retriever_type: params.retriever_type || 'hybrid',
      conversation_id: params.conversation_id || null,
    }),
  });

  if (!response.ok) {
    const err = new Error(`HTTP ${response.status}`);
    onError?.({ message: err.message, status: response.status });
    throw err;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  // SSE 事件按空行分隔，每块可能含多行
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // 按空行切分事件块
    const parts = buffer.split('\n\n');
    buffer = parts.pop() || ''; // 最后一段可能不完整，留到下次

    for (const part of parts) {
      const event = _parseSseEvent(part);
      if (!event) continue;

      switch (event.type) {
        case 'source':
          onSource?.(event.data);
          break;
        case 'answer':
          onAnswer?.(event.data);
          break;
        case 'done':
          onDone?.(event.data);
          return; // 流结束
        case 'error':
          onError?.(event.data);
          return;
      }
    }
  }
};

/**
 * 解析单个 SSE 事件块
 * @param {string} block
 * @returns {{type: string, data: Object} | null}
 */
const _parseSseEvent = (block) => {
  let type = '';
  let dataStr = '';
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) {
      type = line.slice(7).trim();
    } else if (line.startsWith('data: ')) {
      dataStr += line.slice(6);
    }
  }
  if (!type) return null;
  try {
    const data = dataStr ? JSON.parse(dataStr) : {};
    return { type, data };
  } catch {
    return { type, data: { raw: dataStr } };
  }
};

// ============================================================
// 问答历史
// ============================================================

/**
 * 查询问答历史列表
 * @param {Object} [params] - { page?, page_size?, keyword?, feedback? }
 * @returns {Promise<Object>} { success, total, page, page_size, total_pages, items[] }
 */
export const getHistoryList = async (params = {}) => {
  const response = await apiClient.get('/api/qa/history', {
    params: {
      page: params.page ?? 1,
      page_size: params.page_size ?? 20,
      ...(params.keyword ? { keyword: params.keyword } : {}),
      ...(params.feedback ? { feedback: params.feedback } : {}),
    },
  });
  return response.data;
};

/**
 * 查询单条问答历史详情
 * @param {number} historyId
 * @returns {Promise<Object>} QAHistoryDetailResponse
 */
export const getHistoryDetail = async (historyId) => {
  const response = await apiClient.get(`/api/qa/history/${historyId}`);
  return response.data;
};

// ============================================================
// 问答反馈
// ============================================================

/**
 * 提交问答反馈
 * @param {number} qaId
 * @param {'like'|'dislike'|'none'} feedback
 * @returns {Promise<Object>} { success, qa_id, feedback, message }
 */
export const submitFeedback = async (qaId, feedback) => {
  const response = await apiClient.post(`/api/qa/feedback/${qaId}`, { feedback });
  return response.data;
};

// ============================================================
// 多轮对话会话管理
// ============================================================

/**
 * 查询当前用户的会话列表
 * @returns {Promise<Object>} { success, total, items[] }
 *   items[]: { conversation_id, title, message_count, last_question, created_at, updated_at }
 */
export const getConversations = async () => {
  const response = await apiClient.get('/api/qa/conversations');
  return response.data;
};

/**
 * 查询会话详情（完整多轮对话）
 * @param {string} conversationId
 * @returns {Promise<Object>} { success, conversation_id, title, message_count, items[] }
 *   items[]: { id, question, answer, sources, feedback, created_at }
 */
export const getConversationDetail = async (conversationId) => {
  const response = await apiClient.get(`/api/qa/conversations/${conversationId}`);
  return response.data;
};

/**
 * 删除会话（连同其全部问答记录）
 * @param {string} conversationId
 * @returns {Promise<Object>} { success, conversation_id, deleted_count, message }
 */
export const deleteConversation = async (conversationId) => {
  const response = await apiClient.delete(`/api/qa/conversations/${conversationId}`);
  return response.data;
};

// ============================================================
// 反馈统计
// ============================================================

/**
 * 查询反馈统计
 * @param {Object} [params] - { scope?: 'me' | 'all' }；scope=all 仅 admin 有效，非 admin 会被后端强制降级为 me
 * @returns {Promise<Object>} { success, scope, total_qa, total_likes, total_dislikes, total_no_feedback, like_rate, top_disliked[] }
 *   top_disliked[]: { qa_id, question, answer, feedback, created_at, conversation_id, username }
 */
export const getFeedbackStats = async (params = {}) => {
  const response = await apiClient.get('/api/qa/feedback/stats', {
    params: {
      scope: params.scope || 'me',
    },
  });
  return response.data;
};

/**
 * 获取检索过滤器可选值（level / service）
 * 返回数据库中实际存在的 distinct 值，避免前端硬编码
 * @returns {Promise<{levels: string[], services: string[]}>}
 */
export const getFilterOptions = async () => {
  const response = await apiClient.get('/api/qa/filters');
  return response.data.data;
};

// ============================================================
// 统一导出（便于集中导入）
// ============================================================
export default {
  askQuestion,
  askStreamQuestion,
  getHistoryList,
  getHistoryDetail,
  submitFeedback,
  getConversations,
  getConversationDetail,
  deleteConversation,
  getFeedbackStats,
  getFilterOptions,
};
