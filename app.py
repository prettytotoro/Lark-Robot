# -*- coding: utf-8 -*-
"""
Lark机器人制作小程序 - 低代码配置UI
====================================
运行:
    streamlit run app.py

这个UI只负责"编辑配置"，实际的定时抓取+推送由 worker.py 常驻进程执行。
两者通过 bots_config.json 交互，worker 每60秒自动感知配置变化。
"""

import json
import streamlit as st
from bs4 import BeautifulSoup
from core.config_store import (
    load_config, add_webhook, delete_webhook,
    upsert_bot, delete_bot, get_bot,
)
from core.field_detector import detect_json_fields, detect_html_fields

st.set_page_config(page_title="Lark机器人制作小程序", layout="wide")
st.title("🤖 Lark机器人制作小程序")
st.caption("配置好就存进 bots_config.json，由后台 worker.py 按各自的调度规则自动执行抓取+推送")

cfg = load_config()

tab_bots, tab_webhooks = st.tabs(["机器人列表", "群Webhook池"])

# ===========================================================================
# Tab: 群 Webhook 池管理
# ===========================================================================
with tab_webhooks:
    st.subheader("群 Webhook 池")
    st.caption("先把要用到的群机器人 Webhook 地址存到这里，起个好记的名字，后面配置机器人推送目标时直接从池子里选")

    with st.form("add_webhook_form", clear_on_submit=True):
        c1, c2 = st.columns([1, 2])
        wh_name = c1.text_input("群昵称（自己起名，方便识别）")
        wh_url = c2.text_input("Webhook URL")
        if st.form_submit_button("添加"):
            if wh_name and wh_url:
                add_webhook(wh_name, wh_url)
                st.success(f"已添加: {wh_name}")
                st.rerun()
            else:
                st.error("名称和URL都要填")

    if cfg["webhooks"]:
        st.write("已保存的群：")
        for name, url in cfg["webhooks"].items():
            c1, c2, c3 = st.columns([1, 3, 1])
            c1.write(f"**{name}**")
            c2.code(url, language=None)
            if c3.button("删除", key=f"del_wh_{name}"):
                delete_webhook(name)
                st.rerun()
    else:
        st.info("还没有添加任何群Webhook")


