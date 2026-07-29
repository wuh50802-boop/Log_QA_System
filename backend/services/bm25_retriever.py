"""
BM25 关键词检索服务
支持中英文混合分词 + 词干提取（Stemming）
"""
import logging
import pickle
import os
import re
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

import jieba
from rank_bm25 import BM25Okapi
from nltk.stem import PorterStemmer

logger = logging.getLogger(__name__)


@dataclass
class BM25Result:
    """BM25 检索结果"""
    log_id: int
    payload: Dict[str, Any]
    score: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "log_id": self.log_id,
            "payload": self.payload,
            "score": round(self.score, 4),
        }


class BM25Retriever:
    """
    BM25 关键词检索器 - 中英文混合分词 + 词干提取
    """
    
    def __init__(
        
        self,
        corpus: Optional[List[Dict[str, Any]]] = None,
        cache_path: str = "./bm25_index.pkl",
        use_cache: bool = True,
    ):
         # 预加载 jieba
        jieba.initialize()
        self.corpus = corpus or []
        self.cache_path = cache_path
        self.use_cache = use_cache
        self.bm25 = None
        self.tokenized_corpus = []
        self.documents = []
        
        # 初始化词干提取器
        self._init_stemmer()
        
        if self.corpus:
            self.build_index(self.corpus)
        elif use_cache and os.path.exists(cache_path):
            self.load_index(cache_path)
    
    def _init_stemmer(self):
        """初始化词干提取器"""
        try:
            # 尝试下载 NLTK 数据（首次运行）
            import nltk
            try:
                nltk.data.find('tokenizers/punkt')
            except LookupError:
                nltk.download('punkt', quiet=True)
                nltk.download('stopwords', quiet=True)
        except Exception as e:
            logger.warning(f"NLTK 初始化失败: {e}")
        
        self.stemmer = PorterStemmer()
        logger.info("✅ Porter Stemmer 初始化完成")
    
    def _tokenize(self, text: str) -> List[str]:
        """
        中英文混合分词 + 词干提取 + 中英文映射 + 技术标识符提取

        策略：
        1. 快速检测文本语言类型
        2. 根据语言类型选择处理策略
        3. 中英文查询都能匹配英文日志
        4. 额外提取技术标识符（blk_123、0xff00、192.168.1.1、E1234 等）
           这类标识符含字母+数字+分隔符，传统 [a-z]+ 分词会丢失数字部分，
           导致搜 blk_123456 只能匹配 blk。标识符不做词干提取（是专有名词）。
        """
        if not text or not text.strip():
            return []

        text_lower = text.lower()
        all_tokens = []

        # 快速检测语言类型
        has_chinese = bool(re.search(r'[\u4e00-\u9fff]', text))
        has_english = bool(re.search(r'[a-z]', text_lower))

        # === 情况1：纯中文查询 ===
        if has_chinese and not has_english:
            # 中文分词
            chinese_tokens = jieba.lcut(text)
            chinese_tokens = [t for t in chinese_tokens if re.search(r'[\u4e00-\u9fff]', t) and len(t) >= 1]
            all_tokens.extend(chinese_tokens)

            # 中英文映射（为每个中文词添加英文同义词）
            for cn_token in chinese_tokens:
                all_tokens.extend(self._map_chinese_to_english(cn_token))

        # === 情况2：纯英文查询 ===
        elif has_english and not has_chinese:
            # 提取英文单词
            english_tokens = re.findall(r'[a-z]{2,}', text_lower)
            # 词干提取
            english_tokens = [self.stemmer.stem(t) for t in english_tokens if len(t) >= 2]
            all_tokens.extend(english_tokens)

        # === 情况3：中英文混合查询 ===
        else:
            # 处理英文部分
            if has_english:
                english_tokens = re.findall(r'[a-z]{2,}', text_lower)
                english_tokens = [self.stemmer.stem(t) for t in english_tokens if len(t) >= 2]
                all_tokens.extend(english_tokens)

            # 处理中文部分
            if has_chinese:
                chinese_tokens = jieba.lcut(text)
                chinese_tokens = [t for t in chinese_tokens if re.search(r'[\u4e00-\u9fff]', t) and len(t) >= 1]
                all_tokens.extend(chinese_tokens)

                # 中英文映射
                for cn_token in chinese_tokens:
                    all_tokens.extend(self._map_chinese_to_english(cn_token))

        # === 提取技术标识符（所有情况都执行） ===
        # 匹配含字母+数字的标识符（如 blk_123456、0xff00ab、192.168.1.1、E1234、blk_-1234567）
        # 不做词干提取：标识符是专有名词，stem 会破坏其精确匹配语义
        all_tokens.extend(self._extract_identifiers(text_lower))

        # 过滤停用词
        stopwords = self._get_stopwords()
        all_tokens = [t for t in all_tokens if t not in stopwords and len(t) >= 2]

        # 去重（保持顺序）
        seen = set()
        unique_tokens = []
        for token in all_tokens:
            if token not in seen:
                seen.add(token)
                unique_tokens.append(token)

        return unique_tokens

    # 技术标识符正则：字母开头，后跟字母/数字/下划线/连字符/点，且至少包含一个数字
    # 例：blk_123456、0xff00ab、192.168.1.1、E1234、blk_-1234567、fs namesystem
    _IDENTIFIER_PATTERN = re.compile(
        r'[a-z0-9][a-z0-9_.-]*\d[a-z0-9_.-]*',
        re.IGNORECASE
    )

    def _extract_identifiers(self, text_lower: str) -> List[str]:
        """
        提取技术标识符：含字母+数字+分隔符的连续串。

        与纯字母单词提取互补：
        - [a-z]{2,}  → 'blk_123456' 得到 'blk'（数字丢失）
        - 本方法     → 'blk_123456' 得到 'blk_123456'（完整保留）

        不做词干提取，因为 blk_123 和 blk_456 是不同的 block ID。
        """
        raw_matches = self._IDENTIFIER_PATTERN.findall(text_lower)
        identifiers = []
        for match in raw_matches:
            # 去掉首尾的分隔符（_.-）避免 token 边界不一致
            cleaned = match.strip('._-')
            # 至少 3 字符且包含数字（过滤掉纯字母单词，那些已由 [a-z]+ 处理）
            if len(cleaned) >= 3 and any(c.isdigit() for c in cleaned):
                identifiers.append(cleaned)
        return identifiers

    def _map_chinese_to_english(self, chinese_word: str) -> List[str]:
        """
        将中文词映射为英文同义词（包含词干形式）
        
        Args:
            chinese_word: 中文词
        
        Returns:
            英文同义词列表（包含原词和词干形式）
        """
        result = []
        
        # 中英文映射字典
        cn_en_map = {
            # 技术术语
            '数据库': 'database',
            '连接': 'connection',
            '超时': 'timeout',
            '失败': 'failure',
            '错误': 'error',
            '异常': 'exception',
            '服务': 'service',
            '登录': 'login',
            '用户': 'user',
            '认证': 'authentication auth',
            '授权': 'authorization',
            '权限': 'permission',
            '缓存': 'cache',
            '内存': 'memory',
            '磁盘': 'disk',
            '网络': 'network',
            '请求': 'request',
            '响应': 'response',
            '重试': 'retry',
            '空指针': 'nullpointer null',
            '文件': 'file',
            '未找到': 'notfound',
            '配置': 'config configuration',
            '参数': 'parameter param',
            '无效': 'invalid',
            '有效': 'valid',
            '警告': 'warning',
            '信息': 'info',
            '调试': 'debug',
            '追踪': 'trace',
            
            # 日志相关
            '日志': 'log',
            '记录': 'record',
            '消息': 'message',
            '堆栈': 'stack',
            '跟踪': 'trace',
            '调用': 'call',
            '方法': 'method',
            '函数': 'function func',
            '类': 'class',
            '对象': 'object',
            '实例': 'instance',
            '线程': 'thread',
            '进程': 'process',
            
            # 系统相关
            '系统': 'system',
            '应用': 'application app',
            '程序': 'program',
            '模块': 'module',
            '组件': 'component',
            '接口': 'interface',
            '端点': 'endpoint',
            '路径': 'path',
            '路由': 'route',
            '端口': 'port',
            '主机': 'host',
            '地址': 'address',
            
            # 操作相关
            '添加': 'add',
            '删除': 'delete del',
            '更新': 'update',
            '修改': 'modify',
            '创建': 'create',
            '读取': 'read',
            '写入': 'write',
            '执行': 'execute exec',
            '运行': 'run',
            '启动': 'start',
            '停止': 'stop',
            '重启': 'restart',
            
            # 状态相关
            '成功': 'success',
            '完成': 'complete',
            '处理中': 'processing',
            '待处理': 'pending',
            '阻塞': 'block',
            '死锁': 'deadlock',
            '溢出': 'overflow',
            '泄漏': 'leak',
            '损坏': 'corrupt',
            '丢失': 'lost',
            
            # 业务相关
            '订单': 'order',
            '支付': 'payment',
            '账单': 'bill',
            '账户': 'account',
            '余额': 'balance',
            '交易': 'transaction',
            '商品': 'product',
            '库存': 'inventory',
            '价格': 'price',
            '数量': 'quantity',
            '管理员': 'admin',
            
            # 数据库相关
            '查询': 'query',
            '插入': 'insert',
            '删除': 'delete',
            '更新': 'update',
            '事务': 'transaction',
            '索引': 'index',
            '表': 'table',
            '字段': 'field column',
            '主键': 'primarykey pk',
            '外键': 'foreignkey fk',
            '连接池': 'connectionpool pool',
            
            # 网络相关
            '超时': 'timeout',
            '重试': 'retry',
            '断路器': 'circuitbreaker',
            '限流': 'ratelimit',
            '降级': 'degrade',
            '熔断': 'fuse',
        }
        
        # 1. 精确匹配
        if chinese_word in cn_en_map:
            en_terms = cn_en_map[chinese_word].split()
            for en_term in en_terms:
                if en_term:
                    result.append(en_term)
                    # 添加词干形式（仅对英文词）
                    if re.match(r'^[a-z]+$', en_term):
                        result.append(self.stemmer.stem(en_term))
        
        # 2. 部分匹配（处理复合词，如 "数据库连接"）
        else:
            for cn_key, en_value in cn_en_map.items():
                if cn_key in chinese_word:
                    en_terms = en_value.split()
                    for en_term in en_terms:
                        if en_term:
                            result.append(en_term)
                            if re.match(r'^[a-z]+$', en_term):
                                result.append(self.stemmer.stem(en_term))
        
        return result
    
    def _get_stopwords(self) -> set:
        """
        获取停用词集合（缓存为类属性，避免重复创建）
        """
        if hasattr(self, '_stopwords_cache'):
            return self._stopwords_cache
        
        stopwords = {
            # 英文停用词
            'a', 'an', 'the', 'of', 'to', 'for', 'on', 'in', 'at', 'by',
            'with', 'without', 'and', 'or', 'but', 'not', 'is', 'are',
            'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had',
            'do', 'does', 'did', 'will', 'would', 'could', 'should',
            'may', 'might', 'must', 'shall', 'then', 'than', 'so', 'too',
            'very', 'just', 'like', 'some', 'any', 'more', 'most', 'such',
            'from', 'into', 'over', 'under', 'above', 'below',
            'via', 'per', 'among', 'between', 'during', 'without', 'within',
            # 中文停用词
            '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都',
            '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会',
            '着', '没有', '看', '好', '自己', '这', '那', '它', '他', '她',
            '但', '而', '与', '或', '且', '并', '等', '地', '得', '着',
        }
        
        self._stopwords_cache = stopwords
        return stopwords
        
    def build_index(self, corpus: List[Dict[str, Any]]) -> None:
        """构建 BM25 索引"""
        if not corpus:
            logger.warning("语料库为空")
            return

        total = len(corpus)
        logger.info(f"开始构建 BM25 索引，文档数: {total}")

        # ---- 阶段 1: 文档预处理（拼接文本） ----
        t0 = time.time()
        self.documents = []
        texts = []

        for doc in corpus:
            # 获取文本内容
            text = doc.get('chunk_text', '') or doc.get('message', '')
            if not text:
                continue

            # 添加服务名和级别增强匹配
            text_parts = [text]
            if doc.get('service'):
                text_parts.append(doc['service'])
            if doc.get('level'):
                text_parts.append(doc['level'])
            if doc.get('source'):
                text_parts.append(doc['source'])

            full_text = ' '.join(text_parts)

            self.documents.append({
                'log_id': doc.get('log_id'),
                'payload': doc,
                'text': full_text,
            })
            texts.append(full_text)

        if not texts:
            logger.warning("没有有效的文本内容")
            return

        logger.info(f"✅ 阶段 1/3 文档预处理完成: {len(texts)} 条，耗时 {time.time() - t0:.1f}s")

        # ---- 阶段 2: 分词（最耗时，带进度） ----
        logger.info(f"⏳ 阶段 2/3 正在分词，共 {len(texts)} 条文本...")
        t1 = time.time()
        self.tokenized_corpus = []
        progress_interval = max(100000, len(texts) // 20)  # 至少 10 万条打一次，最多 20 次
        for i, text in enumerate(texts):
            self.tokenized_corpus.append(self._tokenize(text))
            if (i + 1) % progress_interval == 0 or (i + 1) == len(texts):
                elapsed = time.time() - t1
                speed = (i + 1) / elapsed if elapsed > 0 else 0
                pct = (i + 1) / len(texts) * 100
                # 估算剩余时间
                eta = (len(texts) - i - 1) / speed if speed > 0 else 0
                eta_str = f"{eta:.0f}s" if eta < 60 else f"{eta/60:.1f}m"
                logger.info(
                    f"   分词进度: {i+1}/{len(texts)} ({pct:.1f}%) | "
                    f"速度: {speed:.0f} docs/s | 剩余: {eta_str}"
                )

        logger.info(f"✅ 阶段 2/3 分词完成，耗时 {time.time() - t1:.1f}s")

        # 统计
        all_words = set()
        for tokens in self.tokenized_corpus:
            all_words.update(tokens)
        logger.info(f"   - 总词汇数: {len(all_words)}")
        logger.info(f"   - 平均文档词数: {sum(len(t) for t in self.tokenized_corpus) / len(self.tokenized_corpus):.1f}")

        # 显示样本分词结果（调试）
        if self.tokenized_corpus:
            sample_tokens = self.tokenized_corpus[0][:10]
            logger.info(f"   - 样本分词: {sample_tokens}")

        # ---- 阶段 3: 构建 BM25Okapi 索引 ----
        logger.info("⏳ 阶段 3/3 构建 BM25Okapi 索引...")
        t2 = time.time()
        self.bm25 = BM25Okapi(self.tokenized_corpus)
        logger.info(f"✅ 阶段 3/3 BM25Okapi 构建完成，耗时 {time.time() - t2:.1f}s")

        logger.info(f"🎉 BM25 索引构建完成，文档数: {len(self.documents)}，总耗时 {time.time() - t0:.1f}s")
        
        if self.use_cache and self.cache_path:
            self.save_index(self.cache_path)
    
    def search(
        self,
        query: str,
        top_k: int = 10,
        filter_level: Optional[str] = None,
        filter_service: Optional[str] = None,
        filter_source: Optional[str] = None,
    ) -> List[BM25Result]:
        """执行 BM25 检索"""
        if not query or not query.strip():
            return []
        
        if not self.bm25:
            logger.warning("BM25 索引未构建")
            return []
        
        try:
            # 分词查询（同样应用词干提取）
            tokenized_query = self._tokenize(query)
            
            if not tokenized_query:
                logger.warning(f"查询分词后为空: {query}")
                return []
            
            logger.debug(f"查询分词: {tokenized_query}")
            
            # 计算分数
            scores = self.bm25.get_scores(tokenized_query)
            
            # 获取 Top-K
            sorted_indices = sorted(
                range(len(scores)),
                key=lambda i: scores[i],
                reverse=True
            )[:top_k * 2]  # 多取一些用于过滤
            
            results = []
            for idx in sorted_indices:
                score = scores[idx]
                if score == 0:
                    continue
                
                doc = self.documents[idx]
                payload = doc['payload']
                
                # 应用过滤
                if filter_level and payload.get('level') != filter_level:
                    continue
                if filter_service and payload.get('service') != filter_service:
                    continue
                if filter_source and payload.get('source') != filter_source:
                    continue
                
                results.append(BM25Result(
                    log_id=doc['log_id'],
                    payload=payload,
                    score=score,
                ))
                
                if len(results) >= top_k:
                    break
            
            logger.info(f"BM25 检索完成，查询: '{query}'，返回 {len(results)} 条结果")
            return results
            
        except Exception as e:
            logger.error(f"BM25 检索失败: {e}")
            return []
    
    def search_with_filter(
        self,
        query: str,
        top_k: int = 10,
        filter_params: Optional[Dict[str, Any]] = None,
    ) -> List[BM25Result]:
        """带过滤条件的检索"""
        filter_level = filter_params.get('level') if filter_params else None
        filter_service = filter_params.get('service') if filter_params else None
        filter_source = filter_params.get('source') if filter_params else None
        
        return self.search(
            query=query,
            top_k=top_k,
            filter_level=filter_level,
            filter_service=filter_service,
            filter_source=filter_source,
        )
    
    def save_index(self, path: str) -> None:
        """保存索引"""
        try:
            data = {
                'documents': self.documents,
                'tokenized_corpus': self.tokenized_corpus,
                'bm25': self.bm25,
            }
            with open(path, 'wb') as f:
                pickle.dump(data, f)
            logger.info(f"✅ BM25 索引已保存到: {path}")
        except Exception as e:
            logger.error(f"保存失败: {e}")
    
    def load_index(self, path: str) -> bool:
        """加载索引"""
        if not os.path.exists(path):
            return False
        
        try:
            with open(path, 'rb') as f:
                data = pickle.load(f)
            self.documents = data['documents']
            self.tokenized_corpus = data['tokenized_corpus']
            self.bm25 = data['bm25']
            logger.info(f"✅ BM25 索引已加载: {len(self.documents)} 条文档")
            return True
        except Exception as e:
            logger.error(f"加载失败: {e}")
            return False
    
    def get_document_count(self) -> int:
        return len(self.documents)


# ============ 单例 ============
_bm25_retriever = None


def get_bm25_retriever(
    corpus: Optional[List[Dict[str, Any]]] = None,
    cache_path: str = "./bm25_index.pkl",
) -> BM25Retriever:
    global _bm25_retriever
    if _bm25_retriever is None:
        _bm25_retriever = BM25Retriever(
            corpus=corpus,
            cache_path=cache_path,
            use_cache=True,
        )
    return _bm25_retriever


def bm25_search(
    query: str,
    top_k: int = 10,
    level: Optional[str] = None,
    service: Optional[str] = None,
    source: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """便捷检索函数"""
    retriever = get_bm25_retriever()
    results = retriever.search(
        query=query,
        top_k=top_k,
        filter_level=level,
        filter_service=service,
        filter_source=source,
    )
    return [r.to_dict() for r in results]