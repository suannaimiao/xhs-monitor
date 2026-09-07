import json
import random
import re
import time
import urllib.parse
from datetime import datetime

from loguru import logger

from apis.xhs_pc_apis import XHS_Apis
from xhs_utils.xhs_pc import XHSPcAuth

from .config import NOTE_URL_TPL
from .db import connect, insert_metrics, known_note_ids, now, upsert_note

# 联名识别：'品牌A x 品牌B' / 'A×B' / 'A✖B' 等，以及 '联名/合作款' 关键词
COBRAND_SEP = r"[xX×✖✕]"
COBRAND_RE = re.compile(
    r"([A-Za-z0-9\u4e00-\u9fa5][A-Za-z0-9\u4e00-\u9fa5&·+.\-]{0,24})"
    r"\s*" + COBRAND_SEP + r"\s*"
    r"([A-Za-z0-9\u4e00-\u9fa5][A-Za-z0-9\u4e00-\u9fa5&·+.\-]{0,24})"
)
COBRAND_KEYWORDS = ("联名", "合作款", "联乘", "特别合作")
# 常见误匹配词：分隔符两侧出现这些视为普通文本而非品牌名
COBRAND_STOP = {"vs", "and", "or", "the", "of", "in", "on", "at", "to", "x", "iphone", "ios", "pc", "tv", "ui", "ux", "xp", "xl", "xs", "dna", "diy"}
# 品牌名前后常见的修饰语（修剪用）
_COBRAND_SUFFIX = ["联名礼盒", "联名系列", "合作系列", "联名款", "合作款", "联名", "限定", "礼盒", "周边",
                   "开箱", "测评", "上新", "开售", "发布", "推荐", "种草", "分享", "来啦", "来了", "好可爱"]
_COBRAND_PREFIX = ["终于买到", "终于", "今天买了", "今天入手", "开箱", "入手", "买了", "抢到", "喜提",
                   "首发", "新品", "测评", "推荐", "种草", "第一个", "以及", "还有", "同时"]


def _trim_brand(w: str) -> str:
    changed = True
    while changed:
        changed = False
        for suf in _COBRAND_SUFFIX:
            if len(w) > len(suf) + 1 and w.endswith(suf):
                w, changed = w[:-len(suf)], True
        for pre in _COBRAND_PREFIX:
            if len(w) > len(pre) + 1 and w.startswith(pre):
                w, changed = w[len(pre):], True
    return w.strip("。，,.！!？?~～ 的了在是这就也都被把让给用要又再才刚和与跟有个这那")


def _brandlike(word: str) -> bool:
    w = word.strip().strip("。，,.！!？?~～ ")
    if len(w) < 1 or len(w) > 25 or w.lower() in COBRAND_STOP:
        return False
    if re.fullmatch(r"[a-z]+", w):
        return False
    if re.fullmatch(r"[\d.]+", w):
        return False
    return True


def detect_cobrand(title: str, desc: str, tags: str = "") -> str:
    text = f"{title or ''} {desc or ''} {tags or ''}"
    found = []
    for m in COBRAND_RE.finditer(text):
        a, b = _trim_brand(m.group(1)), _trim_brand(m.group(2))
        if _brandlike(a) and _brandlike(b):
            pair = f"{a} × {b}"
            if pair not in found:
                found.append(pair)
    # 联名关键词兜底：无 x 配对但明确写了联名
    if not found and any(k in text for k in COBRAND_KEYWORDS):
        for k in COBRAND_KEYWORDS:
            i = text.find(k)
            if i >= 0:
                found.append(f"{text[max(0, i-12):i+len(k)+12].strip()}（关键词：{k}）")
                break
    return "; ".join(found[:3])


def build_api(cfg):
    if not cfg["cookies"]:
        raise ValueError(".env 中未配置 COOKIES，请浏览器登录小红书后复制完整 Cookie")
    auth = XHSPcAuth.from_cookie(cfg["cookies"])
    api = XHS_Apis(auth).bootstrap()
    return api


def health_check(api) -> tuple[bool, str]:
    success, msg, data = api.get_user_me()
    nickname = (data or {}).get("data", {}).get("nickname", "")
    return success, f"登录态正常: {nickname}" if success else f"Cookie 失效或异常: {msg}"


def _int_cn(v) -> int:
    if v is None:
        return 0
    s = str(v).strip().replace(",", "")
    try:
        return int(float(s))
    except ValueError:
        pass
    mult = 1
    if s.endswith("万"):
        mult, s = 10_000, s[:-1]
    elif s.endswith("亿"):
        mult, s = 100_000_000, s[:-1]
    elif s.endswith("w"):
        mult, s = 10_000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0


