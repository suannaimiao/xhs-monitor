"""为指定笔记下载媒体（图片/视频/文案）并打包 zip。"""
import io
import json
import zipfile
from pathlib import Path

import requests
from loguru import logger

try:
    from PIL import Image
except ImportError:
    Image = None

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
           "Referer": "https://www.xiaohongshu.com/"}
VIDEO_MAX_BYTES = 30 * 1024 * 1024  # 单视频超 30MB 跳过，避免邮件超限
IMG_MAX_SIDE = 1080


def _shrink(data: bytes) -> bytes:
    """图片压到最长边 1080px、JPEG q80，控制 zip 体积以便邮件发送。"""
    if Image is None or len(data) < 300 * 1024:
        return data
    try:
        img = Image.open(io.BytesIO(data))
        if max(img.size) > IMG_MAX_SIDE:
            img.thumbnail((IMG_MAX_SIDE, IMG_MAX_SIDE))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=80)
        return buf.getvalue()
    except Exception:
        return data


def _extract_media(detail_json: str) -> tuple[list, str]:
    """从详情 JSON 提取图片 URL 列表与视频地址。"""
    try:
        item = json.loads(detail_json)
    except (TypeError, ValueError):
        return [], ""
    nc = item.get("note_card") or {}
    urls = []
    for img in nc.get("image_list") or []:
        u = (img.get("url_default") or (img.get("info_list") or [{}])[-1].get("url"))
        if u and u not in urls:
            urls.append(u)
    video_addr = ""
    streams = (nc.get("video") or {}).get("media", {}).get("stream", {}).get("h264", [])
    if streams:
        video_addr = streams[0].get("master_url") or streams[0].get("url") or ""
    return urls, video_addr


def _download(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return r.content
    except Exception as e:
        logger.warning(f"媒体下载失败 {url[:80]}: {e}")
        return None


def build_zip(notes: list, zip_path: Path, conn=None) -> Path:
    """notes: 含 note_id/title/desc/tags/cobrand/detail_json/note_type 的 dict 列表。"""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for n in notes:
            folder = f"{n['note_id']}_{(n['title'] or '无标题')[:20]}/"
            text = (f"标题：{n['title'] or '无标题'}\n"
                    f"账号：{n.get('nickname') or ''}\n"
                    f"发布时间：{n.get('publish_time') or ''}\n"
                    f"数据：赞 {n.get('liked_count', 0)} / 藏 {n.get('collected_count', 0)} / "
                    f"评 {n.get('comment_count', 0)} / 分享 {n.get('share_count', 0)}\n"
                    f"联名：{n.get('cobrand') or '无'}\n"
                    f"话题：{n.get('tags') or '无'}\n"
                    f"链接：{n.get('note_url') or ''}\n\n"
                    f"正文：\n{n.get('desc') or '（详情未抓取）'}\n")
            zf.writestr(folder + "文案.txt", text)
            urls, video_addr = _extract_media(n.get("detail_json"))
            for i, u in enumerate(urls, 1):
                data = _download(u)
                if data:
                    ext = ".webp" if ".webp" in u else (".png" if ".png" in u else ".jpg")
                    zf.writestr(f"{folder}images/{i:02d}{ext}", _shrink(data))
            if video_addr:
                head = requests.head(video_addr, headers=HEADERS, timeout=15)
                size = int(head.headers.get("Content-Length", 0))
                if size <= VIDEO_MAX_BYTES:
                    data = _download(video_addr)
                    if data:
                        zf.writestr(f"{folder}video.mp4", data)
                else:
                    logger.info(f"视频过大跳过 ({size/1048576:.0f}MB): {n['note_id']}")
    return zip_path
