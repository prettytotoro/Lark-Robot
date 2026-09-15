# -*- coding: utf-8 -*-
"""
后台Worker：常驻进程，负责实际的"到点抓取+推送"。
UI (app.py) 只负责改配置文件，真正的调度和执行都在这里。

启动:
    python worker.py

每 60 秒会重新读一次 bots_config.json，如果发现机器人配置有增删改，
会自动更新调度任务，不需要重启 worker。
"""

import logging
import time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from core.config_store import load_config
from core.scraper import run_bot_fetch
from core.lark_push import dispatch

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("lark_report_bot")

scheduler = BackgroundScheduler(timezone="America/Chicago")  # TODO: 按需调整时区
_known_job_signatures = {}  # bot_id -> 配置的hash签名，用于判断是否变了


def run_bot(bot_id: str):
    """实际执行一个bot：抓取 -> 推送。每次触发都重新读最新配置，避免用到旧的账号密码等。"""
    cfg = load_config()
    bot = next((b for b in cfg["bots"] if b["id"] == bot_id), None)
    if not bot or not bot.get("enabled", True):
        return
    logger.info(f"触发机器人: {bot['name']} ({bot_id})")
    try:
        context = run_bot_fetch(bot)
        dispatch(context, bot, cfg["webhooks"])
    except Exception as e:
        logger.error(f"机器人 {bot['name']} 执行失败: {e}")


def _bot_signature(bot: dict) -> str:
    """简单签名：调度相关字段变了就需要重建job"""
    sched = bot.get("schedule", {})
    return f"{bot.get('enabled', True)}|{sched.get('type')}|{sched.get('hour')}|{sched.get('minute')}|{sched.get('minutes')}"


def sync_jobs():
    """对比当前配置和已注册的job，增删改成一致"""
    cfg = load_config()
    current_ids = set()

    for bot in cfg["bots"]:
        bot_id = bot["id"]
        current_ids.add(bot_id)
        sig = _bot_signature(bot)

        if _known_job_signatures.get(bot_id) == sig:
            continue  # 没变化，跳过

        # 有变化或新增：先移除旧job（如果存在），再按新配置注册
        if scheduler.get_job(bot_id):
            scheduler.remove_job(bot_id)

        if not bot.get("enabled", True):
            _known_job_signatures[bot_id] = sig
            continue

        sched = bot.get("schedule", {})
        if sched.get("type") == "cron":
            trigger = CronTrigger(hour=sched.get("hour", 0), minute=sched.get("minute", 0))
        elif sched.get("type") == "interval":
            trigger = IntervalTrigger(minutes=sched.get("minutes", 30))
        else:
            logger.warning(f"机器人 {bot['name']} 的调度类型无效，跳过")
            continue

        scheduler.add_job(run_bot, trigger, args=[bot_id], id=bot_id, replace_existing=True)
        _known_job_signatures[bot_id] = sig
        logger.info(f"已注册/更新任务: {bot['name']} -> {sched}")

    # 清理已被删除的bot对应的job
    for bot_id in list(_known_job_signatures.keys()):
        if bot_id not in current_ids:
            if scheduler.get_job(bot_id):
                scheduler.remove_job(bot_id)
            _known_job_signatures.pop(bot_id, None)
            logger.info(f"已移除任务: {bot_id}")


def main():
    scheduler.start()
    logger.info("Worker 已启动，每60秒同步一次配置...(Ctrl+C 退出)")
    try:
        while True:
            sync_jobs()
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Worker 已停止")


if __name__ == "__main__":
    main()
