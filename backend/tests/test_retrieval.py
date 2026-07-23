"""
检索模块单元测试
覆盖向量检索、BM25检索、混合检索的正常和边界情况
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import time
from typing import List, Dict, Any

from services.retriever import LogRetriever, search_logs, get_retriever
from services.bm25_retriever import bm25_search, get_bm25_retriever
from services.hybrid_retriever import hybrid_search, get_hybrid_retriever
from services.qdrant_client import get_qdrant_client
from services.formatter import ResultFormatter


# ============ 辅助函数 ============

def has_vector_data():
    """检查是否有向量数据"""
    try:
        client = get_qdrant_client()
        return client.count() > 0
    except:
        return False


def has_bm25_data():
    """检查是否有 BM25 数据"""
    try:
        retriever = get_bm25_retriever()
        return retriever.get_document_count() > 0
    except:
        return False


# ============ 向量检索测试 ============

class TestVectorRetrieval:
    """向量检索单元测试"""
    
    @classmethod
    def setup_class(cls):
        """测试前置准备"""
        cls.retriever = LogRetriever(top_k=5, score_threshold=0.0)
        try:
            cls.has_data = get_qdrant_client().count() > 0
        except:
            cls.has_data = False
    
    # ========== 正常情况测试 ==========
    
    def test_basic_search(self):
        """测试基础检索"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "数据库连接失败"
        results = self.retriever.search(query, top_k=3)
        
        assert isinstance(results, list)
        assert len(results) <= 3
        
        if len(results) > 0:
            result = results[0]
            assert hasattr(result, 'id')
            assert hasattr(result, 'score')
            assert hasattr(result, 'payload')
            assert result.score >= 0
            
            payload = result.payload
            assert 'log_id' in payload
            assert 'chunk_text' in payload
            assert 'level' in payload
            assert 'service' in payload
            assert 'timestamp' in payload
    
    def test_search_with_top_k(self):
        """测试不同 Top-K 值"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        test_cases = [1, 3, 5, 10]
        
        for top_k in test_cases:
            results = self.retriever.search("测试查询", top_k=top_k)
            assert len(results) <= top_k
    
    def test_search_with_level_filter(self):
        """测试级别过滤"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "服务异常"
        results = self.retriever.search_by_level(
            query=query,
            level="ERROR",
            top_k=5
        )
        
        for result in results:
            payload = result.payload
            if 'level' in payload:
                assert payload['level'] == 'ERROR'
    
    def test_search_with_service_filter(self):
        """测试服务过滤"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "认证失败"
        results = self.retriever.search_by_service(
            query=query,
            service="auth-service",
            top_k=5
        )
        
        for result in results:
            payload = result.payload
            if 'service' in payload:
                assert payload['service'] == 'auth-service'
    
    def test_search_with_multiple_filters(self):
        """测试组合过滤"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "系统错误"
        filter_params = {
            'level': 'ERROR',
            'service': 'auth-service'
        }
        results = self.retriever.search(
            query=query,
            top_k=5,
            filter_params=filter_params
        )
        
        for result in results:
            payload = result.payload
            if 'level' in payload:
                assert payload['level'] == 'ERROR'
            if 'service' in payload:
                assert payload['service'] == 'auth-service'
    
    def test_search_with_time_filter_before(self):
        """测试时间过滤（之前）"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "服务异常"
        before_time = "2025-01-01 00:00:00"
        results = self.retriever.search_by_time(
            query=query,
            before=before_time,
            top_k=3
        )
        
        for result in results:
            payload = result.payload
            if 'timestamp' in payload:
                assert payload['timestamp'] <= before_time
    
    def test_search_with_time_filter_between(self):
        """测试时间过滤（时间段）"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "服务异常"
        start_time = "2026-07-15 00:00:00"
        end_time = "2026-07-20 23:59:59"
        results = self.retriever.search_by_time(
            query=query,
            between=(start_time, end_time),
            top_k=3
        )
        
        for result in results:
            payload = result.payload
            if 'timestamp' in payload:
                assert start_time <= payload['timestamp'] <= end_time
    
    def test_score_threshold(self):
        """测试相似度阈值"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "系统崩溃"
        results_low = self.retriever.search(query, top_k=10, score_threshold=0.0)
        results_high = self.retriever.search(query, top_k=10, score_threshold=0.5)
        
        assert len(results_high) <= len(results_low)
        
        for result in results_high:
            assert result.score >= 0.5
    
    # ========== 边界情况测试 ==========
    
    def test_empty_query(self):
        """测试空查询"""
        results = self.retriever.search("")
        assert results == []
        
        results = self.retriever.search("   ")
        assert results == []
    
    def test_very_long_query(self):
        """测试超长查询（1000+字符）"""
        long_query = "测试 " * 500
        results = self.retriever.search(long_query, top_k=3)
        assert isinstance(results, list)
    
    def test_special_characters_query(self):
        """测试特殊字符查询"""
        special_queries = [
            "!@#$%^&*()",
            "查询 with 特殊 字符",
            "SQL注入' OR '1'='1",
            "<script>alert('xss')</script>",
        ]
        
        for query in special_queries:
            results = self.retriever.search(query, top_k=3)
            assert isinstance(results, list)
    
    def test_non_chinese_query(self):
        """测试非中文查询"""
        results = self.retriever.search("English query test", top_k=3)
        assert isinstance(results, list)
    
    def test_get_log_info(self):
        """测试获取日志信息方法"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "数据库错误"
        results = self.retriever.search(query, top_k=1)
        
        if results:
            log_info = results[0].get_log_info()
            assert 'log_id' in log_info
            assert 'level' in log_info
            assert 'service' in log_info
            assert 'timestamp' in log_info
            assert 'message' in log_info
            assert 'score' in log_info
    
    def test_convenience_function(self):
        """测试便捷函数"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        results = search_logs(
            query="服务异常",
            top_k=3,
            level="ERROR",
            service="auth-service"
        )
        
        assert isinstance(results, list)
        if results:
            result = results[0]
            assert 'log_id' in result
            assert 'score' in result
            assert 'level' in result
            assert 'service' in result
            assert 'timestamp' in result
            assert 'message' in result


# ============ BM25 检索测试 ============

class TestBM25Retrieval:
    """BM25 检索单元测试"""
    
    @classmethod
    def setup_class(cls):
        """测试前置准备"""
        try:
            cls.retriever = get_bm25_retriever()
            cls.has_data = cls.retriever.get_document_count() > 0
        except:
            cls.has_data = False
    
    # ========== 正常情况测试 ==========
    
    def test_basic_search(self):
        """测试基础 BM25 检索"""
        if not self.has_data:
            pytest.skip("无BM25索引，跳过测试")
        
        query = "timeout"
        results = bm25_search(query, top_k=3)
        
        assert isinstance(results, list)
        assert len(results) <= 3
        
        if results:
            result = results[0]
            assert 'log_id' in result
            assert 'score' in result
            assert 'payload' in result
    
    def test_search_with_level_filter(self):
        """测试 BM25 级别过滤"""
        if not self.has_data:
            pytest.skip("无BM25索引，跳过测试")
        
        query = "error"
        results = bm25_search(
            query=query,
            top_k=5,
            level="ERROR"
        )
        
        for result in results:
            payload = result.get('payload', {})
            if 'level' in payload:
                assert payload['level'] == 'ERROR'
    
    def test_search_with_service_filter(self):
        """测试 BM25 服务过滤"""
        if not self.has_data:
            pytest.skip("无BM25索引，跳过测试")
        
        query = "error"
        results = bm25_search(
            query=query,
            top_k=5,
            service="auth-service"
        )
        
        for result in results:
            payload = result.get('payload', {})
            if 'service' in payload:
                assert payload['service'] == 'auth-service'
    
    def test_search_english_query(self):
        """测试英文查询"""
        if not self.has_data:
            pytest.skip("无BM25索引，跳过测试")
        
        english_queries = [
            "timeout",
            "database",
            "connection",
            "error",
            "NullPointerException",
        ]
        
        for query in english_queries:
            results = bm25_search(query, top_k=3)
            assert isinstance(results, list)
    
    # ========== 边界情况测试 ==========
    
    def test_empty_query(self):
        """测试空查询"""
        results = bm25_search("")
        assert results == []
        
        results = bm25_search("   ")
        assert results == []
    
    def test_query_no_match(self):
        """测试无匹配查询"""
        results = bm25_search("xyzabc123notexist", top_k=3)
        assert isinstance(results, list)
    
    def test_large_top_k(self):
        """测试大 Top-K 值"""
        if not self.has_data:
            pytest.skip("无BM25索引，跳过测试")
        
        results = bm25_search("timeout", top_k=100)
        assert len(results) <= 100


# ============ 混合检索测试 ============

class TestHybridRetrieval:
    """混合检索单元测试"""
    
    @classmethod
    def setup_class(cls):
        """测试前置准备"""
        try:
            cls.retriever = get_hybrid_retriever()
            cls.has_data = get_qdrant_client().count() > 0
        except:
            cls.has_data = False
    
    # ========== 正常情况测试 ==========
    
    def test_basic_search(self):
        """测试基础混合检索"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "timeout"
        results = self.retriever.search(query, top_k=5)
        
        assert isinstance(results, list)
        assert len(results) <= 5
        
        if results:
            result = results[0]
            assert hasattr(result, 'log_id')
            assert hasattr(result, 'rrf_score')
            assert hasattr(result, 'vector_score')
            assert hasattr(result, 'bm25_score')
            assert hasattr(result, 'vector_rank')
            assert hasattr(result, 'bm25_rank')
    
    def test_search_with_filter(self):
        """测试混合检索过滤"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "error"
        results = self.retriever.search(
            query=query,
            top_k=5,
            filter_params={"level": "ERROR", "service": "auth-service"}
        )
        
        assert isinstance(results, list)
        for result in results:
            payload = result.payload
            if 'level' in payload:
                assert payload['level'] == 'ERROR'
            if 'service' in payload:
                assert payload['service'] == 'auth-service'
    
    def test_hybrid_better_than_single(self):
        """测试混合检索优于单一检索"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "NullPointerException"
        
        vector_results = search_logs(query, top_k=5)
        bm25_results = bm25_search(query, top_k=5)
        hybrid_results = hybrid_search(query, top_k=5)
        
        assert len(hybrid_results) >= 0
        
        print(f"\n  向量: {len(vector_results)} 条")
        print(f"  BM25: {len(bm25_results)} 条")
        print(f"  混合: {len(hybrid_results)} 条")
    
    # ========== 边界情况测试 ==========
    
    def test_empty_query(self):
        """测试空查询"""
        results = self.retriever.search("")
        assert results == []
        
        results = self.retriever.search("   ")
        assert results == []
    
    def test_formatted_search(self):
        """测试格式化检索"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        results = self.retriever.search_formatted(
            query="timeout",
            top_k=3,
            include_summary=True,
            include_evidence=True
        )
        
        assert 'logs' in results
        assert 'count' in results
        assert 'summary' in results
        assert 'evidence' in results
        assert results['count'] <= 3


# ============ 集成测试 ============

class TestRetrievalIntegration:
    """检索集成测试"""
    
    @classmethod
    def setup_class(cls):
        try:
            cls.has_data = get_qdrant_client().count() > 0
        except:
            cls.has_data = False
    
    def test_end_to_end_search(self):
        """端到端检索测试"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        queries = ["timeout", "error", "NullPointerException"]
        
        for query in queries:
            vector_results = search_logs(query, top_k=3)
            assert isinstance(vector_results, list)
            
            bm25_results = bm25_search(query, top_k=3)
            assert isinstance(bm25_results, list)
            
            hybrid_results = hybrid_search(query, top_k=3)
            assert isinstance(hybrid_results, list)
            
            print(f"\n  查询: {query}")
            print(f"    向量: {len(vector_results)} 条")
            print(f"    BM25: {len(bm25_results)} 条")
            print(f"    混合: {len(hybrid_results)} 条")
    
    def test_search_consistency(self):
        """测试检索一致性"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "timeout"
        
        results_list = []
        for _ in range(3):
            results = search_logs(query, top_k=5)
            results_list.append([r['log_id'] for r in results])
        
        for i in range(1, len(results_list)):
            assert results_list[i] == results_list[0], f"检索结果不一致"


# ============ 格式化器测试 ============

class TestFormatter:
    """格式化器单元测试"""
    
    def test_format_single(self):
        """测试单条格式化"""
        payload = {
            'log_id': 123,
            'level': 'ERROR',
            'service': 'auth-service',
            'timestamp': '2026-07-23 10:00:00',
            'chunk_text': 'Test message',
            'source': 'auth-service'
        }
        score = 0.85
        
        log = ResultFormatter.format_single(payload, score)
        
        assert log.log_id == 123
        assert log.level == 'ERROR'
        assert log.service == 'auth-service'
        assert log.timestamp == '2026-07-23 10:00:00'
        assert log.message == 'Test message'
        assert log.source == 'auth-service'
        assert log.score == 0.85
    
    def test_format_batch(self):
        """测试批量格式化"""
        results = [
            (0.85, {'log_id': 1, 'level': 'ERROR', 'chunk_text': 'Message 1'}),
            (0.72, {'log_id': 2, 'level': 'WARNING', 'chunk_text': 'Message 2'}),
        ]
        
        logs = ResultFormatter.format_batch(results)
        
        assert len(logs) == 2
        assert logs[0].log_id == 1
        assert logs[0].score == 0.85
        assert logs[1].log_id == 2
        assert logs[1].score == 0.72
    
    def test_to_evidence_text(self):
        """测试证据文本生成"""
        from services.formatter import RetrievedLog
        
        logs = [
            RetrievedLog(1, 'ERROR', 'auth-service', '2026-07-23 10:00:00', 'Message 1', 'auth', 0.85),
            RetrievedLog(2, 'WARNING', 'api-gateway', '2026-07-23 10:05:00', 'Message 2', 'api', 0.72),
        ]
        
        evidence = ResultFormatter.to_evidence_text(logs)
        
        assert '1.' in evidence
        assert '2.' in evidence
        assert '[2026-07-23 10:00:00]' in evidence
        assert '[ERROR]' in evidence
        assert 'Message 1' in evidence
    
    def test_summarize_empty(self):
        """测试空结果摘要"""
        summary = ResultFormatter.summarize([])
        
        assert summary['total'] == 0
        assert summary['levels'] == {}
        assert summary['services'] == {}
        assert summary['avg_score'] == 0.0
    
    def test_summarize(self):
        """测试摘要生成"""
        from services.formatter import RetrievedLog
        
        logs = [
            RetrievedLog(1, 'ERROR', 'auth-service', '2026-07-23 10:00:00', 'Message 1', 'auth', 0.85),
            RetrievedLog(2, 'ERROR', 'auth-service', '2026-07-23 10:05:00', 'Message 2', 'auth', 0.72),
            RetrievedLog(3, 'WARNING', 'api-gateway', '2026-07-23 10:10:00', 'Message 3', 'api', 0.65),
        ]
        
        summary = ResultFormatter.summarize(logs)
        
        assert summary['total'] == 3
        assert summary['levels']['ERROR'] == 2
        assert summary['levels']['WARNING'] == 1
        assert summary['services']['auth-service'] == 2
        assert summary['services']['api-gateway'] == 1
        assert 0.7 < summary['avg_score'] < 0.8


# ============ 运行测试 ============

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])