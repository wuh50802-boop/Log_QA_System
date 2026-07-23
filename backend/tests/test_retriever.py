"""
向量检索单元测试
"""
import pytest
import time
from services.retriever import LogRetriever, search_logs
from services.qdrant_client import get_qdrant_client


class TestRetriever:
    """检索器测试类"""
    
    @classmethod
    def setup_class(cls):
        """测试前置准备"""
        cls.retriever = LogRetriever(top_k=5, score_threshold=0.3)
        
        # 检查是否有数据
        client = get_qdrant_client()
        cls.has_data = client.count() > 0
        
        # 测试查询
        cls.test_queries = [
            "数据库连接失败",
            "API请求超时",
            "内存使用率过高",
            "无效的查询语句"
        ]
    
    def test_basic_search(self):
        """测试基础检索"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "数据库连接失败"
        results = self.retriever.search(query, top_k=3)
        
        assert isinstance(results, list)
        assert len(results) <= 3
        if len(results) > 0:
            assert hasattr(results[0], 'id')
            assert hasattr(results[0], 'score')
            assert hasattr(results[0], 'payload')
            assert results[0].score >= 0
            # 验证payload结构
            assert 'log_id' in results[0].payload
            assert 'chunk_text' in results[0].payload
            assert 'level' in results[0].payload
            assert 'service' in results[0].payload
            assert 'timestamp' in results[0].payload
    
    def test_search_with_level_filter(self):
        """测试按级别过滤"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "服务异常"
        results = self.retriever.search_by_level(
            query=query,
            level="ERROR",
            top_k=5
        )
        
        # 验证过滤条件生效
        for result in results:
            payload = result.payload
            if 'level' in payload:
                assert payload['level'] == 'ERROR'
    
    def test_search_with_service_filter(self):
        """测试按服务过滤"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "认证失败"
        results = self.retriever.search_by_service(
            query=query,
            service="auth-service",
            top_k=5
        )
        
        # 验证过滤条件生效
        for result in results:
            payload = result.payload
            if 'service' in payload:
                assert payload['service'] == 'auth-service'
    
    def test_search_with_multiple_filters(self):
        """测试多个过滤条件组合"""
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
        
        # 验证所有条件
        for result in results:
            payload = result.payload
            if 'level' in payload:
                assert payload['level'] == 'ERROR'
            if 'service' in payload:
                assert payload['service'] == 'auth-service'
    
    def test_score_threshold(self):
        """测试相似度阈值"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "系统崩溃"
        results_low = self.retriever.search(query, top_k=10, score_threshold=0.0)
        results_high = self.retriever.search(query, top_k=10, score_threshold=0.5)
        
        # 高阈值应该返回更少结果
        assert len(results_high) <= len(results_low)
        
        # 所有结果的分数应该>=阈值
        for result in results_high:
            assert result.score >= 0.5
    
    def test_empty_query(self):
        """测试空查询"""
        results = self.retriever.search("")
        assert results == []
        
        results = self.retriever.search("   ")
        assert results == []
    
    def test_search_by_time(self):
        """测试时间过滤"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "服务异常"
        from datetime import datetime
        
        # 使用一个很早的时间
        before_time = "2025-01-01 00:00:00"
        results = self.retriever.search_by_time(
            query=query,
            before=before_time,
            top_k=3
        )
        
        # 验证时间过滤（如果结果存在）
        for result in results:
            payload = result.payload
            if 'timestamp' in payload:
                assert payload['timestamp'] <= before_time
    
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
        for result in results:
            assert 'log_id' in result
            assert 'score' in result
            assert 'level' in result
            assert 'service' in result
            assert 'timestamp' in result
            assert 'message' in result
    
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
    
    def test_performance(self):
        """测试检索性能"""
        if not self.has_data:
            pytest.skip("无向量数据，跳过测试")
        
        query = "数据库连接失败"
        
        # 执行10次检索
        times = []
        for _ in range(10):
            start = time.time()
            self.retriever.search(query, top_k=5)
            elapsed = time.time() - start
            times.append(elapsed)
        
        avg_time = sum(times) / len(times)
        
        print(f"\n平均检索耗时: {avg_time*1000:.2f}ms")
        # 期望平均耗时 < 300ms (按规划要求)
        assert avg_time < 0.3, f"检索耗时 {avg_time*1000:.2f}ms 超过300ms"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])