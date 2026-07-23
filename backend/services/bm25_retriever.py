"""
BM25 关键词检索服务
支持中英文混合分词 + 词干提取（Stemming）
"""
import logging
import pickle
import os
import re
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
        中英文混合分词 + 词干提取
        
        策略：
        1. 英文：正则提取 → 词干提取 → 转为小写
        2. 中文：jieba 分词
        3. 合并去重
        4. 过滤停用词
        """
        if not text or not text.strip():
            return []
        
        # 1. 转为小写
        text_lower = text.lower()
        
        # 2. 提取英文单词（字母，长度>=2）
        english_tokens = re.findall(r'[a-z]{2,}', text_lower)
        
        # 3. 词干提取（英文）
        english_tokens = [self.stemmer.stem(t) for t in english_tokens]
        
        # 4. 中文分词（使用 jieba）
        chinese_tokens = []
        if re.search(r'[\u4e00-\u9fff]', text):
            chinese_tokens = jieba.lcut(text)
            # 过滤：只保留中文词（长度>=2）
            chinese_tokens = [t for t in chinese_tokens if len(t) >= 2 and re.search(r'[\u4e00-\u9fff]', t)]
        
        # 5. 合并所有 token
        all_tokens = english_tokens + chinese_tokens
        
        # 6. 过滤停用词
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
        all_tokens = [t for t in all_tokens if t not in stopwords and len(t) >= 2]
        
        # 7. 去重（保持顺序）
        seen = set()
        unique_tokens = []
        for token in all_tokens:
            if token not in seen:
                seen.add(token)
                unique_tokens.append(token)
        
        return unique_tokens
    
    def build_index(self, corpus: List[Dict[str, Any]]) -> None:
        """构建 BM25 索引"""
        if not corpus:
            logger.warning("语料库为空")
            return
        
        logger.info(f"开始构建 BM25 索引，文档数: {len(corpus)}")
        
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
        
        # 分词
        logger.info(f"正在分词，共 {len(texts)} 条文本...")
        self.tokenized_corpus = [self._tokenize(text) for text in texts]
        
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
        
        # 构建 BM25 索引
        logger.info("构建 BM25 索引...")
        self.bm25 = BM25Okapi(self.tokenized_corpus)
        
        logger.info(f"✅ BM25 索引构建完成，文档数: {len(self.documents)}")
        
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