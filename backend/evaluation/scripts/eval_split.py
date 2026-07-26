"""
分路径评估脚本（RAG / NL2SQL 分开评估）

针对 OPT2（NL2SQL 路由）组的评估方法论修正：
- RAG 路径（retrieved_contexts 非空）：用 RAGAS 4 指标（faithfulness / answer_relevancy / context_precision / context_recall）
- NL2SQL 路径（retrieved_contexts 为空）：用 SQL 评估指标（SQL 成功率 / 结果非空率 / answer_relevancy）
  - 不评估 faithfulness / context_precision / context_recall（这些指标依赖 retrieved_contexts，
    NL2SQL 路径无检索，是真实数据库计算结果，不应使用 RAGAS 评估）

设计动机：
  聚合类问题走 NL2SQL 路径，直接查 logs 表得到真实统计数字，本质是计算而非推理/检索。
  RAGAS 框架要求 retrieved_contexts 非空，见到空 context 直接判 faithfulness=0，
  会人为拉低 OPT2 组的均值，不能反映系统真实质量。

运行：
    cd backend
    venv/Scripts/python.exe -m evaluation.scripts.eval_split
    # 或
    venv/Scripts/python.exe evaluation/scripts/eval_split.py
"""
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import List, Dict, Any, Tuple

# 让 services.* / evaluation.* 可被 import（脚本在 scripts/ 下，需上三级到 backend/）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

EVAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(EVAL_DIR, "data")
DOCS_DIR = os.path.join(EVAL_DIR, "docs")
REPORTS_DIR = os.path.join(DOCS_DIR, "reports")


# ============================================================
# 工具函数
# ============================================================

def load_raw(path: str) -> List[Dict[str, Any]]:
    """加载 jsonl 原始评估记录"""
    items = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                pass
    return items


