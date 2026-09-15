# -*- coding: utf-8 -*-
"""
通用抓取引擎
============
根据 bot 配置里的 login / fetch / list 三段描述，自动完成：
  1. 登录（表单登录 or JSON接口登录，拿到可复用的 requests.Session）
  2. 请求目标数据接口/页面
  3. 按配置提取字段（JSON点路径 或 CSS选择器）
  4. 按配置提取"列表"数据（比如按站点拆分的明细行），供消息模板里的 {list_block} 使用

不需要每次接入新数据源都写新代码——只要目标站点的登录方式和数据结构能用下面的配置描述出来。
如果遇到特别复杂的站点（比如需要处理JS渲染），需要额外接入 Playwright，这个框架里先留了接口位置。
"""

import re
import requests
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# 登录
# ---------------------------------------------------------------------------

def login_session(login_cfg: dict) -> requests.Session:
    """
    根据登录配置返回一个已登录的 requests.Session。
    login_cfg 示例：
      {
        "type": "form",          # "form" | "json_api" | "none"
        "url": "https://xxx/login",
        "username": "xxx",
        "password": "xxx",
        "username_field": "username",   # 表单里用户名字段名
        "password_field": "password",   # 表单里密码字段名
        "extra_payload": {},            # 其他登录时需要一起提交的固定字段
        "extra_headers": {}             # 需要的自定义请求头
      }
    """
    session = requests.Session()
    login_type = login_cfg.get("type", "none")

    if login_type == "none":
        return session

    if login_type == "cookie":
        # 直接复用浏览器里已登录会话的Cookie，不用重放登录流程
        # (很多内部系统的登录不是简单的账号密码POST，可能涉及CSRF/SSO/多步验证，
        #  遇到这种情况用Cookie模式最省事，缺点是Cookie过期后要手动更新)
        cookie_str = login_cfg.get("cookie", "")
        if cookie_str:
            session.headers.update({"Cookie": cookie_str})
        extra_headers = login_cfg.get("extra_headers", {}) or {}
        if extra_headers:
            session.headers.update(extra_headers)
        return session

    headers = login_cfg.get("extra_headers", {}) or {}
    if headers:
        session.headers.update(headers)

    payload = dict(login_cfg.get("extra_payload", {}) or {})
    payload[login_cfg.get("username_field", "username")] = login_cfg.get("username", "")
    payload[login_cfg.get("password_field", "password")] = login_cfg.get("password", "")

    if login_type == "form":
        resp = session.post(login_cfg["url"], data=payload, timeout=15)
    elif login_type == "json_api":
        resp = session.post(login_cfg["url"], json=payload, timeout=15)
        # 有些系统登录接口返回 token，需要手动塞进后续请求头，这里给个占位：
        try:
            data = resp.json()
            token = data.get("token") or data.get("access_token")
            if token:
                session.headers.update({"Authorization": f"Bearer {token}"})
        except Exception:
            pass
    else:
        raise ValueError(f"不支持的登录类型: {login_type}")

    resp.raise_for_status()
    return session


# ---------------------------------------------------------------------------
# 请求目标数据
# ---------------------------------------------------------------------------

def fetch_raw(session: requests.Session, fetch_cfg: dict):
    """
    根据 fetch_cfg 请求目标数据源，返回 (response_type, parsed)
    fetch_cfg 示例：
      {
        "url": "https://xxx/api/tomorrow-delivery",
        "method": "GET",              # GET | POST
        "params": {},                 # query参数 或 POST body
        "response_type": "json"       # "json" | "html"
      }
    """
    method = fetch_cfg.get("method", "GET").upper()
    params = fetch_cfg.get("params", {}) or {}
    url = fetch_cfg["url"]
    response_type = fetch_cfg.get("response_type", "json")

    if method == "GET":
        resp = session.get(url, params=params, timeout=15)
    else:
        resp = session.post(url, json=params, timeout=15)
    resp.raise_for_status()

    if response_type == "json":
        return "json", resp.json()
    else:
        return "html", BeautifulSoup(resp.text, "html.parser")


# ---------------------------------------------------------------------------
# 字段提取
# ---------------------------------------------------------------------------

def dot_get(obj, path):
    """按点路径从嵌套dict/list里取值，比如 'data.total' 或 'data.items.0.qty'"""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def extract_fields(response_type: str, parsed, fields_cfg: list) -> dict:
    """
    fields_cfg: [{"key": "total", "path": "data.total"}, ...]
    JSON模式下 path 是点路径；HTML模式下 path 以 "css:" 开头，后面跟CSS选择器。
    """
    result = {}
    for f in fields_cfg:
        key = f["key"]
        path = f["path"]
        if response_type == "json":
            result[key] = dot_get(parsed, path)
        else:  # html
            selector = path[4:] if path.startswith("css:") else path
            el = parsed.select_one(selector)
            result[key] = el.get_text(strip=True) if el else None
    return result


def extract_list(response_type: str, parsed, list_cfg: dict) -> list:
    """
    提取"重复行"数据，比如按站点拆分的明细。返回 list[dict]。
    list_cfg 三种模式：

    1) JSON字典模式 (比如 {"SGF001": 900, "SGF002": 334}):
       {"source": "dict_items", "path": "data.by_site",
        "key_field": "site", "value_field": "qty"}

    2) JSON数组模式 (比如 [{"site": "SGF001", "qty": 900}, ...]):
       {"source": "array", "path": "data.items",
        "item_fields": [{"key": "site", "path": "site"}, {"key": "qty", "path": "qty"}]}

    3) HTML重复元素模式：
       {"source": "html_repeat", "html_selector": ".site-row",
        "html_item_fields": [{"key": "site", "selector": ".site-name"},
                              {"key": "qty", "selector": ".qty"}]}
    """
    if not list_cfg:
        return []
    source = list_cfg["source"]

    if source == "dict_items":
        raw = dot_get(parsed, list_cfg["path"]) or {}
        k_field = list_cfg.get("key_field", "key")
        v_field = list_cfg.get("value_field", "value")
        return [{k_field: k, v_field: v} for k, v in raw.items()]

    if source == "array":
        raw = dot_get(parsed, list_cfg["path"]) or []
        items = []
        for entry in raw:
            item = {}
            for f in list_cfg["item_fields"]:
                item[f["key"]] = dot_get(entry, f["path"])
            items.append(item)
        return items

    if source == "html_repeat":
        rows = parsed.select(list_cfg["html_selector"])
        items = []
        for row in rows:
            item = {}
            for f in list_cfg["html_item_fields"]:
                el = row.select_one(f["selector"])
                item[f["key"]] = el.get_text(strip=True) if el else None
            items.append(item)
        return items

    raise ValueError(f"不支持的list来源: {source}")


# ---------------------------------------------------------------------------
# 一站式：登录 + 抓取 + 提取
# ---------------------------------------------------------------------------

def run_bot_fetch(bot: dict) -> dict:
    """
    执行一个bot完整的抓取流程，返回 context：
      {字段...,  "_list_items": [...]}
    context 供 lark_push.py 渲染消息模板使用。
    """
    session = login_session(bot.get("login", {"type": "none"}))
    response_type, parsed = fetch_raw(session, bot["fetch"])

    context = extract_fields(response_type, parsed, bot["fetch"].get("fields", []))
    list_items = extract_list(response_type, parsed, bot["fetch"].get("list"))
    context["_list_items"] = list_items
    return context
