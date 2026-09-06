"""历史数据回填：反复执行增量采集，直到 2026-01-01 以来的笔记详情补满或达到轮次上限。

用法：uv run python -m monitor.backfill [轮次上限，默认 3]
每轮结束打印进度，完成后生成看板。
"""
import sys

from loguru import logger

from .collect import build_api, collect_all, health_check
from .config import ensure_dirs, load_config
from .dashboard import build_dashboard
from .db import connect, init_db
from .mailer import send_alert


def remaining_details(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM notes WHERE detail_fetched=0"
    ).fetchone()[0]


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    ensure_dirs()
    init_db()
    cfg = load_config()
    api = build_api(cfg)
    ok, msg = health_check(api)
    logger.info(f"健康检查: {ok}, {msg}")
    if not ok:
        sys.exit(2)

    conn = connect()
    for i in range(1, rounds + 1):
        conn = connect()
        left_before = remaining_details(conn)
        conn.close()
        if left_before == 0:
            logger.info("全部笔记详情已补满，提前结束")
            break
        logger.info(f"===== 回填第 {i}/{rounds} 轮（剩余待补详情 {left_before} 篇）=====")
        result = collect_all(api, cfg)
        logger.info(f"第 {i} 轮完成: 新增 {result['new_total']}, 详情 {sum(s['detail_fetched'] for s in result['stats'])}, 异常 {len(result['errors'])}")
        if result.get("cookie_expired"):
            send_alert(cfg, "Cookie 已过期，采集已停止",
                       "监测到小红书登录态失效（接口返回：登录已过期）。\n\n"
                       "请在项目目录执行：\n"
                       "  cd /home/yefu/xhs-monitor\n"
                       "  uv run python -m monitor.login\n\n"
                       "登录后运行 uv run python -m monitor.backfill 可继续补齐详情。")
            break
    conn.close()
    path = build_dashboard(cfg)
    logger.success(f"回填结束，看板已生成: {path}")


if __name__ == "__main__":
    main()