def _summary_from_card(card: dict, user_id: str) -> dict:
    interact = card.get("interact_info") or {}
    cover = (card.get("cover") or {}).get("url_default") or (
        ((card.get("cover") or {}).get("info_list") or [{}])[-1].get("url")
    )
    return {
        "note_id": card.get("note_id") or card.get("id"),
        "user_id": user_id,
        "nickname": (card.get("user") or {}).get("nickname"),
        "title": (card.get("display_title") or "").strip() or "无标题",
        "note_type": "视频" if card.get("type") == "video" else "图集",
        "publish_time": card.get("time"),
        "liked_count": _int_cn(interact.get("liked_count")),
        "collected_count": _int_cn(interact.get("collected_count")),
        "comment_count": _int_cn(interact.get("comment_count")),
        "share_count": _int_cn(interact.get("share_count")),
        "note_url": NOTE_URL_TPL.format(note_id=card.get("note_id") or card.get("id"),
                                        token=card.get("xsec_token", "")),
        "cover_url": cover,
        "raw": card,
    }


def _detail_from_note_info(item: dict) -> dict:
    nc = item.get("note_card") or {}
    interact = nc.get("interact_info") or {}
    tags = ",".join(t["name"] for t in (nc.get("tag_list") or []) if isinstance(t, dict) and t.get("name"))
    return {
        "title": (nc.get("title") or "").strip() or "无标题",
        "desc": nc.get("desc", ""),
        "note_type": "图集" if nc.get("type") == "normal" else "视频",
        "liked_count": _int_cn(interact.get("liked_count")),
        "collected_count": _int_cn(interact.get("collected_count")),
        "comment_count": _int_cn(interact.get("comment_count")),
        "share_count": _int_cn(interact.get("share_count")),
        "ip_location": nc.get("ip_location", "未知"),
        "tags": tags,
        "publish_time": nc.get("time"),
        "cobrand": detect_cobrand(nc.get("title", ""), nc.get("desc", ""), tags),
    }


def iter_user_notes(api, homepage: str, cutoff_ms: int, page_sleep=(2, 5), max_consecutive_old=5):
    """按发布时间从新到旧翻页产出笔记卡片，越过 cutoff（或连续多张旧笔记）即停止。"""
    parsed = urllib.parse.urlparse(homepage)
    user_id = parsed.path.split("/")[-1]
    qs = urllib.parse.parse_qs(parsed.query)
    xsec_token = qs.get("xsec_token", [""])[0]
    xsec_source = qs.get("xsec_source", ["pc_search"])[0]
    cursor = ""
    consecutive_old = 0
    while True:
        success, msg, res = api.get_user_note_info(user_id, cursor, xsec_token, xsec_source)
        if not success:
            raise RuntimeError(f"获取用户笔记失败: {msg}")
        data = (res or {}).get("data") or {}
        cards = data.get("notes") or []
        for card in cards:
            t = card.get("time") or 0
            if cutoff_ms and t < cutoff_ms:
                consecutive_old += 1
                if consecutive_old >= max_consecutive_old:
                    return
                continue
            consecutive_old = 0
            yield card
        if not cards or not data.get("has_more") or "cursor" not in data:
            return
        cursor = str(data.get("cursor"))
        time.sleep(random.uniform(*page_sleep))


def collect_user(api, conn, user: dict, cfg: dict, run_at: str, errors: list) -> dict:
    uid, name = user["user_id"], user.get("name", user["user_id"])
    cutoff_ms = cfg["settings"]["min_publish_ms"]
    stats = {"name": name, "user_id": uid, "total_seen": 0, "new_notes": 0, "detail_fetched": 0}
    try:
        known = known_note_ids(conn, uid)
        seen_ids = set()
        max_details = cfg["settings"]["max_details_per_user"]
        for card in iter_user_notes(api, user.get("homepage"), cutoff_ms):
            s = _summary_from_card(card, uid)
            nid = s["note_id"]
            if not nid or nid in seen_ids:
                continue
            seen_ids.add(nid)
            stats["total_seen"] += 1
            is_new = nid not in known
            # 新笔记拉详情；已有但缺详情的笔记（历史回填）也补
            if (is_new or not known.get(nid)) and stats["detail_fetched"] < max_details:
                time.sleep(random.uniform(*cfg["settings"]["detail_sleep"]))
                ok, dmsg, res = api.get_note_info(s["note_url"])
                if ok:
                    item = (res or {}).get("data", {}).get("items", [{}])[0]
                    s.update(_detail_from_note_info(item))
                    s["raw"] = item
                    stats["detail_fetched"] += 1
                else:
                    logger.warning(f"详情拉取失败 {nid}: {dmsg}")
                    errors.append(f"[{name}] 详情失败 {nid}: {dmsg}")
            if not s.get("cobrand"):
                s["cobrand"] = detect_cobrand(s["title"], s.get("desc", ""), s.get("tags", ""))
            upsert_note(conn, s, detail_fetched="desc" in s)
            insert_metrics(conn, nid, s["liked_count"], s["collected_count"],
                           s["comment_count"], s["share_count"])
            if is_new:
                stats["new_notes"] += 1
        conn.commit()
    except Exception as e:
        logger.error(f"[{name}] 采集异常: {e}")
        errors.append(f"[{name}] {e}")
    return stats


