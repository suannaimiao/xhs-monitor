import os
from pathlib import Path

from dotenv import load_dotenv
import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

NOTE_URL_TPL = "https://www.xiaohongshu.com/explore/{note_id}?xsec_token={token}&xsec_source=pc_user"


def load_config():
    load_dotenv(BASE_DIR / ".env")
    with open(BASE_DIR / "watchlist.yaml", encoding="utf-8") as f:
        wl = yaml.safe_load(f)
    settings = wl.get("settings") or {}
    users = wl.get("users") or []
    for u in users:
        u.setdefault("homepage", f"https://www.xiaohongshu.com/user/profile/{u['user_id']}")
    cfg = {
        "cookies": os.getenv("COOKIES", "").strip(),
        "smtp": {
            "host": os.getenv("SMTP_HOST", ""),
            "port": int(os.getenv("SMTP_PORT", "465")),
            "user": os.getenv("SMTP_USER", ""),
            "pass": os.getenv("SMTP_PASS", ""),
            "to": [x.strip() for x in os.getenv("MAIL_TO", "").split(",") if x.strip()],
        },
        "settings": {
            "max_details_per_user": int(settings.get("max_details_per_user", 30)),
            "detail_sleep": settings.get("detail_sleep", [5, 15]),
            "user_sleep": settings.get("user_sleep", [30, 60]),
            "download_media": bool(settings.get("download_media", False)),
            "always_mail": bool(settings.get("always_mail", True)),
        },
        "users": users,
    }
    return cfg


def ensure_dirs():
    for p in (DATA_DIR, DATA_DIR / "excel", DATA_DIR / "notes", DATA_DIR / "reports", LOGS_DIR):
        p.mkdir(parents=True, exist_ok=True)
