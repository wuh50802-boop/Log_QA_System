#!/usr/bin/env python
"""
检索结果可视化工具
直观展示向量检索、BM25检索、混合检索的排名对比
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from typing import List, Dict, Any, Optional
from datetime import datetime

from services.retriever import search_logs
from services.bm25_retriever import bm25_search
from services.hybrid_retriever import hybrid_search, compare_retrievers


class RetrievalVisualizer:
    """检索结果可视化工具"""
    
    COLORS = {
        "vector": "\033[94m",   # 蓝色
        "bm25": "\033[92m",     # 绿色
        "hybrid": "\033[93m",   # 黄色
        "reset": "\033[0m",     # 重置
        "bold": "\033[1m",      # 粗体
        "dim": "\033[2m",       # 灰色
    }
    
    def __init__(self):
        self.results = []
    
    def print_header(self, title: str, char: str = "=", length: int = 80):
        """打印标题头"""
        print(f"\n{char * length}")
        print(f"{self.COLORS['bold']}{title.center(length)}{self.COLORS['reset']}")
        print(f"{char * length}\n")
    
    def print_subheader(self, title: str):
        """打印子标题"""
        print(f"\n{self.COLORS['bold']}▶ {title}{self.COLORS['reset']}")
        print("-" * 60)
    
    def format_score(self, score: float, color: bool = True) -> str:
        """格式化分数（带颜色）"""
        if score == 0:
            return f"{self.COLORS['dim']}0.0000{self.COLORS['reset']}"
        
        if score >= 0.8:
            color_code = "\033[92m"  # 绿色
        elif score >= 0.5:
            color_code = "\033[93m"  # 黄色
        else:
            color_code = "\033[91m"  # 红色
        
        if color:
            return f"{color_code}{score:.4f}{self.COLORS['reset']}"
        return f"{score:.4f}"
    
    def print_ranking_comparison(self, query: str, top_k: int = 10):
        """打印排名对比（三种检索方式）"""
        self.print_header(f"📊 检索排名对比: '{query}'")
        
        # 执行三种检索
        print(f"{self.COLORS['dim']}正在执行检索...{self.COLORS['reset']}\n")
        
        # 1. 向量检索
        vector_results = search_logs(query, top_k=top_k)
        print(f"{self.COLORS['bold']}🔵 向量检索{self.COLORS['reset']} ({len(vector_results)} 条)")
        for i, r in enumerate(vector_results[:5], 1):
            print(f"   {i:2d}. [{self.format_score(r['score'])}] log_id={r['log_id']} | {r['level']} | {r['service']}")
            print(f"       {r['message'][:60]}...")
        
        # 2. BM25 检索
        print(f"\n{self.COLORS['bold']}🟢 BM25 检索{self.COLORS['reset']}")
        bm25_results = bm25_search(query, top_k=top_k)
        if bm25_results:
            for i, r in enumerate(bm25_results[:5], 1):
                score = r.get('score', 0)
                payload = r.get('payload', {})
                print(f"   {i:2d}. [{self.format_score(score)}] log_id={r['log_id']} | {payload.get('level')} | {payload.get('service')}")
                print(f"       {payload.get('chunk_text', '')[:60]}...")
        else:
            print(f"   {self.COLORS['dim']}无结果{self.COLORS['reset']}")
        
        # 3. 混合检索
        print(f"\n{self.COLORS['bold']}🟡 混合检索 (RRF融合){self.COLORS['reset']}")
        hybrid_results = hybrid_search(query, top_k=top_k)
        if hybrid_results:
            for i, r in enumerate(hybrid_results[:5], 1):
                print(f"   {i:2d}. [{self.format_score(r['rrf_score'])}] log_id={r['log_id']} | {r['level']} | {r['service']}")
                print(f"       向量={r['vector_score']:.4f} | BM25={r['bm25_score']:.4f}")
                print(f"       {r['message'][:60]}...")
        else:
            print(f"   {self.COLORS['dim']}无结果{self.COLORS['reset']}")
    
    def print_detail_comparison(self, query: str, top_k: int = 5):
        """打印详细对比（显示交集和并集）"""
        self.print_header(f"📋 详细对比: '{query}'")
        
        # 获取结果
        vector_results = search_logs(query, top_k=top_k)
        bm25_results = bm25_search(query, top_k=top_k)
        hybrid_results = hybrid_search(query, top_k=top_k)
        
        # 提取 log_id 集合
        vector_ids = {r['log_id'] for r in vector_results}
        bm25_ids = {r.get('log_id') for r in bm25_results}
        hybrid_ids = {r.get('log_id') for r in hybrid_results}
        
        # 计算交集
        vector_bm25_intersection = vector_ids & bm25_ids
        vector_hybrid_intersection = vector_ids & hybrid_ids
        bm25_hybrid_intersection = bm25_ids & hybrid_ids
        all_intersection = vector_ids & bm25_ids & hybrid_ids
        
        print(f"\n📊 结果统计:")
        print(f"   向量检索: {len(vector_ids)} 条")
        print(f"   BM25 检索: {len(bm25_ids)} 条")
        print(f"   混合检索: {len(hybrid_ids)} 条")
        
        print(f"\n🔗 结果交集:")
        print(f"   三种检索共同结果: {len(all_intersection)} 条")
        print(f"   向量 ∩ BM25: {len(vector_bm25_intersection)} 条")
        print(f"   向量 ∩ 混合: {len(vector_hybrid_intersection)} 条")
        print(f"   BM25 ∩ 混合: {len(bm25_hybrid_intersection)} 条")
        
        # 显示共同结果
        if all_intersection:
            print(f"\n📋 三种检索共同找到的日志:")
            for log_id in list(all_intersection)[:3]:
                # 从向量结果中获取信息
                for r in vector_results:
                    if r['log_id'] == log_id:
                        print(f"   - log_id={log_id} | {r['level']} | {r['service']}")
                        print(f"     {r['message'][:50]}...")
                        break
    
    def print_rank_comparison_table(self, query: str, top_k: int = 5):
        """打印排名对比表格"""
        self.print_header(f"📊 排名对比表格: '{query}'")
        
        # 获取结果
        vector_results = search_logs(query, top_k=top_k)
        bm25_results = bm25_search(query, top_k=top_k)
        hybrid_results = hybrid_search(query, top_k=top_k)
        
        # 建立 log_id -> 排名 的映射
        vector_rank = {r['log_id']: i+1 for i, r in enumerate(vector_results)}
        bm25_rank = {r['log_id']: i+1 for i, r in enumerate(bm25_results)}
        hybrid_rank = {r['log_id']: i+1 for i, r in enumerate(hybrid_results)}
        
        # 获取所有 log_id
        all_ids = set(vector_rank.keys()) | set(bm25_rank.keys()) | set(hybrid_rank.keys())
        
        if not all_ids:
            print("无结果")
            return
        
        print(f"\n{'log_id':>8} | {'向量排名':>8} | {'BM25排名':>8} | {'混合排名':>8} | {'变化':>6}")
        print("-" * 50)
        
        for log_id in sorted(all_ids):
            v_rank = vector_rank.get(log_id, "-")
            b_rank = bm25_rank.get(log_id, "-")
            h_rank = hybrid_rank.get(log_id, "-")
            
            # 计算变化
            change = ""
            if isinstance(v_rank, int) and isinstance(h_rank, int):
                diff = v_rank - h_rank
                if diff > 0:
                    change = f"↑{diff}"
                elif diff < 0:
                    change = f"↓{-diff}"
                else:
                    change = "="
            
            print(f"{log_id:>8} | {str(v_rank):>8} | {str(b_rank):>8} | {str(h_rank):>8} | {change:>6}")
    
    def print_query_suggestions(self):
        """打印测试查询建议"""
        self.print_header("💡 测试查询建议")
        
        suggestions = [
            ("关键词查询", [
                ("timeout", "查找超时相关日志"),
                ("database", "查找数据库相关日志"),
                ("error", "查找错误日志"),
                ("nullpointer", "查找空指针异常"),
            ]),
            ("语义查询", [
                ("数据库连接失败", "查找数据库连接问题"),
                ("服务响应缓慢", "查找性能问题"),
                ("用户登录异常", "查找认证问题"),
                ("内存溢出", "查找内存问题"),
            ]),
            ("混合查询", [
                ("NullPointerException in UserService", "精确异常名"),
                ("Connection timeout to database", "完整错误信息"),
                ("认证失败 用户登录", "中英文混合"),
            ]),
        ]
        
        for category, queries in suggestions:
            print(f"\n{self.COLORS['bold']}{category}{self.COLORS['reset']}")
            for query, desc in queries:
                print(f"   • {query:30} - {desc}")
    
    def interactive_mode(self):
        """交互式模式"""
        self.print_header("🔍 检索结果可视化工具 (交互模式)")
        
        print("输入查询进行检索，输入 'exit' 退出")
        print("-" * 60)
        
        while True:
            try:
                query = input(f"\n{self.COLORS['bold']}查询: {self.COLORS['reset']}").strip()
                
                if query.lower() in ['exit', 'quit', 'q']:
                    print("再见！")
                    break
                
                if not query:
                    continue
                
                # 选择显示模式
                print(f"\n{self.COLORS['dim']}选择显示模式:{self.COLORS['reset']}")
                print("  1. 排名对比")
                print("  2. 详细对比")
                print("  3. 排名表格")
                print("  4. 全部")
                
                mode = input(f"{self.COLORS['bold']}模式 (1-4): {self.COLORS['reset']}").strip() or "1"
                
                if mode == "1":
                    self.print_ranking_comparison(query)
                elif mode == "2":
                    self.print_detail_comparison(query)
                elif mode == "3":
                    self.print_rank_comparison_table(query)
                elif mode == "4":
                    self.print_ranking_comparison(query)
                    self.print_detail_comparison(query)
                    self.print_rank_comparison_table(query)
                else:
                    print("无效模式")
                
            except KeyboardInterrupt:
                print("\n\n再见！")
                break
            except Exception as e:
                print(f"错误: {e}")


def main():
    """主函数"""
    visualizer = RetrievalVisualizer()
    
    # 显示标题
    print(f"""
{visualizer.COLORS['bold']}╔══════════════════════════════════════════════════════════════════════╗
║                    🔍 检索结果可视化工具                        ║
║        向量检索 | BM25检索 | 混合检索 (RRF融合)                ║
╚══════════════════════════════════════════════════════════════════════╝{visualizer.COLORS['reset']}
""")
    
    # 选择模式
    print("选择运行模式:")
    print("  1. 快速演示 - 展示多个查询的排名对比")
    print("  2. 交互模式 - 自定义查询")
    print("  3. 测试查询建议")
    
    choice = input(f"\n{visualizer.COLORS['bold']}选择 (1-3): {visualizer.COLORS['reset']}").strip() or "1"
    
    if choice == "1":
        # 快速演示
        demo_queries = [
            "timeout",
            "error",
            "NullPointerException",
            "数据库连接失败",
            "Connection timeout",
        ]
        
        for query in demo_queries:
            visualizer.print_ranking_comparison(query, top_k=5)
            visualizer.print_detail_comparison(query, top_k=5)
            print("\n" + "-" * 80)
            input("按 Enter 继续...")
    
    elif choice == "2":
        visualizer.interactive_mode()
    
    elif choice == "3":
        visualizer.print_query_suggestions()
    
    else:
        print("无效选择")


if __name__ == "__main__":
    main()