def sweep_unfetched(api, conn, cfg, max_notes: int = 0) -> int:
    """补齐缺失/损坏的笔记详情：
    1) detail_fetched=0（清单外被删除/隐藏的笔记）
    2) detail_fetched=1 但 detail_json 被列表卡覆盖损坏的（历史 bug 修复）
    联名笔记优先。循环执行直到无进展或达到 max_notes 上限（0=不限）。
    """
    total_ok = 0
    attempted: set = set()
    while True:
        rows = conn.execute(
            """SELECT note_id, note_url FROM notes
               WHERE (detail_fetched=0 OR detail_json IS NULL OR detail_json NOT LIKE '%note_card%')
                 AND note_url != ''
               ORDER BY CASE WHEN cobrand != '' THEN 0 ELSE 1 END, note_id
               LIMIT 500""").fetchall()
        rows = [r for r in rows if r["note_id"] not in attempted]
        if not rows:
            break
        ok_in_pass = 0
        for r in rows:
            if max_notes and total_ok >= max_notes:
                return total_ok
            time.sleep(random.uniform(*cfg["settings"]["detail_sleep"]))
            ok, msg, res = api.get_note_info(r["note_url"])
            attempted.add(r["note_id"])
            if not ok:
                logger.warning(f"[sweep] 详情失败 {r['note_id']}: {msg}")
                continue
            item = (res or {}).get("data", {}).get("items", [{}])[0]
            d = _detail_from_note_info(item)
            conn.execute(
                """UPDATE notes SET desc=?, tags=?, ip_location=?, liked_count=?, collected_count=?,
                     comment_count=?, share_count=?, detail_fetched=1, detail_json=?,
                     cobrand=COALESCE(NULLIF(?,''), cobrand) WHERE note_id=?""",
                (d["desc"], d["tags"], d["ip_location"], d["liked_count"], d["collected_count"],
                 d["comment_count"], d["share_count"],
                 json.dumps(item, ensure_ascii=False), d["cobrand"], r["note_id"]))
            insert_metrics(conn, r["note_id"], d["liked_count"], d["collected_count"],
                           d["comment_count"], d["share_count"])
            total_ok += 1
            ok_in_pass += 1
        conn.commit()
        logger.info(f"[sweep] 本轮补齐 {ok_in_pass}/{len(rows)} 篇")
        if ok_in_pass == 0:
            break
    logger.info(f"[sweep] 完成，共补齐 {total_ok} 篇")
    return total_ok


def collect_all(api, cfg: dict) -> dict:
    run_at = now()
    start = time.time()
    conn = connect()
    errors = []
    stats_list = []
    cookie_expired = False
    for i, user in enumerate(cfg["users"]):
        if i > 0 and not cookie_expired:
            time.sleep(random.uniform(*cfg["settings"]["user_sleep"]))
        stats_list.append(collect_user(api, conn, user, cfg, run_at, errors))
        logger.info(f"[{user.get('name')}] 完成: {stats_list[-1]}")
        if any("登录已过期" in e for e in errors):
            cookie_expired = True
            errors.append("检测到登录态失效，本轮剩余账号已跳过")
            break
    duration = time.time() - start
    total_new = sum(s["new_notes"] for s in stats_list)
    from .db import record_run
    record_run(conn, run_at, "ok" if not errors else "partial", total_new,
               len(cfg["users"]), "; ".join(errors)[:2000], duration)
    conn.close()
    return {
        "run_at": run_at,
        "stats": stats_list,
        "new_total": total_new,
        "errors": errors,
        "cookie_expired": cookie_expired,
        "duration_s": round(duration, 1),
    }
