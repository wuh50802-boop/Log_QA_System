#!/usr/bin/env python
"""
检索性能测试
测试不同数据量下的向量检索、BM25检索、混合检索的耗时
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import json
import statistics
from datetime import datetime
from typing import List, Dict, Any

from services.retriever import search_logs, get_retriever
from services.bm25_retriever import bm25_search, get_bm25_retriever
from services.hybrid_retriever import hybrid_search, get_hybrid_retriever
from services.qdrant_client import get_qdrant_client


class PerformanceTest:
    """性能测试类"""
    
    def __init__(self):
        self.client = get_qdrant_client()
        self.results = []
        
        # 测试查询
        self.test_queries = [
            "数据库连接失败",
            "服务超时",
            "内存溢出",
            "NullPointerException",
            "Connection timeout",
        ]
        
        # 预热
        self._warmup()
    
    def _warmup(self):
        """预热，避免首次加载开销"""
        print("🔥 预热中...")
        
        # 预加载 jieba
        try:
            import jieba
            jieba.lcut("预热测试")
        except:
            pass
        
        # 执行一次空检索
        try:
            search_logs("预热", top_k=1)
            bm25_search("预热", top_k=1)
            hybrid_search("预热", top_k=1)
        except:
            pass
        
        print("✅ 预热完成\n")
    
    def get_vector_count(self) -> int:
        """获取向量总数"""
        try:
            return self.client.count()
        except:
            return 0
    
    def test_vector_retrieval(
        self,
        query: str,
        top_k: int = 10,
        iterations: int = 10,
    ) -> Dict[str, Any]:
        """测试向量检索性能"""
        times = []
        results_count = []
        
        for _ in range(iterations):
            start = time.perf_counter()
            results = search_logs(query, top_k=top_k)
            elapsed = time.perf_counter() - start
            times.append(elapsed * 1000)
            results_count.append(len(results))
        
        # 计算中位数（更准确）
        sorted_times = sorted(times)
        median = sorted_times[len(sorted_times)//2] if sorted_times else 0
        
        return {
            "type": "vector",
            "query": query,
            "top_k": top_k,
            "iterations": iterations,
            "times_ms": times,
            "avg_ms": statistics.mean(times),
            "median_ms": median,
            "min_ms": min(times),
            "max_ms": max(times),
            "std_ms": statistics.stdev(times) if len(times) > 1 else 0,
            "avg_results": statistics.mean(results_count),
        }
    
    def test_bm25_retrieval(
        self,
        query: str,
        top_k: int = 10,
        iterations: int = 10,
    ) -> Dict[str, Any]:
        """测试 BM25 检索性能"""
        times = []
        results_count = []
        
        for _ in range(iterations):
            start = time.perf_counter()
            results = bm25_search(query, top_k=top_k)
            elapsed = time.perf_counter() - start
            times.append(elapsed * 1000)
            results_count.append(len(results))
        
        sorted_times = sorted(times)
        median = sorted_times[len(sorted_times)//2] if sorted_times else 0
        
        return {
            "type": "bm25",
            "query": query,
            "top_k": top_k,
            "iterations": iterations,
            "times_ms": times,
            "avg_ms": statistics.mean(times),
            "median_ms": median,
            "min_ms": min(times),
            "max_ms": max(times),
            "std_ms": statistics.stdev(times) if len(times) > 1 else 0,
            "avg_results": statistics.mean(results_count),
        }
    
    def test_hybrid_retrieval(
        self,
        query: str,
        top_k: int = 10,
        iterations: int = 10,
    ) -> Dict[str, Any]:
        """测试混合检索性能"""
        times = []
        results_count = []
        
        for _ in range(iterations):
            start = time.perf_counter()
            results = hybrid_search(query, top_k=top_k)
            elapsed = time.perf_counter() - start
            times.append(elapsed * 1000)
            results_count.append(len(results))
        
        sorted_times = sorted(times)
        median = sorted_times[len(sorted_times)//2] if sorted_times else 0
        
        return {
            "type": "hybrid",
            "query": query,
            "top_k": top_k,
            "iterations": iterations,
            "times_ms": times,
            "avg_ms": statistics.mean(times),
            "median_ms": median,
            "min_ms": min(times),
            "max_ms": max(times),
            "std_ms": statistics.stdev(times) if len(times) > 1 else 0,
            "avg_results": statistics.mean(results_count),
        }
    
    def run_full_test(self, top_k: int = 10, iterations: int = 10) -> List[Dict[str, Any]]:
        """运行完整性能测试"""
        print(f"\n{'='*70}")
        print(f"🚀 开始性能测试")
        print(f"{'='*70}")
        print(f"📊 向量总数: {self.get_vector_count()}")
        print(f"📝 测试查询数: {len(self.test_queries)}")
        print(f"🔄 每个查询迭代: {iterations} 次")
        print(f"📌 Top-K: {top_k}")
        print(f"{'='*70}\n")
        
        all_results = []
        
        for i, query in enumerate(self.test_queries, 1):
            print(f"\n📌 查询 {i}/{len(self.test_queries)}: '{query}'")
            print(f"{'-'*50}")
            
            # 1. 向量检索
            print("   🔍 测试向量检索...")
            vector_result = self.test_vector_retrieval(query, top_k, iterations)
            print(f"      平均耗时: {vector_result['avg_ms']:.2f}ms (中位数: {vector_result['median_ms']:.2f}ms)")
            print(f"      最快: {vector_result['min_ms']:.2f}ms, 最慢: {vector_result['max_ms']:.2f}ms")
            print(f"      平均结果数: {vector_result['avg_results']:.0f}")
            all_results.append(vector_result)
            
            # 2. BM25 检索
            print("   🔍 测试 BM25 检索...")
            bm25_result = self.test_bm25_retrieval(query, top_k, iterations)
            print(f"      平均耗时: {bm25_result['avg_ms']:.2f}ms (中位数: {bm25_result['median_ms']:.2f}ms)")
            print(f"      最快: {bm25_result['min_ms']:.2f}ms, 最慢: {bm25_result['max_ms']:.2f}ms")
            print(f"      平均结果数: {bm25_result['avg_results']:.0f}")
            all_results.append(bm25_result)
            
            # 3. 混合检索
            print("   🔍 测试混合检索...")
            hybrid_result = self.test_hybrid_retrieval(query, top_k, iterations)
            print(f"      平均耗时: {hybrid_result['avg_ms']:.2f}ms (中位数: {hybrid_result['median_ms']:.2f}ms)")
            print(f"      最快: {hybrid_result['min_ms']:.2f}ms, 最慢: {hybrid_result['max_ms']:.2f}ms")
            print(f"      平均结果数: {hybrid_result['avg_results']:.0f}")
            all_results.append(hybrid_result)
        
        self.results = all_results
        return all_results
    
    def test_different_top_k(self, top_k_values: List[int] = [5, 10, 20, 50]) -> Dict[str, Any]:
        """测试不同 Top-K 值下的性能"""
        print(f"\n{'='*70}")
        print(f"📊 不同 Top-K 值性能对比")
        print(f"{'='*70}")
        
        query = "数据库连接失败"
        results = {}
        
        for top_k in top_k_values:
            print(f"\n📌 Top-K: {top_k}")
            
            vector_result = self.test_vector_retrieval(query, top_k, iterations=5)
            print(f"   向量检索: {vector_result['median_ms']:.2f}ms (平均: {vector_result['avg_ms']:.2f}ms)")
            
            bm25_result = self.test_bm25_retrieval(query, top_k, iterations=5)
            print(f"   BM25 检索: {bm25_result['median_ms']:.2f}ms (平均: {bm25_result['avg_ms']:.2f}ms)")
            
            hybrid_result = self.test_hybrid_retrieval(query, top_k, iterations=5)
            print(f"   混合检索: {hybrid_result['median_ms']:.2f}ms (平均: {hybrid_result['avg_ms']:.2f}ms)")
            
            results[f"top_{top_k}"] = {
                "vector": vector_result,
                "bm25": bm25_result,
                "hybrid": hybrid_result,
            }
        
        return results
    
    def generate_report(self) -> str:
        """生成性能测试报告"""
        if not self.results:
            return "没有测试数据"
        
        lines = []
        lines.append("=" * 70)
        lines.append("📊 性能测试报告")
        lines.append("=" * 70)
        lines.append(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"向量总数: {self.get_vector_count()}")
        lines.append("")
        
        # 按类型分组
        vector_results = [r for r in self.results if r['type'] == 'vector']
        bm25_results = [r for r in self.results if r['type'] == 'bm25']
        hybrid_results = [r for r in self.results if r['type'] == 'hybrid']
        
        def calc_avg(data, key='median_ms'):
            if not data:
                return 0
            return statistics.mean([r[key] for r in data])
        
        lines.append("📈 各检索方式性能（中位数）:")
        lines.append(f"   向量检索: {calc_avg(vector_results):.2f}ms")
        lines.append(f"   BM25 检索: {calc_avg(bm25_results):.2f}ms")
        lines.append(f"   混合检索: {calc_avg(hybrid_results):.2f}ms")
        lines.append("")
        
        lines.append("📈 各检索方式性能详情:")
        for ret_type, results in [("向量检索", vector_results), ("BM25检索", bm25_results), ("混合检索", hybrid_results)]:
            if results:
                median_avg = statistics.mean([r['median_ms'] for r in results])
                avg_avg = statistics.mean([r['avg_ms'] for r in results])
                min_val = min([r['min_ms'] for r in results])
                max_val = max([r['max_ms'] for r in results])
                lines.append(f"   {ret_type}:")
                lines.append(f"      中位数平均: {median_avg:.2f}ms, 平均: {avg_avg:.2f}ms")
                lines.append(f"      最快: {min_val:.2f}ms, 最慢: {max_val:.2f}ms")
        
        lines.append("")
        lines.append("=" * 70)
        lines.append("✅ 性能测试完成")
        lines.append("=" * 70)
        
        return "\n".join(lines)
    
    def save_results(self, filename: str = "performance_results.json"):
        """保存测试结果到 JSON 文件"""
        data = {
            "timestamp": datetime.now().isoformat(),
            "vector_count": self.get_vector_count(),
            "results": self.results,
        }
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"\n📁 结果已保存到: {filename}")


def main():
    """主测试函数"""
    print("=" * 70)
    print("🧪 日志检索性能测试")
    print("=" * 70)
    
    tester = PerformanceTest()
    
    # 1. 基础性能测试
    results = tester.run_full_test(top_k=10, iterations=5)
    
    # 2. 不同 Top-K 值测试
    tester.test_different_top_k(top_k_values=[5, 10, 20])
    
    # 3. 生成报告
    report = tester.generate_report()
    print("\n" + report)
    
    # 4. 保存结果
    tester.save_results("performance_results.json")
    
    # 5. 验收判断
    print("\n" + "=" * 70)
    print("📋 验收结果")
    print("=" * 70)
    
    vector_median = statistics.mean([r['median_ms'] for r in results if r['type'] == 'vector'])
    bm25_median = statistics.mean([r['median_ms'] for r in results if r['type'] == 'bm25'])
    hybrid_median = statistics.mean([r['median_ms'] for r in results if r['type'] == 'hybrid'])
    
    print(f"   当前数据量: {tester.get_vector_count()} 条")
    print(f"   向量检索中位数: {vector_median:.2f}ms")
    print(f"   BM25 检索中位数: {bm25_median:.2f}ms")
    print(f"   混合检索中位数: {hybrid_median:.2f}ms")
    
    # 使用中位数进行评估（更准确）
    if tester.get_vector_count() >= 10000:
        print(f"\n   ✅ 数据量 >= 1万条，性能测试有效")
        
        # 目标: 10万条 < 300ms，1万条预估 < 30ms 为优秀
        if vector_median < 300:
            print("   ✅ 向量检索性能达标 (< 300ms)")
        else:
            print(f"   ⚠️ 向量检索性能待优化 ({vector_median:.2f}ms > 300ms)")
        
        if bm25_median < 100:
            print("   ✅ BM25 检索性能达标 (< 100ms)")
        else:
            print(f"   ⚠️ BM25 检索性能待优化 ({bm25_median:.2f}ms > 100ms)")
        
        if hybrid_median < 500:
            print("   ✅ 混合检索性能达标 (< 500ms)")
        else:
            print(f"   ⚠️ 混合检索性能待优化 ({hybrid_median:.2f}ms > 500ms)")
    else:
        print(f"\n   ⚠️ 当前数据量 {tester.get_vector_count()} 条，建议达到 10000+ 条进行完整测试")
    
    print("=" * 70)


if __name__ == "__main__":
    main()