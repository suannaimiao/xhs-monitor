import smtplib
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

from loguru import logger

from .config import BASE_DIR


def _connect_smtp(cfg):
    smtp = smtplib.SMTP_SSL(cfg["smtp"]["host"], cfg["smtp"]["port"], timeout=120)
    smtp.login(cfg["smtp"]["user"], cfg["smtp"]["pass"])
    return smtp


def _attach(msg: MIMEMultipart, path: Path):
    if not path or not Path(path).exists():
        return
    with open(path, "rb") as f:
        part = MIMEApplication(f.read())
    part.add_header("Content-Disposition", "attachment",
                    filename=Header(Path(path).name, "utf-8").encode())
    msg.attach(part)


def _send(cfg, subject: str, html: str, attachments=None):
    if not (cfg["smtp"]["host"] and cfg["smtp"]["user"] and cfg["smtp"]["pass"] and cfg["smtp"]["to"]):
        logger.warning("SMTP 未配置完整，跳过邮件发送")
        return False
    msg = MIMEMultipart("related")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr(("XHS竞品监测", cfg["smtp"]["user"]))
    msg["To"] = ",".join(cfg["smtp"]["to"])
    msg.attach(MIMEText(html, "html", "utf-8"))
    for p in attachments or []:
        _attach(msg, p)
    with _connect_smtp(cfg) as smtp:
        smtp.sendmail(cfg["smtp"]["user"], cfg["smtp"]["to"], msg.as_string())
    logger.info(f"邮件已发送: {subject} -> {cfg['smtp']['to']}")
    return True


def send_report(cfg, subject: str, html: str, *attachments):
    return _send(cfg, subject, html, list(attachments))


def send_alert(cfg, title: str, detail: str):
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(BASE_DIR / "monitor" / "templates"))
    html = env.get_template("alert.html.j2").render(title=title, detail=detail)
    return _send(cfg, f"[告警] XHS竞品监测: {title}", html)
