import random
import time
from datetime import datetime

from loguru import logger

from apis.xhs_pc_apis import XHS_Apis
from xhs_utils.xhs_pc import XHSPcAuth

from .config import NOTE_URL_TPL
from .db import connect, insert_metrics, known_note_ids, now, upsert_note


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
        "liked_count": int(str(interact.get("liked_count", "0")).replace(",", "") or 0),
        "collected_count": int(str(interact.get("collected_count", "0")).replace(",", "") or 0),
        "comment_count": int(str(interact.get("comment_count", "0")).replace(",", "") or 0),
        "share_count": int(str(interact.get("share_count", "0")).replace(",", "") or 0),
        "note_url": NOTE_URL_TPL.format(note_id=card.get("note_id") or card.get("id"),
                                        token=card.get("xsec_token", "")),
        "cover_url": cover,
        "raw": card,
    }


def _detail_from_note_info(item: dict) -> dict:
    nc = item.get("note_card") or {}
    interact = nc.get("interact_info") or {}

    def _int(v):
        try:
            return int(str(v).replace(",", ""))
        except (ValueError, TypeError):
            return 0

    return {
        "title": (nc.get("title") or "").strip() or "无标题",
        "desc": nc.get("desc", ""),
        "note_type": "图集" if nc.get("type") == "normal" else "视频",
        "liked_count": _int(interact.get("liked_count")),
        "collected_count": _int(interact.get("collected_count")),
        "comment_count": _int(interact.get("comment_count")),
        "share_count": _int(interact.get("share_count")),
        "ip_location": nc.get("ip_location", "未知"),
        "tags": ",".join(t["name"] for t in (nc.get("tag_list") or []) if isinstance(t, dict) and t.get("name")),
        "publish_time": nc.get("time"),
    }


def collect_user(api, conn, user: dict, cfg: dict, run_at: str, errors: list) -> dict:
    uid, name = user["user_id"], user.get("name", user["user_id"])
    homepage = user.get("homepage", f"https://www.xiaohongshu.com/user/profile/{uid}")
    stats = {"name": name, "user_id": uid, "total_seen": 0, "new_notes": 0, "detail_fetched": 0}
    try:
        success, msg, cards = api.get_user_all_notes(homepage)
        if not success:
            raise RuntimeError(f"获取用户笔记失败: {msg}")
        stats["total_seen"] = len(cards)
        known = known_note_ids(conn, uid)
        seen_ids = set()
        max_details = cfg["settings"]["max_details_per_user"]

        for card in cards:
            s = _summary_from_card(card, uid)
            nid = s["note_id"]
            if not nid or nid in seen_ids:
                continue
            seen_ids.add(nid)
            is_new = nid not in known
            if is_new and stats["detail_fetched"] < max_details:
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
            upsert_note(conn, s, detail_fetched=is_new and "desc" in s)
            insert_metrics(conn, nid, s["liked_count"], s["collected_count"],
                           s["comment_count"], s["share_count"])
            if is_new:
                stats["new_notes"] += 1
        conn.commit()
    except Exception as e:
        logger.error(f"[{name}] 采集异常: {e}")
        errors.append(f"[{name}] {e}")
    return stats


def collect_all(api, cfg: dict) -> dict:
    run_at = now()
    start = time.time()
    conn = connect()
    errors = []
    stats_list = []
    for i, user in enumerate(cfg["users"]):
        if i > 0:
            time.sleep(random.uniform(*cfg["settings"]["user_sleep"]))
        stats_list.append(collect_user(api, conn, user, cfg, run_at, errors))
        logger.info(f"[{user.get('name')}] 完成: {stats_list[-1]}")
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
        "duration_s": round(duration, 1),
    }
