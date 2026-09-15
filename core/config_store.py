# -*- coding: utf-8 -*-
"""
配置存取层：所有机器人/群组配置统一存在 bots_config.json
UI (app.py) 和后台 worker (worker.py) 都通过这个模块读写，保证格式一致。
"""

import json
import os
import uuid
from typing import Any, Dict, List

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bots_config.json")

DEFAULT_CONFIG = {
    "webhooks": {},   # {"群昵称": "https://open.feishu.cn/open-apis/bot/v2/hook/xxxx"}
    "bots": []        # 见 README 里的 bot 结构说明
}


def load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: Dict[str, Any]):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ---- webhooks ----

def add_webhook(name: str, url: str):
    cfg = load_config()
    cfg["webhooks"][name] = url
    save_config(cfg)


def delete_webhook(name: str):
    cfg = load_config()
    cfg["webhooks"].pop(name, None)
    save_config(cfg)


# ---- bots ----

def list_bots() -> List[Dict[str, Any]]:
    return load_config()["bots"]


def get_bot(bot_id: str) -> Dict[str, Any]:
    for b in list_bots():
        if b["id"] == bot_id:
            return b
    return None


def upsert_bot(bot: Dict[str, Any]):
    cfg = load_config()
    if not bot.get("id"):
        bot["id"] = str(uuid.uuid4())[:8]
    for i, b in enumerate(cfg["bots"]):
        if b["id"] == bot["id"]:
            cfg["bots"][i] = bot
            save_config(cfg)
            return bot["id"]
    cfg["bots"].append(bot)
    save_config(cfg)
    return bot["id"]


def delete_bot(bot_id: str):
    cfg = load_config()
    cfg["bots"] = [b for b in cfg["bots"] if b["id"] != bot_id]
    save_config(cfg)
