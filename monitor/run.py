import argparse
import sys
import traceback

from loguru import logger

from .collect import build_api, collect_all, health_check
from .config import ensure_dirs, load_config, LOGS_DIR
from .db import connect, init_db, new_notes_this_run
from .mailer import send_alert, send_report
from .report import build_excel, build_html, build_hot_notes


def setup_logger():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger.add(LOGS_DIR / "monitor_{time:YYYY-MM-DD}.log", rotation="1 day",
               retention="30 days", encoding="utf-8", level="INFO")


def main():
    parser = argparse.ArgumentParser(description="XHS 竞品监测")
    parser.add_argument("--no-mail", action="store_true", help="只采集不发邮件")
    parser.add_argument("--collect-only", action="store_true", help="只采集，不生成报告")
    args = parser.parse_args()
    setup_logger()
    ensure_dirs()
    init_db()
    cfg = load_config()
    conn = connect()

    try:
        api = build_api(cfg)
        ok, msg = health_check(api)
        logger.info(f"健康检查: {ok}, {msg}")
        if not ok:
            send_alert(cfg, "Cookie 失效，采集已停止", f"健康检查失败：{msg}\n请更新 .env 中的 COOKIES。")
            sys.exit(2)

        result = collect_all(api, cfg)
        result["new_notes"] = new_notes_this_run(conn, result["run_at"])
        logger.info(f"采集完成: 新增 {result['new_total']} 篇, 耗时 {result['duration_s']}s, 异常 {len(result['errors'])}")

        if args.collect_only:
            return
        result["hot_notes"] = build_hot_notes(conn)
        excel_path = build_excel(result, conn)
        html_path = build_html(result, conn)
        logger.info(f"报告已生成: {excel_path}, {html_path}")

        if not args.no_mail and (cfg["settings"]["always_mail"] or result["new_notes"]):
            with open(html_path, encoding="utf-8") as f:
                html = f.read()
            subject = f"【XHS竞品监测】{result['run_at'][:10]} 新增 {result['new_total']} 篇"
            send_report(cfg, subject, html, excel_path, html_path)
        conn.close()
    except SystemExit:
        raise
    except Exception as e:
        logger.exception(f"运行异常: {e}")
        try:
            send_alert(cfg, "运行异常", f"{e}\n\n{traceback.format_exc()[-2000:]}")
        except Exception:
            logger.exception("告警邮件发送失败")
        sys.exit(1)


if __name__ == "__main__":
    main()
