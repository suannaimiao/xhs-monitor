"""登录小红书并把 Cookie 自动写入 .env。

用法：
  uv run python -m monitor.login            # 手机号 + 短信验证码登录
  uv run python -m monitor.login --qrcode   # 终端二维码，小红书 App 扫码登录
"""
import argparse

from loguru import logger

from xhs_utils.xhs_pc import XHSPcAuth

from .config import BASE_DIR


def update_env_cookies(cookie: str):
    env_path = BASE_DIR / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    out, replaced = [], False
    for line in lines:
        if line.startswith("COOKIES="):
            out.append(f"COOKIES='{cookie}'")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"COOKIES='{cookie}'")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return env_path


def main():
    parser = argparse.ArgumentParser(description="登录小红书并保存 Cookie")
    parser.add_argument("--qrcode", action="store_true", help="终端二维码扫码登录（默认手机验证码）")
    args = parser.parse_args()

    print("正在初始化登录环境（本地签名计算，无需浏览器）...")
    if args.qrcode:
        auth = XHSPcAuth.from_qrcode_login(show_in_terminal=True)
    else:
        auth = XHSPcAuth.from_phone_login()

    cookie = auth.cookies
    if not cookie or "web_session" not in cookie:
        raise RuntimeError("登录未取得有效 Cookie")
    env_path = update_env_cookies(cookie)
    logger.success(f"登录成功，Cookie 已写入 {env_path}（web_session 已包含）")


if __name__ == "__main__":
    main()
