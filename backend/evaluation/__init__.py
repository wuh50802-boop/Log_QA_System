"""
RAGAS 评估模块

使用 RAGAS 框架对日志问答系统进行量化评估。
评估维度：
- faithfulness: 答案是否忠实于检索到的上下文（无幻觉）
- answer_relevancy: 答案与问题的相关性
- context_precision: 检索上下文的精确度
- context_recall: 检索上下文的召回率

评估器配置：
- Evaluator LLM: DeepSeek（复用项目 LLM）
- Evaluator Embeddings: BGE bge-base-zh-v1.5（复用项目 embedder）
"""
