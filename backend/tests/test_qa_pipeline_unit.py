"""
QA Pipeline 单元测试
覆盖正常路径和异常路径
运行: pytest tests/test_qa_pipeline_unit.py -v
"""

import sys
import os
import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from typing import List, Dict, Any

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.qa_pipeline import (
    QAPipeline, 
    QAResult, 
    StreamChunk, 
    create_pipeline,
    SourceReference
)
from services.exceptions import (
    NoSearchResultsError,
    LLMTimeoutError,
    InvalidQueryError,
    ConversationNotFoundError
)
from services.error_handler import RobustQAPipeline, create_robust_pipeline


# ============================================================
# 测试数据
# ============================================================

SAMPLE_LOGS = [
    {
        "log_id": 6789,
        "service": "user-service",
        "timestamp": "2026-07-15 15:08:42",
        "level": "ERROR",
        "content": "File not found: /var/log/app.log",
        "score": 0.85
    },
    {
        "log_id": 4553,
        "service": "user-service",
        "timestamp": "2026-07-19 15:01:08",
        "level": "DEBUG",
        "content": "User login successful",
        "score": 0.75
    },
    {
        "log_id": 6792,
        "service": "auth-service",
        "timestamp": "2026-07-18 01:20:38",
        "level": "ERROR",
        "content": "NullPointerException in UserService",
        "score": 0.90
    }
]


# ============================================================
# QAPipeline 测试
# ============================================================

class TestQAPipeline:
    """QAPipeline 基础功能测试"""
    
    def test_init_default(self):
        """测试默认初始化"""
        pipeline = QAPipeline()
        assert pipeline.top_k == 5
        assert pipeline.retriever_type == "hybrid"
        assert pipeline.template_type == "evidence_chain"
        assert pipeline.conversation_history == []
    
    def test_init_custom(self):
        """测试自定义初始化"""
        pipeline = QAPipeline(
            top_k=10,
            template_type="quick",
            retriever_type="bm25"
        )
        assert pipeline.top_k == 10
        assert pipeline.retriever_type == "bm25"
        assert pipeline.template_type == "quick"
    
    def test_create_pipeline(self):
        """测试工厂函数"""
        pipeline = create_pipeline(top_k=3, retriever_type="vector")
        assert pipeline.top_k == 3
        assert pipeline.retriever_type == "vector"
    
    def test_clear_history(self):
        """测试清空对话历史"""
        pipeline = QAPipeline()
        pipeline.conversation_history = [{"role": "user", "content": "test"}]
        pipeline.clear_history()
        assert pipeline.conversation_history == []
    
    def test_get_history(self):
        """测试获取对话历史"""
        pipeline = QAPipeline()
        pipeline.conversation_history = [
            {"role": "user", "content": "test1"},
            {"role": "assistant", "content": "answer1"}
        ]
        history = pipeline.get_history()
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"


class TestQAResult:
    """QAResult 数据类测试"""
    
    def test_qaresult_creation(self):
        """测试 QAResult 创建"""
        result = QAResult(
            question="测试问题",
            answer="测试回答",
            sources=[],
            confidence="高",
            total_tokens=100,
            retriever_type="hybrid"
        )
        assert result.question == "测试问题"
        assert result.answer == "测试回答"
        assert result.confidence == "高"
        assert result.total_tokens == 100
    
    def test_qaresult_with_sources(self):
        """测试带来源的 QAResult"""
        sources = [{"log_id": 123, "content": "test log"}]
        result = QAResult(
            question="test",
            answer="answer",
            sources=sources,
            confidence="中"
        )
        assert len(result.sources) == 1
        assert result.sources[0]["log_id"] == 123
    
    def test_qaresult_source_refs(self):
        """测试来源引用"""
        source_refs = [
            SourceReference(
                ref_id="[1]",
                log_id=6789,
                service="user-service",
                timestamp="2026-07-15 15:08:42",
                level="ERROR",
                content="test content"
            )
        ]
        result = QAResult(
            question="test",
            answer="answer",
            source_refs=source_refs
        )
        assert len(result.source_refs) == 1
        assert result.source_refs[0].ref_id == "[1]"
        
        # 测试 get_source_by_ref
        found = result.get_source_by_ref("[1]")
        assert found is not None
        assert found.log_id == 6789
        
        # 测试 get_source_by_log_id
        found = result.get_source_by_log_id(6789)
        assert len(found) == 1


class TestStreamChunk:
    """StreamChunk 数据类测试"""
    
    def test_stream_chunk_source(self):
        """测试流式来源块"""
        chunk = StreamChunk(
            type="source",
            content="找到 3 条日志",
            data={"sources": []}
        )
        assert chunk.type == "source"
        assert chunk.data is not None
    
    def test_stream_chunk_answer(self):
        """测试流式回答块"""
        chunk = StreamChunk(
            type="answer",
            content="这是回答内容"
        )
        assert chunk.type == "answer"
        assert chunk.content == "这是回答内容"


# ============================================================
# 异常处理测试
# ============================================================

class TestExceptions:
    """异常类测试"""
    
    def test_no_search_results_error(self):
        """测试检索无结果异常"""
        error = NoSearchResultsError("test query")
        assert "未找到" in error.message
        assert error.error_code == "NO_SEARCH_RESULTS"
    
    def test_no_search_results_with_filters(self):
        """测试带过滤条件的检索无结果异常"""
        error = NoSearchResultsError("test query", filters={"level": "ERROR"})
        assert "ERROR" in error.message
    
    def test_llm_timeout_error(self):
        """测试LLM超时异常"""
        error = LLMTimeoutError(30)
        assert "30s" in error.message
        assert error.error_code == "LLM_TIMEOUT"
    
    def test_invalid_query_error(self):
        """测试无效查询异常"""
        error = InvalidQueryError("")
        assert "无效" in error.message
        assert error.error_code == "INVALID_QUERY"