# ===========================================================================
# Tab: 机器人列表 + 新建/编辑
# ===========================================================================
with tab_bots:
    left, right = st.columns([1, 2])

    with left:
        st.subheader("已有机器人")
        bots = cfg["bots"]
        if not bots:
            st.info("还没有创建任何机器人")
        for b in bots:
            with st.container(border=True):
                st.write(f"**{b['name']}** {'✅' if b.get('enabled', True) else '⏸️ 已停用'}")
                sched = b.get("schedule", {})
                if sched.get("type") == "cron":
                    st.caption(f"每天 {sched.get('hour',0):02d}:{sched.get('minute',0):02d} 触发一次")
                elif sched.get("type") == "interval":
                    st.caption(f"每 {sched.get('minutes',30)} 分钟轮询一次")
                st.caption(f"推送到 {len(b.get('targets', []))} 个目标")
                c1, c2 = st.columns(2)
                if c1.button("编辑", key=f"edit_{b['id']}"):
                    st.session_state["editing_bot_id"] = b["id"]
                    st.rerun()
                if c2.button("删除", key=f"del_{b['id']}"):
                    delete_bot(b["id"])
                    if st.session_state.get("editing_bot_id") == b["id"]:
                        st.session_state.pop("editing_bot_id", None)
                    st.rerun()
        if st.button("➕ 新建机器人"):
            st.session_state["editing_bot_id"] = None
            st.session_state["form_reset"] = True
            st.rerun()

    with right:
        editing_id = st.session_state.get("editing_bot_id", "__unset__")
        if editing_id == "__unset__":
            st.info("点左边「新建机器人」开始配置，或选一个已有机器人「编辑」")
        else:
            existing = get_bot(editing_id) if editing_id else None
            st.subheader("编辑机器人" if existing else "新建机器人")

            # ---- 用session_state管理动态数组：fields / list_fields / targets ----
            if st.session_state.get("form_reset") or "bot_fields" not in st.session_state:
                st.session_state["bot_fields"] = (existing["fetch"].get("fields", []) if existing else [])
                st.session_state["bot_list_source"] = (existing["fetch"].get("list", {}).get("source", "无") if existing and existing["fetch"].get("list") else "无")
                st.session_state["bot_list_cfg"] = (existing["fetch"].get("list", {}) if existing else {})
                st.session_state["bot_targets"] = (existing.get("targets", []) if existing else [])
                st.session_state["form_reset"] = False

            name = st.text_input("机器人名称", value=existing["name"] if existing else "")
            enabled = st.checkbox("启用", value=existing.get("enabled", True) if existing else True)

            st.markdown("### 1️⃣ 登录方式")
            login_type = st.selectbox(
                "登录类型", ["none", "form", "json_api"],
                index=["none", "form", "json_api"].index(existing["login"]["type"]) if existing else 0,
                format_func=lambda x: {"none": "不需要登录", "form": "表单登录", "json_api": "JSON接口登录"}[x],
            )
            login_cfg = {"type": login_type}
            if login_type != "none":
                c1, c2 = st.columns(2)
                login_cfg["url"] = c1.text_input("登录URL", value=existing["login"].get("url", "") if existing else "")
                login_cfg["username"] = c2.text_input("账号", value=existing["login"].get("username", "") if existing else "")
                c3, c4 = st.columns(2)
                login_cfg["password"] = c3.text_input("密码", type="password", value=existing["login"].get("password", "") if existing else "")
                c5, c6 = st.columns(2)
                login_cfg["username_field"] = c5.text_input("用户名字段名", value=existing["login"].get("username_field", "username") if existing else "username")
                login_cfg["password_field"] = c6.text_input("密码字段名", value=existing["login"].get("password_field", "password") if existing else "password")

            st.markdown("### 2️⃣ 抓取目标")
            c1, c2 = st.columns([3, 1])
            fetch_url = c1.text_input("目标URL(登录后访问的数据接口/页面)", value=existing["fetch"].get("url", "") if existing else "")
            fetch_method = c2.selectbox("方法", ["GET", "POST"], index=0 if not existing or existing["fetch"].get("method", "GET") == "GET" else 1)
            response_type = st.radio("返回格式", ["json", "html"], index=0 if not existing or existing["fetch"].get("response_type", "json") == "json" else 1, horizontal=True)

            with st.expander("🔍 上传样本自动识别字段（推荐，不用自己写路径/选择器）", expanded=False):
                st.caption(
                    "登录目标网站后，从浏览器F12开发者工具里把数据接口的Response复制出来存成 .json 文件；"
                    "如果是网页表格类的数据，网页另存为 .html 也行。上传后自动扫出候选字段，勾选想要的就行。"
                )
                sample_file = st.file_uploader("上传样本文件(.json / .html)", type=["json", "html", "txt"], key="sample_uploader")
                if sample_file is not None:
                    raw_bytes = sample_file.read()
                    is_json = sample_file.name.lower().endswith(".json")
                    if not is_json:
                        # 兜底：即使是.txt/.html，也先试试能不能当json解析
                        try:
                            json.loads(raw_bytes.decode("utf-8"))
                            is_json = True
                        except Exception:
                            is_json = False

                    if is_json:
                        parsed_sample = json.loads(raw_bytes.decode("utf-8"))
                        leaves, array_cands, dict_cands = detect_json_fields(parsed_sample)

                        st.write(f"识别到 {len(leaves)} 个单值字段候选：")
                        chosen_leaf_idx = []
                        for i, leaf in enumerate(leaves):
                            c1, c2 = st.columns([1, 4])
                            checked = c1.checkbox("选", key=f"leafchk_{i}", label_visibility="collapsed")
                            c2.write(f"`{leaf['path']}` → 建议命名 **{leaf['key_suggestion']}**，样例值: `{leaf['value_preview']}`")
                            if checked:
                                chosen_leaf_idx.append(i)
                        if st.button("✅ 把勾选的单值字段加入字段列表"):
                            existing_paths = {f["path"] for f in st.session_state["bot_fields"]}
                            for i in chosen_leaf_idx:
                                leaf = leaves[i]
                                if leaf["path"] not in existing_paths:
                                    st.session_state["bot_fields"].append({"key": leaf["key_suggestion"], "path": leaf["path"]})
                            st.success(f"已加入 {len(chosen_leaf_idx)} 个字段")
                            st.rerun()

                        if array_cands:
                            st.write("识别到数组型明细候选(比如按站点拆分的多行数据)：")
                            for i, arr in enumerate(array_cands):
                                st.write(f"路径 `{arr['path']}`，共 {arr['size']} 条，字段: {arr['item_keys']}，样例: `{arr['sample']}`")
                                if st.button(f"设为明细列表", key=f"setarr_{i}"):
                                    st.session_state["bot_list_source"] = "array"
                                    st.session_state["bot_list_cfg"] = {
                                        "source": "array",
                                        "path": arr["path"],
                                        "item_fields": [{"key": k, "path": k} for k in arr["item_keys"]],
                                    }
                                    st.success("已设为明细列表，下面「明细列表」区域已自动填好")
                                    st.rerun()

                        if dict_cands:
                            st.write("识别到字典型明细候选(比如 {站点: 数量})：")
                            for i, dc in enumerate(dict_cands):
                                st.write(f"路径 `{dc['path']}`，共 {dc['size']} 项，样例: `{dc['sample']}`")
                                if st.button(f"设为明细列表 ", key=f"setdict_{i}"):
                                    st.session_state["bot_list_source"] = "dict_items"
                                    st.session_state["bot_list_cfg"] = {
                                        "source": "dict_items",
                                        "path": dc["path"],
                                        "key_field": "key",
                                        "value_field": "value",
                                    }
                                    st.success("已设为明细列表，下面「明细列表」区域已自动填好")
                                    st.rerun()
                    else:
                        soup = BeautifulSoup(raw_bytes.decode("utf-8", errors="ignore"), "html.parser")
                        leaf_cands, row_cands = detect_html_fields(soup)
                        st.caption("HTML识别是启发式扫描，不保证100%准确，建议加入后人工核对一下选择器。")

                        st.write(f"识别到 {len(leaf_cands)} 个单值字段候选：")
                        chosen_html_idx = []
                        for i, leaf in enumerate(leaf_cands):
                            c1, c2 = st.columns([1, 4])
                            checked = c1.checkbox("选", key=f"htmlleafchk_{i}", label_visibility="collapsed")
                            c2.write(f"`{leaf['path']}` → 建议命名 **{leaf['key_suggestion']}**，样例值: `{leaf['value_preview']}`")
                            if checked:
                                chosen_html_idx.append(i)
                        if st.button("✅ 把勾选的单值字段加入字段列表 "):
                            existing_paths = {f["path"] for f in st.session_state["bot_fields"]}
                            for i in chosen_html_idx:
                                leaf = leaf_cands[i]
                                if leaf["path"] not in existing_paths:
                                    st.session_state["bot_fields"].append({"key": leaf["key_suggestion"], "path": leaf["path"]})
                            st.success(f"已加入 {len(chosen_html_idx)} 个字段")
                            st.rerun()

                        if row_cands:
                            st.write("识别到重复行候选(可能是明细列表)，选一个作为明细来源：")
                            for i, row in enumerate(row_cands):
                                st.write(f"选择器 `{row['selector']}`，共 {row['count']} 行，样例: `{row['sample_text']}`")
                                if st.button("设为明细列表(HTML)", key=f"sethtmlrow_{i}"):
                                    st.session_state["bot_list_source"] = "html_repeat"
                                    st.session_state["bot_list_cfg"] = {
                                        "source": "html_repeat",
                                        "html_selector": row["selector"],
                                        "html_item_fields": [],  # 行内子字段选择器建议手动补充，结构差异太大不好自动猜
                                    }
                                    st.info("已设为明细列表框架，但行内子字段选择器需要你去下面「明细列表」区域手动补一下(结构差异太大没法自动猜)")
                                    st.rerun()

            st.markdown("**要提取的字段**（比如总量、日期这种单值，也可以从上面自动识别里勾选加入）")
            for i, f in enumerate(st.session_state["bot_fields"]):
                c1, c2, c3 = st.columns([2, 3, 1])
                f["key"] = c1.text_input("字段名(消息模板里用 {字段名} 引用)", value=f.get("key", ""), key=f"fkey_{i}")
                hint = "JSON点路径，如 data.total" if response_type == "json" else "CSS选择器，如 css:.total-value"
                f["path"] = c2.text_input(hint, value=f.get("path", ""), key=f"fpath_{i}")
                if c3.button("移除", key=f"frm_{i}"):
                    st.session_state["bot_fields"].pop(i)
                    st.rerun()
            if st.button("+ 添加字段"):
                st.session_state["bot_fields"].append({"key": "", "path": ""})
                st.rerun()

            st.markdown("**明细列表**（可选，比如按站点拆分的多行数据，不需要就跳过）")
            list_source = st.selectbox(
                "列表来源", ["无", "dict_items", "array", "html_repeat"],
                index=["无", "dict_items", "array", "html_repeat"].index(st.session_state["bot_list_source"]),
                format_func=lambda x: {"无": "不需要明细", "dict_items": "JSON字典(如{站点:数量})", "array": "JSON数组(如[{site,qty},...])", "html_repeat": "HTML重复元素"}[x],
                key="list_source_select",
            )
            st.session_state["bot_list_source"] = list_source
            list_cfg = st.session_state["bot_list_cfg"]
            if list_source == "dict_items":
                list_cfg["source"] = "dict_items"
                list_cfg["path"] = st.text_input("JSON点路径(指向字典)", value=list_cfg.get("path", ""))
                c1, c2 = st.columns(2)
                list_cfg["key_field"] = c1.text_input("key对应字段名", value=list_cfg.get("key_field", "site"))
                list_cfg["value_field"] = c2.text_input("value对应字段名", value=list_cfg.get("value_field", "qty"))
            elif list_source == "array":
                list_cfg["source"] = "array"
                list_cfg["path"] = st.text_input("JSON点路径(指向数组)", value=list_cfg.get("path", ""))
                st.caption("数组元素字段映射，格式: 字段名=点路径，一行一个，例如:\nsite=site\nqty=qty")
                raw = st.text_area("字段映射", value="\n".join(f"{f['key']}={f['path']}" for f in list_cfg.get("item_fields", [])))
                list_cfg["item_fields"] = [
                    {"key": kv.split("=")[0].strip(), "path": kv.split("=")[1].strip()}
                    for kv in raw.splitlines() if "=" in kv
                ]
            elif list_source == "html_repeat":
                list_cfg["source"] = "html_repeat"
                list_cfg["html_selector"] = st.text_input("重复行的CSS选择器", value=list_cfg.get("html_selector", ""))
                st.caption("每行内字段映射，格式: 字段名=CSS选择器，一行一个")
                raw = st.text_area("字段映射 ", value="\n".join(f"{f['key']}={f['selector']}" for f in list_cfg.get("html_item_fields", [])))
                list_cfg["html_item_fields"] = [
                    {"key": kv.split("=")[0].strip(), "selector": kv.split("=")[1].strip()}
                    for kv in raw.splitlines() if "=" in kv
                ]
            else:
                list_cfg = {}
            st.session_state["bot_list_cfg"] = list_cfg

            st.markdown("### 3️⃣ 推送目标（可以配多个，不同群发不同内容）")
            for i, t in enumerate(st.session_state["bot_targets"]):
                with st.container(border=True):
                    st.write(f"目标 {i+1}")
                    c1, c2 = st.columns(2)
                    t["webhook_key"] = c1.selectbox(
                        "推送到哪个群", list(cfg["webhooks"].keys()) or ["(先去群Webhook池添加)"],
                        index=(list(cfg["webhooks"].keys()).index(t["webhook_key"]) if t.get("webhook_key") in cfg["webhooks"] else 0),
                        key=f"twh_{i}",
                    )
                    t["title"] = c2.text_input("卡片标题", value=t.get("title", ""), key=f"ttitle_{i}")
                    t["template"] = st.text_area(
                        "消息正文模板（用 {字段名} 引用第2步提取的字段，用 {list_block} 插入明细列表）",
                        value=t.get("template", ""), key=f"ttpl_{i}",
                    )
                    if list_cfg:
                        c3, c4, c5 = st.columns(3)
                        t["list_item_template"] = c3.text_input("明细每行模板，如 - {site}: {qty}", value=t.get("list_item_template", ""), key=f"tlit_{i}")
                        t["list_filter_field"] = c4.text_input("按哪个字段过滤明细(可选)", value=t.get("list_filter_field", ""), key=f"tlf_{i}")
                        t["list_filter_values"] = c5.text_input("只保留这些值,逗号分隔(可选)", value=",".join(t.get("list_filter_values", [])), key=f"tlv_{i}")
                    if st.button("移除此目标", key=f"trm_{i}"):
                        st.session_state["bot_targets"].pop(i)
                        st.rerun()
            if st.button("+ 添加推送目标"):
                st.session_state["bot_targets"].append({"webhook_key": "", "title": "", "template": ""})
                st.rerun()

            st.markdown("### 4️⃣ 调度方式")
            sched_type = st.radio(
                "触发方式", ["cron", "interval"],
                index=0 if not existing or existing.get("schedule", {}).get("type", "cron") == "cron" else 1,
                format_func=lambda x: {"cron": "固定时间点(每天一次)", "interval": "间隔轮询"}[x],
                horizontal=True,
            )
            schedule = {"type": sched_type}
            if sched_type == "cron":
                c1, c2 = st.columns(2)
                schedule["hour"] = c1.number_input("小时(0-23)", 0, 23, value=existing.get("schedule", {}).get("hour", 9) if existing else 9)
                schedule["minute"] = c2.number_input("分钟(0-59)", 0, 59, value=existing.get("schedule", {}).get("minute", 0) if existing else 0)
            else:
                schedule["minutes"] = st.number_input("每隔几分钟", 1, 1440, value=existing.get("schedule", {}).get("minutes", 30) if existing else 30)

            st.divider()
            if st.button("💾 保存机器人", type="primary"):
                targets_clean = []
                for t in st.session_state["bot_targets"]:
                    tt = dict(t)
                    if isinstance(tt.get("list_filter_values"), str):
                        tt["list_filter_values"] = [v.strip() for v in tt["list_filter_values"].split(",") if v.strip()]
                    targets_clean.append(tt)

                bot = {
                    "id": existing["id"] if existing else None,
                    "name": name,
                    "enabled": enabled,
                    "login": login_cfg,
                    "fetch": {
                        "url": fetch_url,
                        "method": fetch_method,
                        "response_type": response_type,
                        "fields": st.session_state["bot_fields"],
                        "list": list_cfg if list_cfg else None,
                    },
                    "targets": targets_clean,
                    "schedule": schedule,
                }
                bot_id = upsert_bot(bot)
                st.success(f"已保存: {name}")
                st.session_state["editing_bot_id"] = bot_id
                st.session_state["form_reset"] = True
                st.rerun()
