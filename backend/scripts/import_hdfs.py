"""
HDFS 日志数据集适配器。

将 HDFS.log（Loghub 公开数据集）转换为项目期望的 6 字段 CSV 格式：
    timestamp, level, service, ip, message, trace_id

HDFS 原始格式：
    081109 203519 1485 INFO dfs.DataNode$PacketReceiver: PacketResponder 1 for block blk_-1601959949770634159 terminating
    日期MMDDYY 时间HHMMSS PID 级别 组件: 消息

输出格式（与 generate_logs.py 一致，可被 LogParser 解析）：
    timestamp, level, service, ip, message, trace_id

使用方法：
    python scripts/import_hdfs.py --input HDFS.log --output data/hdfs_logs.csv --max-logs 10000
"""
import sys
import os
import re
import csv
import uuid
import argparse
from pathlib import Path
from datetime import datetime

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))


# HDFS 日志正则（Loghub 标准格式）
# 示例: 081109 203519 1485 INFO dfs.DataNode$PacketReceiver: PacketResponder 1 for block ...
HDFS_PATTERN = re.compile(
    r'^(?P<date>\d{6})\s+(?P<time>\d{6})\s+(?P<pid>\d+)\s+(?P<level>\w+)\s+(?P<component>[^:]+):\s*(?P<message>.*)$'
)

# 级别映射（HDFS 用的是标准 Hadoop 级别）
LEVEL_MAP = {
    'INFO': 'INFO',
    'WARN': 'WARNING',
    'WARNING': 'WARNING',
    'ERROR': 'ERROR',
    'FATAL': 'ERROR',
    'DEBUG': 'DEBUG',
    'TRACE': 'DEBUG',
}


def parse_hdfs_date(date_str: str, time_str: str) -> str:
    """
    将 HDFS 的日期时间格式转为项目期望的 "YYYY-MM-DD HH:MM:SS"

    输入: date="081109" time="203519"
    含义: 08年11月09日 20:35:19
    输出: "2008-11-09 20:35:19"
    """
    try:
        # HDFS 数据集是 2008 年左右采集的
        yy = int(date_str[0:2])
        mm = int(date_str[2:4])
        dd = int(date_str[4:6])
        year = 2000 + yy  # 08 → 2008
        hh = int(time_str[0:2])
        mi = int(time_str[2:4])
        ss = int(time_str[4:6])
        return f"{year:04d}-{mm:02d}-{dd:02d} {hh:02d}:{mi:02d}:{ss:02d}"
    except Exception:
        # 解析失败返回当前时间
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def extract_service(component: str) -> str:
    """
    从 HDFS 组件名提取 service 字段。

    示例:
        dfs.DataNode$PacketReceiver  →  dfs.DataNode
        dfs.FSNamesystem             →  dfs.FSNamesystem
        dfs.NameNode                 →  dfs.NameNode
    """
    # 去掉 $ 后面的内部类
    return component.split('$')[0].strip()


def convert_hdfs_to_csv(input_path: Path, output_path: Path,
                        max_logs: int = None, encoding: str = 'utf-8') -> dict:
    """
    将 HDFS.log 转换为项目 CSV 格式。

    Args:
        input_path: HDFS.log 路径
        output_path: 输出 CSV 路径
        max_logs: 最多转换多少条（None=全部）
        encoding: 输入文件编码（默认 utf-8，PowerShell 导出文件常为 utf-16）

    Returns:
        统计字典
    """
    fieldnames = ["timestamp", "level", "service", "ip", "message", "trace_id"]
    total = 0
    valid = 0
    failed = 0
    level_count = {}
    service_count = {}

    print(f"开始转换: {input_path} → {output_path} (encoding={encoding})")
    if max_logs:
        print(f"最多转换 {max_logs} 条")

    with open(input_path, 'r', encoding=encoding, errors='ignore') as fin, \
         open(output_path, 'w', newline='', encoding='utf-8') as fout:

        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()

        for line_num, line in enumerate(fin, 1):
            if max_logs and valid >= max_logs:
                break

            total += 1
            line = line.rstrip('\n')

            # 正则匹配
            m = HDFS_PATTERN.match(line)
            if not m:
                failed += 1
                continue

            # 提取字段
            timestamp = parse_hdfs_date(m.group('date'), m.group('time'))
            raw_level = m.group('level').upper()
            level = LEVEL_MAP.get(raw_level, 'INFO')
            service = extract_service(m.group('component'))
            message = m.group('message').strip()
            # HDFS 日志没有 IP，填占位
            ip = "0.0.0.0"
            # HDFS 日志没有 trace_id，生成 8 位 hex
            trace_id = uuid.uuid4().hex[:8]

            writer.writerow({
                "timestamp": timestamp,
                "level": level,
                "service": service,
                "ip": ip,
                "message": message,
                "trace_id": trace_id,
            })

            valid += 1
            level_count[level] = level_count.get(level, 0) + 1
            service_count[service] = service_count.get(service, 0) + 1

            # 进度打印
            if total % 10000 == 0:
                print(f"  已处理 {total} 行, 有效 {valid} 条")

    # 统计输出
    print("\n" + "=" * 50)
    print("HDFS 数据集转换完成")
    print("=" * 50)
    print(f"总行数:       {total}")
    print(f"有效日志:     {valid}")
    print(f"解析失败:     {failed}")
    print(f"有效率:       {valid/total*100:.1f}%" if total > 0 else "0%")
    print(f"\n按级别分布:")
    for lvl in sorted(level_count.keys()):
        print(f"  {lvl:10} {level_count[lvl]:>8} 条")
    print(f"\n按服务分布 (Top 10):")
    for svc, cnt in sorted(service_count.items(), key=lambda x: -x[1])[:10]:
        print(f"  {svc:30} {cnt:>8} 条")
    print("=" * 50)
    print(f"输出文件: {output_path}")

    return {
        "total": total,
        "valid": valid,
        "failed": failed,
        "level_count": level_count,
        "service_count": service_count,
    }


def main():
    parser = argparse.ArgumentParser(description="HDFS 日志数据集适配器")
    parser.add_argument(
        "--input", "-i",
        type=str,
        required=True,
        help="HDFS.log 输入文件路径",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=str(Path(__file__).parent.parent / "data" / "hdfs_logs.csv"),
        help=f"输出 CSV 路径（默认: data/hdfs_logs.csv）",
    )
    parser.add_argument(
        "--max-logs", "-n",
        type=int,
        default=10000,
        help="最多转换多少条（默认: 10000，设为 0 表示全部）",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误: 输入文件不存在: {input_path}")
        sys.exit(1)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    max_logs = args.max_logs if args.max_logs > 0 else None

    convert_hdfs_to_csv(input_path, output_path, max_logs=max_logs)


if __name__ == "__main__":
    main()
