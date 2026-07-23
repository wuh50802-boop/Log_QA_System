#日志清洗模块
import re
from typing import List, Dict, Set, Tuple


class LogCleaner:
    """
    日志清洗器：对解析后的日志进行去重、空值过滤、格式统一
    """
    
    # 合法的日志级别（标准化用）
    LEVEL_MAPPING = {
        "info": "INFO",
        "information": "INFO",
        "warning": "WARNING",
        "warn": "WARNING",
        "error": "ERROR",
        "err": "ERROR",
        "debug": "DEBUG",
        "dbg": "DEBUG",
    }
    
    # 需要过滤的特殊字符（乱码/不可见字符）
    SPECIAL_CHARS_PATTERN = re.compile(r'[^\x00-\x7F\u4e00-\u9fff]')
    
    @classmethod
    def normalize_level(cls, level: str) -> str:
        """
        标准化日志级别：统一转为大写，处理简写
        
        Args:
            level: 原始日志级别
            
        Returns:
            标准化的日志级别，如果无法识别则返回 "UNKNOWN"
        """
        if not level:
            return "UNKNOWN"
        
        level_lower = str(level).strip().lower()
        return cls.LEVEL_MAPPING.get(level_lower, level_lower.upper())
    
    @classmethod
    def normalize_timestamp(cls, timestamp: str) -> str:
        """
        标准化时间戳：去除多余空格，确保格式统一
        
        Args:
            timestamp: 原始时间戳
            
        Returns:
            标准化后的时间戳
        """
        if not timestamp:
            return ""
        # 去除首尾空格，将多个空格合并为一个
        return re.sub(r'\s+', ' ', str(timestamp).strip())
    
    @classmethod
    def normalize_ip(cls, ip: str) -> str:
        """
        标准化IP地址：去除多余空格
        
        Args:
            ip: 原始IP地址
            
        Returns:
            标准化后的IP地址
        """
        if not ip:
            return ""
        return str(ip).strip()
    
    @classmethod
    def normalize_message(cls, message: str) -> str:
        """
        清洗日志消息：去除特殊字符、多余空格
        
        Args:
            message: 原始消息
            
        Returns:
            清洗后的消息
        """
        if not message:
            return ""
        
        # 1. 去除首尾空格
        cleaned = str(message).strip()
        
        # 2. 去除特殊字符（保留中英文、数字、常用标点）
        cleaned = cls.SPECIAL_CHARS_PATTERN.sub('', cleaned)
        
        # 3. 将多个空格合并为一个
        cleaned = re.sub(r'\s+', ' ', cleaned)
        
        return cleaned
    
    @classmethod
    def normalize_trace_id(cls, trace_id: str) -> str:
        """
        标准化trace_id：转为小写，确保8位
        
        Args:
            trace_id: 原始trace_id
            
        Returns:
            标准化后的trace_id
        """
        if not trace_id:
            return ""
        cleaned = str(trace_id).strip().lower()
        # 补齐到8位（不足前面补0）
        if len(cleaned) < 8 and cleaned.isalnum():
            cleaned = cleaned.zfill(8)
        return cleaned
    
    @classmethod
    def clean_single(cls, log: Dict) -> Dict:
        """
        清洗单条日志
        
        Args:
            log: 原始日志字典
            
        Returns:
            清洗后的日志字典
        """
        cleaned = {}
        
        # 逐字段清洗
        cleaned["timestamp"] = cls.normalize_timestamp(log.get("timestamp", ""))
        cleaned["level"] = cls.normalize_level(log.get("level", ""))
        cleaned["service"] = str(log.get("service", "")).strip()
        cleaned["ip"] = cls.normalize_ip(log.get("ip", ""))
        cleaned["message"] = cls.normalize_message(log.get("message", ""))
        cleaned["trace_id"] = cls.normalize_trace_id(log.get("trace_id", ""))
        
        return cleaned
    
    @classmethod
    def is_empty(cls, log: Dict) -> bool:
        """
        检查日志是否为空（关键字段缺失或为空）
        
        Args:
            log: 日志字典
            
        Returns:
            是否为空
        """
        # 检查关键字段
        required = ["timestamp", "level", "service", "message"]
        for field in required:
            value = log.get(field, "")
            if not value or not str(value).strip():
                return True
        
        # 检查级别是否为UNKNOWN（无法识别）
        if log.get("level") == "UNKNOWN":
            return True
        
        return False
    
    @classmethod
    def deduplicate(cls, logs: List[Dict]) -> Tuple[List[Dict], int]:
        """
        去重：根据 (timestamp, level, service, message) 组合去重
        
        Args:
            logs: 日志列表
            
        Returns:
            (去重后的日志列表, 删除的重复数量)
        """
        seen: Set[Tuple[str, str, str, str]] = set()
        unique_logs = []
        duplicate_count = 0
        
        for log in logs:
            # 构造唯一键
            key = (
                log.get("timestamp", ""),
                log.get("level", ""),
                log.get("service", ""),
                log.get("message", ""),
            )
            
            if key not in seen:
                seen.add(key)
                unique_logs.append(log)
            else:
                duplicate_count += 1
        
        return unique_logs, duplicate_count
    
    @classmethod
    def clean_batch(cls, logs: List[Dict]) -> Dict:
        """
        批量清洗日志
        
        Args:
            logs: 原始日志列表
            
        Returns:
            {
                "cleaned": [...],      # 清洗后的日志
                "removed_empty": int,  # 移除的空值数量
                "removed_duplicate": int,  # 移除的重复数量
                "statistics": {...}    # 统计信息
            }
        """
        original_count = len(logs)
        
        # 1. 逐条清洗
        cleaned_logs = []
        empty_count = 0
        
        for log in logs:
            cleaned = cls.clean_single(log)
            if not cls.is_empty(cleaned):
                cleaned_logs.append(cleaned)
            else:
                empty_count += 1
        
        # 2. 去重
        deduped_logs, duplicate_count = cls.deduplicate(cleaned_logs)
        
        # 3. 统计信息
        statistics = {
            "original_count": original_count,
            "after_cleaning": len(cleaned_logs),
            "after_dedup": len(deduped_logs),
            "removed_empty": empty_count,
            "removed_duplicate": duplicate_count,
            "total_removed": original_count - len(deduped_logs),
            "final_count": len(deduped_logs),
        }
        
        return {
            "cleaned": deduped_logs,
            "removed_empty": empty_count,
            "removed_duplicate": duplicate_count,
            "statistics": statistics,
        }
    
    @classmethod
    def print_report(cls, result: Dict):
        """
        打印清洗报告
        
        Args:
            result: clean_batch 的返回结果
        """
        stats = result.get("statistics", {})
        
        print("\n" + "=" * 60)
        print("🧹 日志清洗报告")
        print("=" * 60)
        print(f"原始日志条数:    {stats.get('original_count', 0):>8}")
        print(f"清洗后条数:      {stats.get('after_cleaning', 0):>8}")
        print(f"去重后条数:      {stats.get('after_dedup', 0):>8}")
        print("-" * 60)
        print(f"移除空值:        {stats.get('removed_empty', 0):>8}")
        print(f"移除重复:        {stats.get('removed_duplicate', 0):>8}")
        print(f"总计移除:        {stats.get('total_removed', 0):>8}")
        print("=" * 60)
        print(f"✅ 最终有效日志:  {stats.get('final_count', 0):>8} 条")
        print("=" * 60)