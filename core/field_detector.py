# -*- coding: utf-8 -*-
"""
字段自动识别引擎（纯本地规则，不调用任何外部API）
================================================
输入一份样本数据（登录后从浏览器复制的JSON响应，或另存的HTML页面），
自动扫描出候选字段，供UI里勾选，省去手写JSON路径/CSS选择器的步骤。

局限性（如实说明）：
- JSON识别比较可靠：结构清晰，能准确扫出所有叶子字段、字典型明细、数组型明细
- HTML识别是启发式的，不保证100%准确，复杂页面建议识别完之后人工核对一下选择器
"""

from collections import defaultdict


# ---------------------------------------------------------------------------
# JSON 样本识别
# ---------------------------------------------------------------------------

def detect_json_fields(obj, prefix=""):
    """
    递归扫描JSON，返回三类候选：
      leaves          -> 单值字段候选，如 {"path": "data.total", "key_suggestion": "total", "value_preview": 1010}
      array_candidates -> 数组型明细候选(list[dict])，如按站点拆分的数组
      dict_candidates  -> 字典型明细候选(dict of 标量)，如 {"SGF001": 900, "SGF002": 334}
    """
    leaves, array_candidates, dict_candidates = [], [], []

    if isinstance(obj, dict):
        if obj and all(not isinstance(v, (dict, list)) for v in obj.values()):
            dict_candidates.append({
                "path": prefix.rstrip("."),
                "size": len(obj),
                "sample": dict(list(obj.items())[:3]),
            })
        for k, v in obj.items():
            new_prefix = f"{prefix}{k}." if prefix else f"{k}."
            path = new_prefix.rstrip(".")
            if isinstance(v, dict):
                sub_l, sub_a, sub_d = detect_json_fields(v, new_prefix)
                leaves.extend(sub_l)
                array_candidates.extend(sub_a)
                dict_candidates.extend(sub_d)
            elif isinstance(v, list):
                if v and all(isinstance(item, dict) for item in v):
                    array_candidates.append({
                        "path": path,
                        "size": len(v),
                        "item_keys": list(v[0].keys()),
                        "sample": v[0],
                    })
                else:
                    leaves.append({"path": path, "key_suggestion": k, "value_preview": v})
            else:
                leaves.append({"path": path, "key_suggestion": k, "value_preview": v})

    return leaves, array_candidates, dict_candidates


# ---------------------------------------------------------------------------
# HTML 样本识别（启发式，best-effort）
# ---------------------------------------------------------------------------

def _build_selector(el):
    if el.get("id"):
        return f"#{el['id']}"
    if el.get("class"):
        return f".{el['class'][0]}"
    return None


def detect_html_fields(soup):
    """
    扫描HTML，返回：
      leaf_candidates -> 单值字段候选，如 {"path": "css:.total-value", "key_suggestion": "...", "value_preview": "1010"}
      row_candidates  -> 重复行候选(用于明细列表)，如 {"selector": "div.site-row", "count": 5, "sample_text": "..."}
    """
    leaf_candidates = []
    seen_selectors = set()

    for el in soup.find_all(True):
        if el.find(True):  # 跳过还有子标签的容器元素，只要"叶子"文本节点
            continue
        text = el.get_text(strip=True)
        if not text or len(text) > 60:
            continue
        selector = _build_selector(el)
        if not selector or selector in seen_selectors:
            continue
        seen_selectors.add(selector)
        leaf_candidates.append({
            "path": f"css:{selector}",
            "key_suggestion": el.get("id") or (el.get("class", [""])[0]) or el.name,
            "value_preview": text,
        })

    groups = defaultdict(list)
    for el in soup.find_all(True):
        classes = tuple(el.get("class", []))
        if classes:
            groups[(el.name, classes)].append(el)

    row_candidates = []
    for (tag, classes), els in groups.items():
        if len(els) >= 2:
            selector = f"{tag}.{'.'.join(classes)}"
            row_candidates.append({
                "selector": selector,
                "count": len(els),
                "sample_text": els[0].get_text(" ", strip=True)[:60],
            })

    return leaf_candidates[:50], row_candidates[:20]
