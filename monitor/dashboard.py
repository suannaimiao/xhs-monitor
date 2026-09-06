import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .config import BASE_DIR, DATA_DIR

TEMPLATE_DIR = BASE_DIR / "monitor" / "templates"


def _collect_dashboard_data(conn) -> dict:
    accounts = [
        {"user_id": r["user_id"], "nickname": r["nickname"] or r["user_id"][:8],
         "total": r["total"], "cobrand": r["cobrand_cnt"]}
        for r in conn.execute(
            """SELECT user_id, MAX(nickname) AS nickname, COUNT(*) AS total,
                 SUM(CASE WHEN cobrand != '' THEN 1 ELSE 0 END) AS cobrand_cnt
               FROM notes GROUP BY user_id ORDER BY total DESC"""
        ).fetchall()
    ]
    notes = []
    for r in conn.execute(
        """SELECT note_id, user_id, nickname, title, desc, note_type, publish_time, tags,
             note_url, cover_url, liked_count, collected_count, comment_count, share_count,
             detail_fetched, cobrand, first_seen_at
           FROM notes ORDER BY publish_time DESC"""
    ).fetchall():
        notes.append({
            "id": r["note_id"],
            "uid": r["user_id"],
            "nickname": r["nickname"] or "",
            "title": (r["title"] or "")[:80],
            "desc": (r["desc"] or "")[:500],
            "type": r["note_type"],
            "time": r["publish_time"] or 0,
            "tags": r["tags"] or "",
            "url": r["note_url"],
            "cover": r["cover_url"] or "",
            "liked": r["liked_count"], "collected": r["collected_count"],
            "comments": r["comment_count"], "shares": r["share_count"],
            "detail": bool(r["detail_fetched"]),
            "cobrand": r["cobrand"] or "",
            "first_seen": r["first_seen_at"],
        })
    return {"accounts": accounts, "notes": notes}


def build_dashboard(cfg=None) -> Path:
    from .db import connect
    conn = connect()
    data = _collect_dashboard_data(conn)
    conn.close()
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    html = env.get_template("dashboard.html.j2").render(data=json.dumps(data, ensure_ascii=False))
    path = DATA_DIR / "dashboard.html"
    path.write_text(html, encoding="utf-8")
    return path