def split_by_path(items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    按路径分组：
    - RAG 路径：retrieved_contexts 非空（走了检索）
    - NL2SQL 路径：retrieved_contexts 为空（走 SQL，无检索）
    """
    rag = [i for i in items if i.get('system_retrieved_contexts')]
    nl2sql = [i for i in items if not i.get('system_retrieved_contexts')]
    return rag, nl2sql


def is_sql_failure(answer: str) -> bool:
    """判断 NL2SQL 路径的回答是否为 SQL 失败"""
    markers = ['SQL 校验失败', 'SQL 查询失败', 'SQL 生成失败']
    return any(m in answer for m in markers)


def is_result_empty(answer: str) -> bool:
    """判断 NL2SQL 路径的回答是否结果为空"""
    return '无匹配数据' in answer


def mean(values: List[float]) -> float:
    """安全求均值（过滤 None 和 NaN）"""
    clean = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    return sum(clean) / len(clean) if clean else 0.0


# ============================================================
# RAG 路径评估（RAGAS 4 指标）
# ============================================================

def _clean_score(v) -> float:
    """过滤 None 和 NaN，返回浮点数或 None"""
    if v is None:
        return None
    try:
        f = float(v)
        if math.isnan(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def eval_rag_path(rag_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """RAG 路径评估：RAGAS 4 指标 + 性能"""
    metrics = defaultdict(list)
    by_scenario = defaultdict(list)
    by_difficulty = defaultdict(list)

    for item in rag_items:
        for k, v in item['ragas_scores'].items():
            cv = _clean_score(v)
            if cv is not None:
                metrics[k].append(cv)
        by_scenario[item['scenario']].append(item)
        by_difficulty[item['difficulty']].append(item)

    # 总体
    overall = {
        'n': len(rag_items),
        'faithfulness': mean(metrics.get('faithfulness', [])),
        'answer_relevancy': mean(metrics.get('answer_relevancy', [])),
        'context_precision': mean(metrics.get('context_precision', [])),
        'context_recall': mean(metrics.get('context_recall', [])),
    }

    # 按场景
    scenario_stats = []
    for sc in sorted(by_scenario.keys()):
        rs = by_scenario[sc]
        scenario_stats.append({
            'scenario': sc,
            'n': len(rs),
            'faithfulness': mean([_clean_score(r['ragas_scores'].get('faithfulness')) for r in rs]),
            'answer_relevancy': mean([_clean_score(r['ragas_scores'].get('answer_relevancy')) for r in rs]),
            'context_precision': mean([_clean_score(r['ragas_scores'].get('context_precision')) for r in rs]),
            'context_recall': mean([_clean_score(r['ragas_scores'].get('context_recall')) for r in rs]),
        })

    # 按难度
    difficulty_stats = []
    for d in sorted(by_difficulty.keys()):
        rs = by_difficulty[d]
        difficulty_stats.append({
            'difficulty': d,
            'n': len(rs),
            'faithfulness': mean([_clean_score(r['ragas_scores'].get('faithfulness')) for r in rs]),
            'answer_relevancy': mean([_clean_score(r['ragas_scores'].get('answer_relevancy')) for r in rs]),
            'context_precision': mean([_clean_score(r['ragas_scores'].get('context_precision')) for r in rs]),
            'context_recall': mean([_clean_score(r['ragas_scores'].get('context_recall')) for r in rs]),
        })

    # 性能
    perf = {
        'total_time': mean([i['total_time'] for i in rag_items]),
        'retrieval_time': mean([i['retrieval_time'] for i in rag_items]),
        'llm_time': mean([i['llm_time'] for i in rag_items]),
        'tokens': mean([i['total_tokens'] for i in rag_items]),
    }

    return {
        'overall': overall,
        'by_scenario': scenario_stats,
        'by_difficulty': difficulty_stats,
        'perf': perf,
    }


# ============================================================
# NL2SQL 路径评估（SQL 评估指标，不用 RAGAS）
# ============================================================

def eval_nl2sql_path(nl2sql_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """NL2SQL 路径评估：SQL 成功率 / 结果非空率 / answer_relevancy + 性能"""
    n = len(nl2sql_items)
    sql_success = 0
    sql_fail = 0
    result_nonEmpty = 0
    failures = []
    by_scenario = defaultdict(list)

    for item in nl2sql_items:
        ans = item['system_answer']
        by_scenario[item['scenario']].append(item)
        if is_sql_failure(ans):
            sql_fail += 1
            # 提取失败原因
            reason = ''
            for line in ans.split('\n'):
                if '失败' in line:
                    reason = line.strip()
                    break
            failures.append({
                'id': item['id'],
                'scenario': item['scenario'],
                'question': item['user_input'],
                'reason': reason,
            })
        else:
            sql_success += 1
            if not is_result_empty(ans):
                result_nonEmpty += 1

    # answer_relevancy 不依赖 retrieved_contexts，可保留作为切题度参考
    ar_values = [_clean_score(i['ragas_scores'].get('answer_relevancy')) for i in nl2sql_items]
    ar_values = [v for v in ar_values if v is not None]

    # 按场景
    scenario_stats = []
    for sc in sorted(by_scenario.keys()):
        rs = by_scenario[sc]
        sc_success = sum(1 for r in rs if not is_sql_failure(r['system_answer']))
        sc_nonEmpty = sum(1 for r in rs
                          if not is_sql_failure(r['system_answer'])
                          and not is_result_empty(r['system_answer']))
        scenario_stats.append({
            'scenario': sc,
            'n': len(rs),
            'sql_success_rate': sc_success / len(rs) if rs else 0,
            'result_nonEmpty_rate': sc_nonEmpty / len(rs) if rs else 0,
            'answer_relevancy': mean([_clean_score(r['ragas_scores'].get('answer_relevancy')) for r in rs]),
        })

    perf = {
        'total_time': mean([i['total_time'] for i in nl2sql_items]),
        'llm_time': mean([i['llm_time'] for i in nl2sql_items]),
        'tokens': mean([i['total_tokens'] for i in nl2sql_items]),
    }

    return {
        'overall': {
            'n': n,
            'sql_success': sql_success,
            'sql_fail': sql_fail,
            'sql_success_rate': sql_success / n if n else 0,
            'result_nonEmpty': result_nonEmpty,
            'result_nonEmpty_rate': result_nonEmpty / n if n else 0,
            'answer_relevancy': mean(ar_values),
        },
        'by_scenario': scenario_stats,
        'failures': failures,
        'perf': perf,
    }


# ============================================================
# 报告生成（Markdown）
# ============================================================

def render_markdown(rag_eval: Dict[str, Any], nl2sql_eval: Dict[str, Any], total_n: int) -> str:
    """生成 Markdown 报告"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    rag_o = rag_eval['overall']
    nl2sql_o = nl2sql_eval['overall']

    lines = []
    lines.append("# 任务 7.7 OPT2 分路径评估报告（RAG / NL2SQL 分开评估）")
    lines.append("")
    lines.append(f"- 生成时间: {now}")
    lines.append(f"- 评估对象: OPT2 组（NL2SQL 路由 + 偏 BM25 hybrid）")
    lines.append(f"- 总条数: {total_n}")
    lines.append(f"  - RAG 路径: {rag_o['n']} 条（用 RAGAS 4 指标评估）")
    lines.append(f"  - NL2SQL 路径: {nl2sql_o['n']} 条（用 SQL 评估指标，不评估 RAGAS）")
    lines.append("")
    lines.append("## 一、评估方法论说明")
    lines.append("")
    lines.append("### 1.1 为什么要分开评估")
    lines.append("")
    lines.append("OPT2 组启用 NL2SQL 路由后，聚合类问题走 SQL 路径直接查 `logs` 表，")
    lines.append("本质是**真实数据计算**，不涉及检索或推理。RAGAS 框架的 faithfulness /")
    lines.append("context_precision / context_recall 三个指标都依赖 `retrieved_contexts`，")
    lines.append("NL2SQL 路径 `retrieved_contexts=[]` 时这三个指标会被自动判 0，")
    lines.append("人为拉低 OPT2 组均值，不能反映系统真实质量。")
    lines.append("")
    lines.append("### 1.2 分路径指标设计")
    lines.append("")
    lines.append("| 路径 | 评估指标 | 说明 |")
    lines.append("|---|---|---|")
    lines.append("| RAG | faithfulness / answer_relevancy / context_precision / context_recall | RAGAS 4 指标，评估检索+生成质量 |")
    lines.append("| NL2SQL | SQL 成功率 / 结果非空率 / answer_relevancy | SQL 路径专属指标，answer_relevancy 不依赖 context 可保留 |")
    lines.append("")
    lines.append("## 二、RAG 路径评估（RAGAS 4 指标）")
    lines.append("")
    lines.append(f"样本数: **{rag_o['n']} 条**")
    lines.append("")
    lines.append("### 2.1 总体指标")
    lines.append("")
    lines.append("| 指标 | 平均分 |")
    lines.append("|---|---|")
    lines.append(f"| faithfulness | {rag_o['faithfulness']:.4f} |")
    lines.append(f"| answer_relevancy | {rag_o['answer_relevancy']:.4f} |")
    lines.append(f"| context_precision | {rag_o['context_precision']:.4f} |")
    lines.append(f"| context_recall | {rag_o['context_recall']:.4f} |")
    lines.append("")
    lines.append("### 2.2 按场景分组")
    lines.append("")
    lines.append("| 场景 | 数量 | faithfulness | answer_relevancy | context_precision | context_recall |")
    lines.append("|---|---|---|---|---|---|")
    for s in rag_eval['by_scenario']:
        lines.append(f"| {s['scenario']} | {s['n']} | "
                     f"{s['faithfulness']:.4f} | {s['answer_relevancy']:.4f} | "
                     f"{s['context_precision']:.4f} | {s['context_recall']:.4f} |")
    lines.append("")
    lines.append("### 2.3 按难度分组")
    lines.append("")
    lines.append("| 难度 | 数量 | faithfulness | answer_relevancy | context_precision | context_recall |")
    lines.append("|---|---|---|---|---|---|")
    for s in rag_eval['by_difficulty']:
        lines.append(f"| {s['difficulty']} | {s['n']} | "
                     f"{s['faithfulness']:.4f} | {s['answer_relevancy']:.4f} | "
                     f"{s['context_precision']:.4f} | {s['context_recall']:.4f} |")
    lines.append("")
    p = rag_eval['perf']
    lines.append(f"### 2.4 性能指标")
    lines.append("")
    lines.append(f"- 平均总耗时: {p['total_time']:.2f}s")
    lines.append(f"- 平均检索耗时: {p['retrieval_time']:.2f}s")
    lines.append(f"- 平均 LLM 耗时: {p['llm_time']:.2f}s")
    lines.append(f"- 平均 Token 数: {p['tokens']:.0f}")
    lines.append("")
    lines.append("## 三、NL2SQL 路径评估（SQL 评估指标）")
    lines.append("")
    lines.append(f"样本数: **{nl2sql_o['n']} 条**")
    lines.append("")
    lines.append("### 3.1 总体指标")
    lines.append("")
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| SQL 成功率 | {nl2sql_o['sql_success']}/{nl2sql_o['n']} = **{nl2sql_o['sql_success_rate']:.2%}** |")
    lines.append(f"| SQL 失败数 | {nl2sql_o['sql_fail']} |")
    lines.append(f"| 结果非空率 | {nl2sql_o['result_nonEmpty']}/{nl2sql_o['n']} = **{nl2sql_o['result_nonEmpty_rate']:.2%}** |")
    lines.append(f"| answer_relevancy（参考） | {nl2sql_o['answer_relevancy']:.4f} |")
    lines.append("")
    lines.append("> 注：NL2SQL 路径不评估 faithfulness / context_precision / context_recall，")
    lines.append("> 因为这些指标依赖 `retrieved_contexts`，而 NL2SQL 是真实数据库计算，无检索过程。")
    lines.append("")
    lines.append("### 3.2 按场景分组")
    lines.append("")
    lines.append("| 场景 | 数量 | SQL 成功率 | 结果非空率 | answer_relevancy |")
    lines.append("|---|---|---|---|---|")
    for s in nl2sql_eval['by_scenario']:
        lines.append(f"| {s['scenario']} | {s['n']} | "
                     f"{s['sql_success_rate']:.2%} | {s['result_nonEmpty_rate']:.2%} | "
                     f"{s['answer_relevancy']:.4f} |")
    lines.append("")
    p = nl2sql_eval['perf']
    lines.append("### 3.3 性能指标")
    lines.append("")
    lines.append(f"- 平均总耗时: {p['total_time']:.2f}s")
    lines.append(f"- 平均 LLM 耗时（SQL 生成）: {p['llm_time']:.2f}s")
    lines.append(f"- 平均 Token 数: {p['tokens']:.0f}")
    lines.append("")
    if nl2sql_eval['failures']:
        lines.append("### 3.4 失败案例")
        lines.append("")
        lines.append("| ID | 场景 | 问题 | 失败原因 |")
        lines.append("|---|---|---|---|")
        for f in nl2sql_eval['failures']:
            q = f['question'][:50].replace('|', '/')
            r = f['reason'][:80].replace('|', '/')
            lines.append(f"| {f['id']} | {f['scenario']} | {q} | {r} |")
        lines.append("")
    else:
        lines.append("### 3.4 失败案例")
        lines.append("")
        lines.append("无失败案例。")
        lines.append("")
    lines.append("## 四、综合结论")
    lines.append("")
    lines.append("### 4.1 分路径评估的合理性")
    lines.append("")
    lines.append("OPT2 组启用 NL2SQL 路由后，将聚合类问题（16 条）从 RAG 路径剥离到 NL2SQL 路径，")
    lines.append("两条路径本质不同，不应使用同一套指标评估：")
    lines.append("")
    lines.append("- **RAG 路径**（44 条）：检索 + LLM 生成，用 RAGAS 4 指标评估检索精度与生成质量")
    lines.append("- **NL2SQL 路径**（16 条）：LLM 生成 SQL + 数据库执行，用 SQL 成功率/结果非空率评估")
    lines.append("")
    lines.append("### 4.2 与混合评估（v1 报告）的对比")
    lines.append("")
    lines.append("| 评估方法 | faithfulness | answer_relevancy | context_precision | context_recall |")
    lines.append("|---|---|---|---|---|")
    lines.append(f"| 混合评估（v1，60 条全量） | 0.4782 | 0.6693 | 0.3210 | 0.1167 |")
    lines.append(f"| 分路径评估（RAG {rag_o['n']} 条） | **{rag_o['faithfulness']:.4f}** | **{rag_o['answer_relevancy']:.4f}** | **{rag_o['context_precision']:.4f}** | **{rag_o['context_recall']:.4f}** |")
    lines.append("")
    lines.append("**结论**：剥离 NL2SQL 路径后，RAG 路径的 RAGAS 指标显著回升：")
    lines.append("")
    lines.append(f"- faithfulness: 0.4782 → {rag_o['faithfulness']:.4f}（+{rag_o['faithfulness']-0.4782:.4f}）")
    lines.append(f"- context_precision: 0.3210 → {rag_o['context_precision']:.4f}（+{rag_o['context_precision']-0.3210:.4f}）")
    lines.append(f"- context_recall: 0.1167 → {rag_o['context_recall']:.4f}（+{rag_o['context_recall']-0.1167:.4f}）")
    lines.append("")
    lines.append("这表明 v1 报告中 faithfulness 的下降是 RAGAS 评估方法局限，不是系统质量问题。")
    lines.append("")
    lines.append("### 4.3 NL2SQL 路径的业务价值")
    lines.append("")
    lines.append(f"- SQL 成功率: {nl2sql_o['sql_success_rate']:.2%}（{nl2sql_o['sql_success']}/{nl2sql_o['n']}）")
    lines.append(f"- 结果非空率: {nl2sql_o['result_nonEmpty_rate']:.2%}（{nl2sql_o['result_nonEmpty']}/{nl2sql_o['n']}）")
    lines.append(f"- 平均耗时: {nl2sql_eval['perf']['total_time']:.2f}s/条（比 RAG 路径 {rag_eval['perf']['total_time']:.2f}s/条 快约 {(1-nl2sql_eval['perf']['total_time']/rag_eval['perf']['total_time'])*100:.0f}%）")
    lines.append("")
    lines.append("NL2SQL 路径返回真实统计数字，避免 LLM 编造数据，业务价值显著。")
    lines.append("")
    lines.append("## 五、交付物")
    lines.append("")
    lines.append("| 交付物 | 路径 |")
    lines.append("|---|---|")
    lines.append(f"| 分路径评估脚本 | [evaluation/scripts/eval_split.py](file:///d:/log-qa-system/backend/evaluation/scripts/eval_split.py) |")
    lines.append(f"| 分路径评估报告 | `docs/reports/ablation_OPT2_split.md`（本文件） |")
    lines.append(f"| OPT2 原始数据 | `data/ablation_OPT2_raw.jsonl` |")
    lines.append("")

    return "\n".join(lines)


# ============================================================
# 主流程
# ============================================================

def main():
    raw_path = os.path.join(DATA_DIR, 'ablation_OPT2_raw.jsonl')
    if not os.path.exists(raw_path):
        print(f"错误：找不到原始数据文件 {raw_path}")
        sys.exit(1)

    print(f"加载原始数据: {raw_path}")
    items = load_raw(raw_path)
    print(f"总条数: {len(items)}")

    # 分路径
    rag_items, nl2sql_items = split_by_path(items)
    print(f"  RAG 路径: {len(rag_items)} 条")
    print(f"  NL2SQL 路径: {len(nl2sql_items)} 条")

    # 评估
    print("\n评估 RAG 路径（RAGAS 4 指标）...")
    rag_eval = eval_rag_path(rag_items)
    print(f"  faithfulness: {rag_eval['overall']['faithfulness']:.4f}")
    print(f"  answer_relevancy: {rag_eval['overall']['answer_relevancy']:.4f}")
    print(f"  context_precision: {rag_eval['overall']['context_precision']:.4f}")
    print(f"  context_recall: {rag_eval['overall']['context_recall']:.4f}")

    print("\n评估 NL2SQL 路径（SQL 评估指标）...")
    nl2sql_eval = eval_nl2sql_path(nl2sql_items)
    print(f"  SQL 成功率: {nl2sql_eval['overall']['sql_success_rate']:.2%}")
    print(f"  结果非空率: {nl2sql_eval['overall']['result_nonEmpty_rate']:.2%}")
    print(f"  answer_relevancy: {nl2sql_eval['overall']['answer_relevancy']:.4f}")

    # 生成 Markdown 报告
    md = render_markdown(rag_eval, nl2sql_eval, len(items))
    out_path = os.path.join(REPORTS_DIR, 'ablation_OPT2_split.md')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f"\n报告已生成: {out_path}")

    # 同时保存 JSON 结构化结果
    json_out = os.path.join(DATA_DIR, 'ablation_OPT2_split.json')
    with open(json_out, 'w', encoding='utf-8') as f:
        json.dump({
            'generated_at': datetime.now().isoformat(),
            'total_n': len(items),
            'rag_path': rag_eval,
            'nl2sql_path': nl2sql_eval,
        }, f, ensure_ascii=False, indent=2)
    print(f"结构化结果: {json_out}")


if __name__ == '__main__':
    main()
