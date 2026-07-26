"""

提供两个能力：
1. load_testset()            -> 读取 testset.json，返回原始 dict
2. load_ragas_samples(filter)-> 返回 RAGAS SingleTurnSample 列表
   （retrieved_contexts 与 response 留空，由评测脚本在运行时填入）

可按 scenario / difficulty 过滤，便于按子集跑评估。

运行：
    cd backend
    python -m evaluation.testset_loader            # 打印测试集概览
    python -m evaluation.testset_loader --validate # 校验数据完整性
"""
import json
import os
import sys
from typing import List, Optional, Dict, Any

TESTSET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'testset.json')


def load_testset() -> Dict[str, Any]:
    """加载测试集 JSON"""
    with open(TESTSET_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_items(
    scenario: Optional[str] = None,
    difficulty: Optional[str] = None,
    ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    按条件加载测试集条目。

    Args:
        scenario: 仅保留该场景的条目（如 'error_diagnosis'）
        difficulty: 仅保留该难度的条目（'easy' / 'medium' / 'hard'）
        ids: 仅保留指定 ID 列表的条目

    Returns:
        条目列表，每条包含 id/scenario/difficulty/user_input/reference/
        reference_contexts/reference_log_ids/tags
    """
    data = load_testset()
    items = data['items']
    if scenario:
        items = [i for i in items if i['scenario'] == scenario]
    if difficulty:
        items = [i for i in items if i['difficulty'] == difficulty]
    if ids:
        id_set = set(ids)
        items = [i for i in items if i['id'] in id_set]
    return items


def to_ragas_sample(item: Dict[str, Any]):
    """
    把测试集条目转换为 RAGAS SingleTurnSample。

    注意：
    - retrieved_contexts 与 response 字段留空（或用占位），
      因为这两个字段是系统在运行时产出的，需要在评测时填入。
    - reference 用作 context_recall / context_precision 的 ground truth。
    """
    from ragas.dataset_schema import SingleTurnSample

    return SingleTurnSample(
        user_input=item['user_input'],
        retrieved_contexts=item.get('retrieved_contexts_placeholder', []),
        response=item.get('response_placeholder', ''),
        reference=item['reference'],
    )


def make_ragas_sample(
    item: Dict[str, Any],
    retrieved_contexts: List[str],
    response: str,
):
    """
    用系统实际产出的 retrieved_contexts 与 response 构造 RAGAS 样本。

    评测流程：
        1. 取 item['user_input']
        2. 调 QA pipeline 检索得到 retrieved_contexts、生成 response
        3. 用本函数打包成 SingleTurnSample
        4. 喂给 RAGAS metrics 评分
    """
    from ragas.dataset_schema import SingleTurnSample

    return SingleTurnSample(
        user_input=item['user_input'],
        retrieved_contexts=retrieved_contexts,
        response=response,
        reference=item['reference'],
    )


# ============================================================
# 校验 / 概览
# ============================================================

def validate() -> bool:
    """校验测试集完整性"""
    data = load_testset()
    items = data['items']
    ok = True
    print(f"测试集版本: {data['version']}")
    print(f"创建时间: {data['created_at']}")
    print(f"数据来源: {data['source_db']} / {data['source_table']}")
    print(f"总条目: {data['total']}")
    print(f"实际加载: {len(items)}")
    if data['total'] != len(items):
        print("  ✗ 总条目数与实际加载条目数不一致")
        ok = False

    # 必填字段检查
    required = ['id', 'scenario', 'difficulty', 'user_input', 'reference',
                'reference_contexts', 'reference_log_ids', 'tags']
    for it in items:
        for k in required:
            if k not in it:
                print(f"  ✗ {it.get('id', '?')} 缺少字段: {k}")
                ok = False
                break

    # 检查 reference_contexts 非空
    empty_ctx = [it['id'] for it in items if not it.get('reference_contexts')]
    if empty_ctx:
        print(f"  ✗ 以下条目 reference_contexts 为空: {empty_ctx}")
        ok = False

    # 检查 ID 唯一
    ids = [it['id'] for it in items]
    if len(ids) != len(set(ids)):
        dupes = [i for i in ids if ids.count(i) > 1]
        print(f"  ✗ ID 重复: {set(dupes)}")
        ok = False

    # 分布
    print(f"\n按场景: {data['stats']['by_scenario']}")
    print(f"按难度: {data['stats']['by_difficulty']}")

    # 覆盖检查
    services_seen = set()
    levels_seen = set()
    for it in items:
        for s in it['tags'].get('services', []):
            services_seen.add(s)
        for l in it['tags'].get('levels', []):
            levels_seen.add(l)
    print(f"\n覆盖服务: {sorted(services_seen)}")
    print(f"覆盖级别: {sorted(levels_seen)}")

    if ok:
        print("\n✅ 测试集校验通过")
    else:
        print("\n❌ 测试集校验失败")
    return ok


def overview():
    """打印测试集概览"""
    data = load_testset()
    print("=" * 60)
    print("RAGAS 测试集概览")
    print("=" * 60)
    print(f"文件: {TESTSET_PATH}")
    print(f"版本: {data['version']}  创建于: {data['created_at']}")
    print(f"来源: {data['source_db']} / {data['source_table']}")
    print(f"总数: {data['total']} 条问答对")
    print()
    print("按场景分布:")
    for k, v in data['stats']['by_scenario'].items():
        print(f"  {k:20s}: {v}")
    print()
    print("按难度分布:")
    for k, v in data['stats']['by_difficulty'].items():
        print(f"  {k:10s}: {v}")
    print()
    print("样例（第一条）:")
    it = data['items'][0]
    print(f"  id          : {it['id']}")
    print(f"  scenario    : {it['scenario']}")
    print(f"  difficulty  : {it['difficulty']}")
    print(f"  user_input  : {it['user_input']}")
    print(f"  reference   : {it['reference'][:80]}...")
    print(f"  ctx_count   : {it['context_count']}")
    print(f"  log_ids     : {it['reference_log_ids']}")
    print("=" * 60)


if __name__ == "__main__":
    if '--validate' in sys.argv:
        ok = validate()
        sys.exit(0 if ok else 1)
    overview()
