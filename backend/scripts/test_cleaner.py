#清洗测试脚本
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.log_parser import LogParser
from services.log_cleaner import LogCleaner


def main():
    """测试日志清洗器"""
    
    print("=" * 60)
    print("🧪 日志清洗器测试")
    print("=" * 60)
    
    # 1. 先解析日志
    csv_path = "data/logs.csv"
    if not os.path.exists(csv_path):
        print(f"❌ 文件不存在: {csv_path}")
        return
    
    print(f"📂 正在解析文件: {csv_path}")
    valid_logs, failed_logs = LogParser.parse_csv(csv_path)
    print(f"✅ 成功解析 {len(valid_logs)} 条日志")
    
    # 2. 执行清洗
    print("\n🔄 正在清洗日志...")
    result = LogCleaner.clean_batch(valid_logs)
    
    # 3. 打印报告
    LogCleaner.print_report(result)
    
    # 4. 显示清洗前后对比样例
    cleaned_logs = result["cleaned"]
    
    if valid_logs and cleaned_logs:
        print("\n📝 清洗前后对比（第1条）：")
        print("-" * 80)
        print("【清洗前】")
        print(f"  {valid_logs[0]}")
        print("【清洗后】")
        print(f"  {cleaned_logs[0]}")
        print("-" * 80)
    
    # 5. 保存清洗后的数据
    if cleaned_logs:
        import csv
        output_path = "logs_cleaned.csv"
        fieldnames = ["timestamp", "level", "service", "ip", "message", "trace_id"]
        
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(cleaned_logs)
        
        print(f"\n💾 清洗后数据已保存到: {output_path}")


if __name__ == "__main__":
    main()