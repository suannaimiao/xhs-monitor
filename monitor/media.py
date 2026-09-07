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


def _iter_note_files(notes: list):
    """逐笔记产出 (arcname, bytes)，含文案、图片（压缩）、视频。"""
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
        yield folder + "文案.txt", text.encode("utf-8")
        urls, video_addr = _extract_media(n.get("detail_json"))
        for i, u in enumerate(urls, 1):
            data = _download(u)
            if data:
                ext = ".webp" if ".webp" in u else (".png" if ".png" in u else ".jpg")
                yield f"{folder}images/{i:02d}{ext}", _shrink(data)
        if video_addr:
            try:
                head = requests.head(video_addr, headers=HEADERS, timeout=15)
                size = int(head.headers.get("Content-Length", 0))
                if size <= VIDEO_MAX_BYTES:
                    data = _download(video_addr)
                    if data:
                        yield f"{folder}video.mp4", data
                else:
                    logger.info(f"视频过大跳过 ({size/1048576:.0f}MB): {n['note_id']}")
            except Exception as e:
                logger.warning(f"视频获取失败 {n['note_id']}: {e}")


def build_zip(notes: list, zip_path: Path, conn=None) -> Path:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for arc, data in _iter_note_files(notes):
            zf.writestr(arc, data)
    return zip_path


def build_zip_parts(notes: list, out_dir: Path, base_name: str, max_part_mb: int = 38) -> list[Path]:
    """分卷打包：每卷不超过 max_part_mb，适配邮箱附件上限。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    limit = max_part_mb * 1024 * 1024
    parts, idx, cur_size = [], 1, 0
    zf = None
    for arc, data in _iter_note_files(notes):
        if zf is None or cur_size + len(data) > limit:
            if zf is not None:
                zf.close()
                parts[-1] = (parts[-1][0], parts[-1][1])
            path = out_dir / f"{base_name}_part{idx:02d}.zip"
            zf = zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED)
            parts.append((path, 0))
            idx += 1
            cur_size = 0
        zf.writestr(arc, data)
        cur_size += len(data)
        parts[-1] = (parts[-1][0], cur_size)
    if zf is not None:
        zf.close()
    return [p for p, _ in parts]