# ============================================================
# RobustQAPipeline 测试
# ============================================================

class TestRobustQAPipeline:
    """健壮 Pipeline 测试"""
    
    def test_robust_pipeline_creation(self):
        """测试创建健壮 Pipeline"""
        pipeline = create_robust_pipeline(top_k=3)
        assert pipeline is not None
        assert hasattr(pipeline, 'ask')
    
    def test_robust_pipeline_empty_query(self):
        """测试空查询"""
        pipeline = create_robust_pipeline()
        result = pipeline.ask("")
        assert result.confidence == "低"
        assert "无效" in result.answer
        assert len(result.sources) == 0
    
    def test_robust_pipeline_whitespace_query(self):
        """测试空白查询"""
        pipeline = create_robust_pipeline()
        result = pipeline.ask("   ")
        assert result.confidence == "低"
        assert "无效" in result.answer
    
    def test_robust_pipeline_error_stats(self):
        """测试错误统计"""
        pipeline = create_robust_pipeline()
        # 触发一个错误
        pipeline.ask("")
        stats = pipeline.get_error_stats()
        assert stats["total_errors"] >= 1


# ============================================================
# 集成测试（需要实际运行）
# ============================================================

class TestIntegration:
    """集成测试 - 实际调用检索和LLM"""
    
    @pytest.mark.integration
    def test_real_ask(self):
        """测试实际问答"""
        pipeline = create_pipeline(top_k=3)
        result = pipeline.ask("auth-service 有什么异常？")
        assert result.answer is not None
        assert len(result.answer) > 0
        assert result.confidence in ["高", "中", "低"]
    
    @pytest.mark.integration
    def test_real_ask_with_filters(self):
        """测试带过滤条件的实际问答"""
        pipeline = create_pipeline(top_k=3)
        result = pipeline.ask(
            "有什么错误？",
            filters={"level": "ERROR"}
        )
        assert result.answer is not None
        assert len(result.answer) > 0
    
    @pytest.mark.integration
    def test_real_ask_stream(self):
        """测试实际流式问答"""
        pipeline = create_pipeline(top_k=3)
        chunks = []
        for chunk in pipeline.ask_stream("auth-service 有什么异常？"):
            chunks.append(chunk)
            if chunk.type == "source":
                assert chunk.data is not None
        assert len(chunks) > 0
    
    @pytest.mark.integration
    def test_real_multi_turn(self):
        """测试实际多轮对话"""
        pipeline = create_pipeline(top_k=3)
        
        # 第一轮
        result1 = pipeline.ask("auth-service 有什么异常？")
        assert result1.answer is not None
        
        # 第二轮（上下文）
        result2 = pipeline.ask("这个错误是什么原因？")
        assert result2.answer is not None
        
        # 验证历史
        history = pipeline.get_history()
        assert len(history) >= 4
    
    @pytest.mark.integration
    def test_real_source_tracking(self):
        """测试实际来源溯源"""
        pipeline = create_pipeline(top_k=3)
        result = pipeline.ask("auth-service 报错是什么原因？")
        
        # 检查是否有来源引用
        if result.source_refs:
            for ref in result.source_refs:
                assert ref.log_id is not None
                assert ref.service is not None
        else:
            # 如果没有来源，置信度应该是"低"
            assert result.confidence in ["低", "中"]


# ============================================================
# 性能测试
# ============================================================

class TestPerformance:
    """性能测试"""
    
    @pytest.mark.performance
    def test_response_time(self):
        """测试响应时间"""
        pipeline = create_pipeline(top_k=3)
        start = time.time()
        pipeline.ask("auth-service 有什么异常？")
        elapsed = time.time() - start
        assert elapsed < 30  # 应该在30秒内完成
    
    @pytest.mark.performance
    def test_memory_usage(self):
        """测试内存使用（简单检查）"""
        import sys
        pipeline = create_pipeline(top_k=3)
        # 执行多个查询
        for i in range(3):
            pipeline.ask(f"测试问题 {i}")
        history = pipeline.get_history()
        assert len(history) <= 20  # 历史不会无限增长


# ============================================================
# 测试夹具
# ============================================================

@pytest.fixture
def sample_pipeline():
    """提供测试用的 Pipeline"""
    return create_pipeline(top_k=3)


@pytest.fixture
def sample_robust_pipeline():
    """提供测试用的健壮 Pipeline"""
    return create_robust_pipeline(top_k=3)


# ============================================================
# 运行测试
# ============================================================

if __name__ == "__main__":
    # 运行所有测试
    pytest.main([__file__, "-v", "--tb=short"])


"""
# 运行所有测试
cd D:\log-qa-system\backend
pytest tests/test_qa_pipeline_unit.py -v

# 只运行基础测试（不调用LLM）
pytest tests/test_qa_pipeline_unit.py -v -m "not integration"

# 运行集成测试（调用LLM）
pytest tests/test_qa_pipeline_unit.py -v -m integration

# 运行性能测试
pytest tests/test_qa_pipeline_unit.py -v -m performance

# 生成覆盖率报告
pytest tests/test_qa_pipeline_unit.py --cov=services --cov-report=html
"""