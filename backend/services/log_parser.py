import csv
import re
from typing import List, Dict, Optional, Tuple


class LogParser:
    """
    日志解析器：读取CSV日志文件，解析并验证每条日志的字段完整性
    """
    
    # 必填字段列表
    REQUIRED_FIELDS = ["timestamp", "level", "service", "ip", "message", "trace_id"]
    
    # 合法的日志级别
    VALID_LEVELS = {"INFO", "WARNING", "ERROR", "DEBUG"}
    
    # 时间戳正则表达式（格式：2026-07-15 10:23:05）
    TIMESTAMP_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}$')
    
    # IP地址正则表达式（简单版）
    IP_PATTERN = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
    
    # trace_id正则表达式（8位十六进制）
    TRACE_ID_PATTERN = re.compile(r'^[0-9a-fA-F]{8}$')
    
    @classmethod
    def parse_line(cls, log_dict: Dict) -> Tuple[bool, Optional[str]]:
        """
        验证单条日志字典的字段完整性
        
        Args:
            log_dict: 日志字典
            
        Returns:
            (是否有效, 错误信息)
        """
        # 1. 检查所有必填字段是否存在
        for field in cls.REQUIRED_FIELDS:
            if field not in log_dict or not log_dict[field] or not str(log_dict[field]).strip():
                return False, f"缺少必填字段或字段为空: {field}"
        
        # 2. 验证日志级别
        level = log_dict["level"].upper()
        if level not in cls.VALID_LEVELS:
            return False, f"无效的日志级别: {level}，合法值为: {', '.join(cls.VALID_LEVELS)}"
        
        # 3. 验证时间戳格式
        if not cls.TIMESTAMP_PATTERN.match(log_dict["timestamp"]):
            return False, f"无效的时间戳格式: {log_dict['timestamp']}，需要格式: YYYY-MM-DD HH:MM:SS"
        
        # 4. 验证IP地址格式（简单验证）
        if not cls.IP_PATTERN.match(log_dict["ip"]):
            return False, f"无效的IP地址格式: {log_dict['ip']}"
        
        # 5. 验证trace_id格式
        if not cls.TRACE_ID_PATTERN.match(log_dict["trace_id"]):
            return False, f"无效的trace_id格式: {log_dict['trace_id']}，需要8位十六进制"
        
        return True, None
    
    @classmethod
    def parse_csv(cls, filepath: str, encoding: str = "utf-8") -> Tuple[List[Dict], List[Dict]]:
        """
        解析CSV日志文件
        
        Args:
            filepath: CSV文件路径
            encoding: 文件编码
            
        Returns:
            (valid_logs, failed_logs)
            - valid_logs: 解析成功的日志列表
            - failed_logs: 解析失败的日志列表（含错误信息）
        """
        valid_logs = []
        failed_logs = []
        
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                # 先尝试读取表头
                sample = f.readline()
                f.seek(0)  # 回到文件开头
                
                # 检测是否有表头
                has_header = ',' in sample and not sample[0].isdigit()
                
                reader = csv.DictReader(f) if has_header else csv.reader(f)
                
                for row_num, row in enumerate(reader, start=1 if has_header else 0):
                    # 处理无表头的情况
                    if not has_header:
                        if len(row) < len(cls.REQUIRED_FIELDS):
                            failed_logs.append({
                                "row": row_num,
                                "data": row,
                                "error": f"字段数量不足: 期望{len(cls.REQUIRED_FIELDS)}个，实际{len(row)}个"
                            })
                            continue
                        log_dict = dict(zip(cls.REQUIRED_FIELDS, row))
                    else:
                        log_dict = dict(row)
                    
                    # 清洗字段值（去除首尾空格）
                    log_dict = {k: str(v).strip() for k, v in log_dict.items()}
                    
                    # 验证日志
                    is_valid, error_msg = cls.parse_line(log_dict)
                    
                    if is_valid:
                        # 统一日志级别为大写
                        log_dict["level"] = log_dict["level"].upper()
                        valid_logs.append(log_dict)
                    else:
                        failed_logs.append({
                            "row": row_num,
                            "data": log_dict,
                            "error": error_msg
                        })
                        
        except FileNotFoundError:
            print(f"❌ 文件未找到: {filepath}")
            return [], []
        except Exception as e:
            print(f"❌ 解析文件时发生错误: {str(e)}")
            return [], []
        
        return valid_logs, failed_logs
    
    @classmethod
    def get_statistics(cls, valid_logs: List[Dict], failed_logs: List[Dict]) -> Dict:
        """
        获取解析统计信息
        
        Returns:
            包含统计信息的字典
        """
        total = len(valid_logs) + len(failed_logs)
        
        # 按级别统计有效日志
        level_count = {}
        for log in valid_logs:
            level = log.get("level", "UNKNOWN")
            level_count[level] = level_count.get(level, 0) + 1
        
        # 按服务统计有效日志
        service_count = {}
        for log in valid_logs:
            service = log.get("service", "UNKNOWN")
            service_count[service] = service_count.get(service, 0) + 1
        
        return {
            "total": total,
            "valid_count": len(valid_logs),
            "failed_count": len(failed_logs),
            "valid_rate": len(valid_logs) / total * 100 if total > 0 else 0,
            "level_distribution": level_count,
            "service_distribution": service_count,
            "failed_samples": failed_logs[:5] if failed_logs else [],  # 只保留前5条错误样例
        }
    
    @classmethod
    def save_failed_logs(cls, failed_logs: List[Dict], output_path: str = "failed.log"):
        """
        将解析失败的日志保存到文件
        
        Args:
            failed_logs: 失败日志列表
            output_path: 输出文件路径
        """
        if not failed_logs:
            # 创建空文件
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("# 无解析失败的日志\n")
            return
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("# 日志解析失败记录\n")
            f.write("#" + "=" * 60 + "\n")
            f.write(f"# 共 {len(failed_logs)} 条记录解析失败\n")
            f.write("#" + "=" * 60 + "\n\n")
            
            for failed in failed_logs:
                f.write(f"[行号: {failed.get('row', 'N/A')}]\n")
                f.write(f"  原始数据: {failed.get('data', {})}\n")
                f.write(f"  错误原因: {failed.get('error', '未知错误')}\n")
                f.write("\n")