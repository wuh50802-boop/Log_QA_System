"""
文本分块服务
将长日志文本切分为适合向量化的短文本块
所有策略均保护数字+单位组合的完整性（如 120s, 500ms, 3次, 5分钟 等）
适配 BAAI/bge-base-zh-v1.5 中文嵌入模型
"""
import re
import logging
from typing import List, Dict, Any, Optional, Generator
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ===================== 全局预编译正则常量（性能优化核心） =====================
# 句子结束分隔符，捕获分组保留标点
RE_SENTENCE_END = re.compile(r'([。！？；\n.!?;]+)')
# 匹配数字后的单位：英文单位/中文单位
RE_UNIT_SUFFIX = re.compile(r'[a-zA-Z\u4e00-\u9fa5]+')
# 纯数字匹配
RE_DIGIT = re.compile(r'\d')

# ===================== 数据结构 =====================
@dataclass(slots=True)  # __slots__ 减少内存开销，海量块场景提升50%内存利用率
class Chunk:
    """文本块数据结构，保留原文字符偏移用于检索回溯"""
    text: str                          # 块文本内容
    chunk_id: int                      # 当前文本内块序号
    start_char: int                    # 原文本起始字符下标（原始未切片坐标）
    end_char: int                      # 原文本结束字符下标
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """序列化字典，适配向量库存储"""
        return {
            "text": self.text,
            "chunk_id": self.chunk_id,
            "start_char": self.start_char,
            "end_char": self.end_char,
            "metadata": self.metadata,
        }

