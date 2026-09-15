# -*- coding: utf-8 -*-
"""
飞书(Lark)推送模块
==================
每个 bot 可以配多个"推送目标(target)"，每个目标独立指定：
  - 推给哪个群 (webhook_key，对应 config 里 webhooks 池的某一个)
  - 用什么标题 + 文案模板
  - 是否只推送 list 明细里符合条件的部分（比如某个群只关心自己站点的数据）

target 配置示例：
  {
    "webhook_key": "SGF站点群",
    "title": "📦 明日配送单量 - SGF",
    "template": "**日期**: {date}\\n**总量**: {total}\\n{list_block}",
    "list_item_template": "- {site}: {qty}",     # 可选，不配就不生成 list_block
    "list_filter_field": "site",                  # 可选，按这个字段过滤list行
    "list_filter_values": ["SGF001", "SGF002"]     # 可选，只保留这些值；不配=不过滤，全部保留
  }
"""

import logging
import requests

logger = logging.getLogger("lark_report_bot")


def build_card(title: str, content_md: str) -> dict:
    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content_md}}
            ],
        },
    }


def render_list_block(list_items: list, target: dict) -> str:
    item_template = target.get("list_item_template")
    if not item_template:
        return ""

    filter_field = target.get("list_filter_field")
    filter_values = target.get("list_filter_values")

    filtered = list_items
    if filter_field and filter_values:
        filtered = [it for it in list_items if str(it.get(filter_field)) in [str(v) for v in filter_values]]

    lines = []
    for item in filtered:
        try:
            lines.append(item_template.format(**item))
        except KeyError as e:
            logger.warning(f"list模板缺字段 {e}，跳过该行: {item}")
    return "\n".join(lines)


def render_target_message(context: dict, target: dict) -> dict:
    """把抓取到的context，按某个target的模板渲染成飞书卡片payload"""
    list_items = context.get("_list_items", [])
    list_block = render_list_block(list_items, target)

    format_ctx = {k: v for k, v in context.items() if k != "_list_items"}
    format_ctx["list_block"] = list_block

    try:
        body = target["template"].format(**format_ctx)
    except KeyError as e:
        logger.error(f"消息模板缺字段 {e}，模板: {target['template']}")
        body = target["template"]

    return build_card(target.get("title", ""), body)


def send_webhook(url: str, payload: dict) -> bool:
    try:
        resp = requests.post(url, json=payload, timeout=10)
        result = resp.json()
        if result.get("code") not in (0, None):
            logger.warning(f"推送失败 {url}: {result}")
            return False
        logger.info(f"推送成功: {url}")
        return True
    except Exception as e:
        logger.error(f"推送异常 {url}: {e}")
        return False


def dispatch(context: dict, bot: dict, webhooks_pool: dict):
    """把一个bot抓到的context，按它配置的所有targets分别渲染+推送"""
    for target in bot.get("targets", []):
        webhook_key = target.get("webhook_key")
        url = webhooks_pool.get(webhook_key)
        if not url:
            logger.warning(f"target引用了不存在的webhook: {webhook_key}")
            continue
        payload = render_target_message(context, target)
        send_webhook(url, payload)
