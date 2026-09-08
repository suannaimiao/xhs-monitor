"""限频友好的详情修复：每次运行最多补 50 篇，配合 cron 每 30 分钟执行。

用法：uv run python -m monitor.repair_once
完成（无待修复）时自动退出；Cookie 过期/持续限频发告警邮件。
"""
import time

from loguru import logger

from .collect import _fetch_detail, build_api, sweep_unfetched
from .config import ensure_dirs, load_config
from .db import connect, init_db
from .mailer import send_alert

BATCH = 50


def remaining(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM notes WHERE detail_fetched=0 "
        "OR detail_json IS NULL OR detail_json NOT LIKE '%note_card%'").fetchone()[0]


def main():
    ensure_dirs()
    init_db()
    cfg = load_config()
    conn = connect()
    left = remaining(conn)
    if left == 0:
        logger.info("无待修复详情，退出")
        return
    try:
        api = build_api(cfg)
    except Exception as e:
        send_alert(cfg, "Cookie 已过期（修复任务）", str(e))
        raise SystemExit(2)

    # 单篇探测：Cookie 失效或仍限频则本次直接放弃
    row = conn.execute(
        "SELECT note_url FROM notes WHERE detail_fetched=0 "
        "OR detail_json IS NULL OR detail_json NOT LIKE '%note_card%' LIMIT 1").fetchone()
    try:
        item, err = _fetch_detail(api, row["note_url"])
    except RuntimeError as e:
        send_alert(cfg, "Cookie 已过期（修复任务）", str(e))
        raise SystemExit(2)
    if item is None:
        logger.info(f"本次跳过（{err}），等待下个周期")
        return

    fixed = sweep_unfetched(api, conn, cfg, max_notes=BATCH)
    left = remaining(conn)
    logger.info(f"本次修复 {fixed} 篇，剩余 {left} 篇")
    if left == 0:
        send_alert(cfg, "全部笔记详情修复完成", "所有笔记的正文/图片地址已全部重建，看板已更新。")
        from .dashboard import build_dashboard
        build_dashboard()


if __name__ == "__main__":
    main()