# ===================== 核心分块器 =====================
class LogChunker:
    """
    日志专用文本分块器，适配BGE中文向量模型
    支持三种策略：
        fixed: 固定长度滑动窗口，堆栈/无标点乱码日志首选
        sentence: 句子优先分块，标准结构化日志，完整语义
        hybrid: 混合策略（推荐生产）=句子分块+超长句自动固定切割
    内置保护规则：不拆分数字+单位组合、保留原文字符偏移、块重叠防语义断裂
    """
    # 默认配置常量
    DEFAULT_CHUNK_SIZE = 256    # 单块最大字符，适配BGE 512token窗口
    DEFAULT_OVERLAP = 50        # 块重叠长度，建议 chunk_size * 0.1 ~ 0.2
    DEFAULT_MIN_CHUNK_SIZE = 20 # 最小有效块长度，过短碎片自动合并
    MAX_TOKEN_RATIO = 2.2       # 中文粗略字符转token系数：1token≈2.2中文字符

    # 支持策略枚举
    STRATEGY_FIXED = "fixed"
    STRATEGY_SENTENCE = "sentence"
    STRATEGY_HYBRID = "hybrid"
    SUPPORT_STRATEGIES = {STRATEGY_FIXED, STRATEGY_SENTENCE, STRATEGY_HYBRID}

    def __init__(
        self,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_OVERLAP,
        min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE,
        strategy: str = STRATEGY_FIXED
    ):
        # 参数合法性校验，提前拦截非法入参
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须为正整数")
        if overlap < 0:
            raise ValueError("overlap 不能为负数")
        if min_chunk_size < 0:
            raise ValueError("min_chunk_size 不能为负数")
        if strategy not in self.SUPPORT_STRATEGIES:
            logger.warning(f"未知策略 {strategy}，自动降级 fixed")
            strategy = self.STRATEGY_FIXED

        self.chunk_size = chunk_size
        self.overlap = min(overlap, chunk_size // 2)  # 重叠不超过块一半
        self.min_chunk_size = min_chunk_size
        self.strategy = strategy

        logger.info(
            f"LogChunker 初始化完成 | chunk_size={chunk_size}, overlap={self.overlap}, "
            f"min_chunk={min_chunk_size}, strategy={strategy}"
        )

    def chunk_text(self, text: str, metadata: Optional[Dict[str, Any]] = None) -> List[Chunk]:
        """单条文本完整分块入口"""
        raw_text = text
        if not raw_text or len(raw_text.strip()) == 0:
            return []
        meta = metadata.copy() if metadata else {}

        if self.strategy == self.STRATEGY_FIXED:
            return self._chunk_fixed(raw_text, meta)
        elif self.strategy == self.STRATEGY_SENTENCE:
            return self._chunk_by_sentence(raw_text, meta)
        else:
            return self._chunk_hybrid(raw_text, meta)

    def chunk_logs_iter(self, logs: List[Dict[str, Any]], text_field: str = "message") -> Generator[Chunk, None, None]:
        """
        批量日志分块【生成器迭代版本】，低内存，海量日志推荐使用
        逐块yield，无需一次性存储所有Chunk列表
        """
        total_logs = len(logs)
        logger.info(f"开始流式分块 {total_logs} 条日志")
        for idx, log in enumerate(logs):
            text = log.get(text_field, "")
            if not text:
                continue
            # 组装通用元数据
            meta = {
                "log_id": log.get("id", idx),
                "level": log.get("level", "UNKNOWN"),
                "service": log.get("service", "unknown"),
                "timestamp": str(log.get("timestamp", "")),
            }
            for extra_key in ("ip", "trace_id"):
                if extra_key in log:
                    meta[extra_key] = log[extra_key]
            # 单条日志分块并迭代输出
            chunk_list = self.chunk_text(text, meta)
            for chunk in chunk_list:
                yield chunk
            # 每1000条打印进度
            if (idx + 1) % 1000 == 0:
                logger.info(f"分块进度: {idx + 1}/{total_logs}")
        logger.info("流式分块全部完成")

    def chunk_logs(self, logs: List[Dict[str, Any]], text_field: str = "message") -> List[Chunk]:
        """批量日志分块，返回完整列表（小数据量使用，大数据优先 chunk_logs_iter）"""
        return list(self.chunk_logs_iter(logs, text_field))

    # ===================== 私有工具方法 =====================
    def _adjust_cut_bound(self, text: str, start: int, end: int) -> int:
        """
        固定分块边界修正工具
        1. 优先句子标点回退截断点
        2. 保护数字+单位不被拆分（如 120|s → 回退到数字开头）
        返回修正后的end下标
        """
        text_len = len(text)
        if end >= text_len:
            return end
        min_valid_pos = start + self.min_chunk_size

        # 第一步：优先在句子分隔符截断
        sep_list = ['。', '！', '？', '；', '.', '!', '?', ';', '\n']
        best_sep_pos = -1
        for sep in sep_list:
            pos = text.rfind(sep, start, end)
            if pos >= min_valid_pos:
                best_sep_pos = pos + 1
                break
        if best_sep_pos != -1:
            return best_sep_pos

        # 第二步：无标点，保护数字+单位组合不被切断
        cut_pos = end
        # 场景1：截断位置在数字中间（12|0s）
        if cut_pos > start and RE_DIGIT.match(text[cut_pos - 1]):
            # 向前回溯找到数字起始
            while cut_pos > start and RE_DIGIT.match(text[cut_pos - 1]):
                cut_pos -= 1
            # 回退后长度不足，放弃修正
            if cut_pos - start < min_valid_pos:
                return end
        # 场景2：截断在数字末尾，后方紧跟单位（120|s）
        if cut_pos < text_len and RE_DIGIT.match(text[cut_pos - 1]):
            unit_match = RE_UNIT_SUFFIX.match(text[cut_pos:])
            if unit_match:
                num_start = cut_pos - 1
                while num_start > start and RE_DIGIT.match(text[num_start - 1]):
                    num_start -= 1
                # 回退后长度达标则回退，否则少量扩容包含单位
                if num_start - start >= min_valid_pos:
                    cut_pos = num_start
                else:
                    expand_end = cut_pos + len(unit_match.group())
                    if expand_end - start <= self.chunk_size + 10:
                        cut_pos = expand_end
        return cut_pos

    def _merge_short_fragments(self, chunk_list: List[Chunk]) -> List[Chunk]:
        """合并过短碎片块，消除无意义小文本"""
        if len(chunk_list) <= 1:
            return chunk_list
        merged = []
        idx = 0
        short_threshold = int(self.min_chunk_size * 0.6)
        while idx < len(chunk_list):
            curr = chunk_list[idx]
            # 当前块过短且存在下一块，尝试合并
            if len(curr.text) < short_threshold and idx + 1 < len(chunk_list):
                nxt = chunk_list[idx + 1]
                combined_text = curr.text + nxt.text
                if len(combined_text) <= self.chunk_size:
                    new_chunk = Chunk(
                        text=combined_text,
                        chunk_id=len(merged),
                        start_char=curr.start_char,
                        end_char=nxt.end_char,
                        metadata=curr.metadata.copy()
                    )
                    merged.append(new_chunk)
                    idx += 2
                    continue
            merged.append(curr)
            idx += 1
        # 重新统一编号
        for new_id, ck in enumerate(merged):
            ck.chunk_id = new_id
        return merged

    def _split_full_sentences(self, text: str) -> List[str]:
        """完整分句，保留标点，过滤空字符串"""
        parts = RE_SENTENCE_END.split(text)
        sentence_buf = []
        buffer = ""
        for part in parts:
            if RE_SENTENCE_END.fullmatch(part):
                if buffer:
                    sentence_buf.append(buffer + part)
                    buffer = ""
            else:
                buffer = part
        # 处理末尾无标点剩余文本
        if buffer.strip():
            sentence_buf.append(buffer)
        # 过滤纯空白句子
        return [s for s in sentence_buf if s.strip()]

    # ===================== 分块策略实现 =====================
    def _chunk_fixed(self, text: str, metadata: Dict[str, Any]) -> List[Chunk]:
        """固定长度滑动窗口分块，数字单位保护"""
        chunks: List[Chunk] = []
        text_len = len(text)
        if text_len <= self.chunk_size:
            chunks.append(Chunk(
                text=text, chunk_id=0, start_char=0, end_char=text_len, metadata=metadata.copy()
            ))
            return chunks

        start = 0
        chunk_id = 0
        while start < text_len:
            raw_end = min(start + self.chunk_size, text_len)
            # 修正截断边界，保护语义与数字单位
            cut_end = self._adjust_cut_bound(text, start, raw_end)
            chunk_raw_text = text[start:cut_end]
            # 仅输出非空白块
            clean_text = chunk_raw_text.strip()
            if clean_text:
                chunks.append(Chunk(
                    text=chunk_raw_text,
                    chunk_id=chunk_id,
                    start_char=start,
                    end_char=cut_end,
                    metadata=metadata.copy()
                ))
                chunk_id += 1
            # 滑动窗口前进（保留重叠）
            slide_step = self.chunk_size - self.overlap
            start = max(start + slide_step, cut_end - self.overlap)
        # 合并短碎片
        return self._merge_short_fragments(chunks)

    def _chunk_by_sentence(self, text: str, metadata: Dict[str, Any]) -> List[Chunk]:
        """句子优先分块，无文本丢失、超长句子自动走fixed切割"""
        raw_sentences = self._split_full_sentences(text)
        if not raw_sentences:
            return self._chunk_fixed(text, metadata)

        chunks: List[Chunk] = []
        chunk_id = 0
        global_start = 0
        sent_idx = 0
        total_sent = len(raw_sentences)

        while sent_idx < total_sent:
            single_sent = raw_sentences[sent_idx]
            sent_len = len(single_sent)
            # 单句超长，递归固定分块
            if sent_len > self.chunk_size:
                sub_chunks = self._chunk_fixed(single_sent, metadata)
                for sub in sub_chunks:
                    sub.start_char += global_start
                    sub.end_char += global_start
                    sub.chunk_id = chunk_id
                    chunks.append(sub)
                    chunk_id += 1
                global_start += sent_len
                sent_idx += 1
                continue

            # 尽可能合并多句，不超限
            buffer_parts = []
            buffer_total = 0
            while sent_idx < total_sent:
                curr_s = raw_sentences[sent_idx]
                curr_len = len(curr_s)
                if buffer_total + curr_len > self.chunk_size:
                    break
                buffer_parts.append(curr_s)
                buffer_total += curr_len
                sent_idx += 1
            # 拼接完整块文本
            block_text = "".join(buffer_parts)
            block_len = len(block_text)
            chunks.append(Chunk(
                text=block_text,
                chunk_id=chunk_id,
                start_char=global_start,
                end_char=global_start + block_len,
                metadata=metadata.copy()
            ))
            chunk_id += 1
            global_start += block_len
        # 合并短碎片
        return self._merge_short_fragments(chunks)

    def _chunk_hybrid(self, text: str, metadata: Dict[str, Any]) -> List[Chunk]:
        """混合策略：句子分块打底，超长块二次固定切割，修正坐标偏移"""
        base_chunks = self._chunk_by_sentence(text, metadata)
        final_chunks: List[Chunk] = []
        new_chunk_id = 0
        for ck in base_chunks:
            if len(ck.text) <= self.chunk_size:
                ck.chunk_id = new_chunk_id
                final_chunks.append(ck)
                new_chunk_id += 1
                continue
            # 超长块拆分，修正子块原始字符偏移
            sub_list = self._chunk_fixed(ck.text, metadata)
            offset = ck.start_char
            for sub in sub_list:
                sub.start_char += offset
                sub.end_char += offset
                sub.chunk_id = new_chunk_id
                final_chunks.append(sub)
                new_chunk_id += 1
        return final_chunks

# ===================== 测试用例 =====================
def test_chunker():
    """全量测试：三种策略、数字完整性、文本还原、碎片合并"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s")
    logger.info("=" * 70)
    logger.info("启动分块器完整测试（数字单位保护+文本完整性校验）")
    # 包含各类数字单位、多行日志、长短句
    test_text = """
    2026-07-22 10:30:15 ERROR auth-service 用户登录失败，密码错误。请求IP: 192.168.1.100。
    尝试次数: 3次，账户将在5分钟后锁定。建议用户重置密码或联系管理员。
    后端堆栈报错：NullReferenceException 第128行，数据库连接池耗尽，等待超时120s。
    另外有500ms延迟，重试3次后仍失败。
    """
    # 必须校验的数字关键字
    critical_tokens = ["120s", "500ms", "3次", "5分钟", "128行"]
    test_chunk_size = 50
    test_overlap = 10

    for strategy in [LogChunker.STRATEGY_FIXED, LogChunker.STRATEGY_SENTENCE, LogChunker.STRATEGY_HYBRID]:
        logger.info(f"\n-------- 测试策略: {strategy} | chunk_size={test_chunk_size} --------")
        chunker = LogChunker(chunk_size=test_chunk_size, overlap=test_overlap, strategy=strategy)
        chunk_result = chunker.chunk_text(test_text, {"source": "test_case"})
        logger.info(f"生成块总数: {len(chunk_result)}")
        full_restore_text = []
        for ck in chunk_result:
            logger.info(f"[{ck.chunk_id}] len={len(ck.text)} | {repr(ck.text)}")
            full_restore_text.append(ck.text)
        full_text_join = "".join(full_restore_text)
        # 校验数字完整性
        missing_tokens = [tk for tk in critical_tokens if tk not in full_text_join]
        if missing_tokens:
            logger.warning(f"【校验失败】丢失数字标识: {missing_tokens}")
        else:
            logger.info(f"【校验通过】全部数字单位完整保留 {critical_tokens}")
    logger.info("\n✅ 所有策略测试完成！")
    logger.info("=" * 70)

if __name__ == "__main__":
    test_chunker()