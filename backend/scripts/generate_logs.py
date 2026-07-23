import csv
import random
from datetime import datetime, timedelta

# ==================== 配置区域 ====================
# 日志数量（可根据需要调整，建议先跑100条测试，再改为10000条）
LOG_COUNT = 10000

# 服务列表
SERVICES = ["auth-service", "order-service", "payment-service", "user-service", "notification-service"]

# 日志级别（按权重分布：INFO最多，ERROR最少）
LOG_LEVELS = ["INFO", "INFO", "INFO", "WARNING", "WARNING", "ERROR", "ERROR", "DEBUG"]

# 错误信息列表（ERROR级别时随机选取）
ERROR_MESSAGES = [
    "Connection timeout to database",
    "NullPointerException in UserService",
    "Payment gateway unavailable",
    "Invalid token provided",
    "Rate limit exceeded",
    "File not found: /var/log/app.log",
    "OutOfMemoryError: Java heap space",
    "Network unreachable",
    "SSL handshake failed",
    "Transaction rollback due to deadlock",
]

# 正常信息列表（INFO级别时随机选取）
INFO_MESSAGES = [
    "User login successful",
    "Order created successfully",
    "Payment processed successfully",
    "User registered successfully",
    "Cache refreshed",
    "Scheduled job completed",
    "Health check passed",
    "Configuration loaded successfully",
]
# =================================================


def generate_logs(count=LOG_COUNT):
    """
    生成模拟日志数据
    
    Args:
        count: 生成的日志条数
        
    Returns:
        list: 包含日志字典的列表
    """
    logs = []
    # 从7天前开始生成，均匀分布
    start_time = datetime.now() - timedelta(days=7)
    
    for i in range(count):
        # 1. 生成随机时间戳（分布在过去7天内）
        random_seconds = random.randint(0, 7 * 24 * 3600)  # 7天的秒数
        timestamp = start_time + timedelta(seconds=random_seconds)
        
        # 2. 随机选择日志级别（按权重分布）
        level = random.choice(LOG_LEVELS)
        
        # 3. 随机选择服务
        service = random.choice(SERVICES)
        
        # 4. 根据级别生成消息
        if level == "ERROR":
            message = random.choice(ERROR_MESSAGES)
        elif level == "WARNING":
            message = random.choice(ERROR_MESSAGES[:5]) + " (retry in 5s)"
        else:
            message = random.choice(INFO_MESSAGES)
        
        # 5. 生成随机IP（内网地址）
        ip = f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}"
        
        # 6. 生成随机trace_id（8位十六进制）
        trace_id = format(random.randint(0, 0xFFFFFFFF), '08x')
        
        # 7. 组装成字典
        log_entry = {
            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "service": service,
            "ip": ip,
            "message": message,
            "trace_id": trace_id, #链路追踪 ID
        }
        logs.append(log_entry)
    
    return logs


def save_to_csv(logs, filename="logs.csv"):
    """
    将日志列表保存为CSV文件
    
    Args:
        logs: 日志字典列表
        filename: 输出文件名
    """
    if not logs:
        print("⚠️ 没有数据可保存")
        return
    
    fieldnames = ["timestamp", "level", "service", "ip", "message", "trace_id"]
    
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(logs)
    
    print(f"✅ 已生成 {len(logs)} 条日志 -> {filename}")


def print_statistics(logs):
    """
    打印日志统计信息
    """
    if not logs:
        return
    
    # 按级别统计
    level_count = {}
    for log in logs:
        level = log["level"]
        level_count[level] = level_count.get(level, 0) + 1
    
    # 按服务统计
    service_count = {}
    for log in logs:
        service = log["service"]
        service_count[service] = service_count.get(service, 0) + 1
    
    print("\n" + "=" * 50)
    print("📊 日志统计信息")
    print("=" * 50)
    print(f"总条数: {len(logs)}")
    print("\n【按日志级别分布】")
    for level, count in sorted(level_count.items()):
        pct = count / len(logs) * 100
        bar = "█" * int(pct / 2)  # 简单柱状图
        print(f"  {level:7} {count:6} 条 ({pct:5.1f}%) {bar}")
    
    print("\n【按服务分布】")
    for service, count in sorted(service_count.items()):
        pct = count / len(logs) * 100
        print(f"  {service:18} {count:6} 条 ({pct:5.1f}%)")
    print("=" * 50)


if __name__ == "__main__":
    print("🚀 开始生成模拟日志...")
    
    # 生成日志
    logs = generate_logs(LOG_COUNT)
    
    # 保存为CSV
    save_to_csv(logs, "logs.csv")
    
    # 打印统计信息
    print_statistics(logs)
    
    # 打印几条示例
    print("\n📝 日志示例（前5条）：")
    print("-" * 80)
    for i, log in enumerate(logs[:5]):
        print(f"{i+1}. [{log['level']}] {log['timestamp']} | {log['service']} | {log['message']}")
    print("-" * 80)