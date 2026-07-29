import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { getFeedbackStats } from '../api/qa';
import './FeedbackStats.css';

const FeedbackStats = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const isAdmin = user?.role === 'admin';

  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [scope, setScope] = useState('me');

  const loadStats = async (s) => {
    setLoading(true);
    try {
      const result = await getFeedbackStats({ scope: s });
      setData(result);
    } catch (err) {
      console.error('加载反馈统计失败:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStats(scope);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSwitchScope = (newScope) => {
    if (newScope === scope) return;
    setScope(newScope);
    loadStats(newScope);
  };

  const handleJumpToConversation = (convId) => {
    if (!convId) return;
    navigate(`/dashboard?conv=${encodeURIComponent(convId)}`);
  };

  const likeRate = data?.like_rate ?? 0;
  const likeRatePct = (likeRate * 100).toFixed(1);
  const totalRated = (data?.total_likes ?? 0) + (data?.total_dislikes ?? 0);

  return (
    <div className="fb-container">
      {/* 顶部导航 */}
      <header className="fb-header">
        <div className="fb-title-row">
          <h1>反馈统计</h1>
          <div className="fb-nav">
            <Link to="/dashboard" className="back-link">
              返回工作台
            </Link>
          </div>
        </div>
      </header>

      <main className="fb-main">
        {/* 统计卡片 */}
        <div className="fb-stats">
          <div className="fb-stat-card">
            <div className="stat-value">{data?.total_qa ?? 0}</div>
            <div className="stat-label">总问答数</div>
          </div>
          <div className="fb-stat-card stat-like">
            <div className="stat-value">{data?.total_likes ?? 0}</div>
            <div className="stat-label">点赞数</div>
          </div>
          <div className="fb-stat-card stat-dislike">
            <div className="stat-value">{data?.total_dislikes ?? 0}</div>
            <div className="stat-label">点踩数</div>
          </div>
          <div className="fb-stat-card stat-rate">
            <div className="stat-value">{likeRatePct}%</div>
            <div className="stat-label">好评率 ({totalRated} 评价)</div>
          </div>
        </div>

        {/* 差评列表卡片 */}
        <div className="fb-card">
          <div className="fb-card-header">
            <h2>差评问题 Top 10</h2>
            <div className="fb-card-actions">
              {isAdmin && (
                <div className="fb-scope-toggle">
                  <button
                    className={`fb-scope-btn ${scope === 'me' ? 'active' : ''}`}
                    onClick={() => handleSwitchScope('me')}
                    disabled={loading}
                  >
                    我的
                  </button>
                  <button
                    className={`fb-scope-btn ${scope === 'all' ? 'active' : ''}`}
                    onClick={() => handleSwitchScope('all')}
                    disabled={loading}
                  >
                    全平台
                  </button>
                </div>
              )}
              <button
                className="refresh-btn"
                onClick={() => loadStats(scope)}
                disabled={loading}
              >
                {loading ? '加载中' : '刷新'}
              </button>
            </div>
          </div>

          {loading && !data ? (
            <div className="fb-loading">加载反馈数据中...</div>
          ) : !data || !data.top_disliked || data.top_disliked.length === 0 ? (
            <div className="fb-empty">暂无差评记录</div>
          ) : (
            <table className="fb-table">
              <thead>
                <tr>
                  <th>问题</th>
                  <th>回答摘要</th>
                  {data.scope === 'all' && <th>用户</th>}
                  <th>时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {data.top_disliked.map((item) => (
                  <tr key={item.qa_id}>
                    <td className="cell-question">{item.question}</td>
                    <td className="cell-answer">{item.answer}</td>
                    {data.scope === 'all' && (
                      <td className="cell-user">{item.username || '-'}</td>
                    )}
                    <td className="cell-time">{item.created_at}</td>
                    <td className="cell-action">
                      {item.conversation_id ? (
                        <button
                          className="jump-btn"
                          onClick={() => handleJumpToConversation(item.conversation_id)}
                        >
                          查看会话
                        </button>
                      ) : (
                        <span className="action-disabled">无关联会话</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="fb-tip">
            点击「查看会话」可跳转到工作台查看该问答的完整上下文。
            差评数据来源于用户的点踩反馈。
          </div>
        </div>
      </main>
    </div>
  );
};

export default FeedbackStats;
