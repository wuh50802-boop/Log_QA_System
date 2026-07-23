#测试日志解析器
import sys
import os

# 将项目根目录添加到 Python 路径，以便导入 services 模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.log_parser import LogParser


def main():
    """测试日志解析器"""
    
    print("=" * 60)
    print("🧪 日志解析器测试")
    print("=" * 60)
    
    # 1. 解析CSV文件
    csv_path = "data/logs.csv"
    
    if not os.path.exists(csv_path):
        print(f"❌ 文件不存在: {csv_path}")
        print("   请先运行 Day 4 的日志生成脚本: python scripts/generate_logs.py")
        return
    
    print(f"📂 正在解析文件: {csv_path}")
    valid_logs, failed_logs = LogParser.parse_csv(csv_path)
    
    # 2. 获取统计信息
    stats = LogParser.get_statistics(valid_logs, failed_logs)
    
    # 3. 打印统计结果
    print("\n" + "=" * 60)
    print("📊 解析结果统计")
    print("=" * 60)
    print(f"总日志条数: {stats['total']}")
    print(f"✅ 解析成功: {stats['valid_count']} 条 ({stats['valid_rate']:.1f}%)")
    print(f"❌ 解析失败: {stats['failed_count']} 条")
    
    # 4. 打印级别分布
    if stats['level_distribution']:
        print("\n【按日志级别分布】")
        for level, count in sorted(stats['level_distribution'].items()):
            pct = count / stats['valid_count'] * 100 if stats['valid_count'] > 0 else 0
            bar = "█" * int(pct / 2)
            print(f"  {level:7} {count:6} 条 ({pct:5.1f}%) {bar}")
    
    # 5. 打印服务分布
    if stats['service_distribution']:
        print("\n【按服务分布】")
        for service, count in sorted(stats['service_distribution'].items()):
            pct = count / stats['valid_count'] * 100 if stats['valid_count'] > 0 else 0
            print(f"  {service:20} {count:6} 条 ({pct:5.1f}%)")
    
    # 6. 打印失败样例
    if stats['failed_samples']:
        print("\n【解析失败样例】")
        for i, sample in enumerate(stats['failed_samples'], 1):
            print(f"  {i}. 行号: {sample.get('row', 'N/A')}")
            print(f"     数据: {sample.get('data', {})}")
            print(f"     错误: {sample.get('error', '未知')}")
    
    # 7. 保存失败日志
    if failed_logs:
        LogParser.save_failed_logs(failed_logs, "failed.log")
        print(f"\n📄 失败记录已保存到: failed.log")
    else:
        # 创建空文件表示全部成功
        LogParser.save_failed_logs([], "failed.log")
        print(f"\n📄 全部解析成功！已生成空的 failed.log")
    
    # 8. 验证通过条件
    print("\n" + "=" * 60)
    if stats['valid_rate'] >= 95:
        print("✅ 验收通过：解析准确率 > 95%")
    else:
        print(f"❌ 验收未通过：解析准确率 {stats['valid_rate']:.1f}% < 95%，需要优化正则表达式")
    print("=" * 60)
    
    # 9. 显示几条解析成功的样例
    if valid_logs:
        print("\n📝 解析成功样例（前3条）：")
        print("-" * 80)
        for i, log in enumerate(valid_logs[:3], 1):
            print(f"{i}. [{log['level']}] {log['timestamp']} | {log['service']} | {log['message']}")
        print("-" * 80)


if __name__ == "__main__":
    main()