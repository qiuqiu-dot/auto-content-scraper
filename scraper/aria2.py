# -*- coding: utf-8 -*-
"""aria2 多线程下载模块。

支持：
- 普通 HTTP/HTTPS/FTP 下载（aria2c 分段）
- 迅雷链接解码（thunder://）
- yt-dlp 视频/音频下载
- 兜底单线程下载
"""
from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import subprocess
from typing import List, Optional
from urllib.parse import urlparse, unquote


def aria2_available() -> bool:
    return shutil.which("aria2c") is not None


def ytdlp_available() -> bool:
    return shutil.which("yt-dlp") is not None


def gh_available() -> bool:
    return shutil.which("gh") is not None


def decode_thunder_url(thunder_url: str) -> Optional[str]:
    """解码迅雷链接 thunder://... 返回真实 URL。"""
    if not thunder_url.startswith("thunder://"):
        return None
    try:
        # 去掉前缀
        encoded = thunder_url[10:]
        # 补齐 Base64 padding
        encoded += "=" * (-len(encoded) % 4)
        decoded = base64.b64decode(encoded).decode("utf-8", errors="ignore")
        # 迅雷链接格式通常是: [真实URL] 或 AA[真实URL]ZZ
        if decoded.startswith("AA") and decoded.endswith("ZZ"):
            decoded = decoded[2:-2]
        return decoded
    except Exception:
        return None


def is_thunder_url(url: str) -> bool:
    return url.startswith("thunder://")


def pick_filename(url: str, content_disposition: str = "") -> str:
    """从 URL 或 Content-Disposition 推测保存文件名。"""
    if content_disposition:
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disposition, re.I)
        if m:
            return unquote(m.group(1).strip())
    path = urlparse(url).path
    base = os.path.basename(path)
    if base and "." in base:
        return unquote(base)
    nm = urlparse(url).netloc.replace("/", "_")
    return nm or "download"


def is_downloadable_url(url: str) -> bool:
    """判断一个 URL 是否像是可下载文件（通过扩展名）。"""
    if is_thunder_url(url):
        # 解码后再判断
        real = decode_thunder_url(url)
        if real:
            return is_downloadable_url(real)
        return True  # 无法解码也当作可下载
    p = unquote(urlparse(url).path).lower()
    exts = (".exe", ".msi", ".apk", ".dmg", ".pkg", ".deb", ".rpm", ".zip",
            ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".iso", ".dll",
            ".whl", ".bin", ".run", ".jar", ".msu", ".img", ".snap", ".ova",
            ".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".ts", ".m3u8",
            ".zip.001", ".apk.1", ".part")
    return p.endswith(exts)


def find_download_links(rows: list) -> List[dict]:
    """从结果行里抽取出所有可下载的链接，供下载使用。"""
    out = []
    for r in rows:
        for dl in r.get("download_links", []):
            u = dl.get("url", "")
            if is_downloadable_url(u):
                out.append({"url": u, "text": dl.get("text", "") or u,
                            "netloc": r.get("netloc", "")})
    # 去重
    seen = set()
    uniq = []
    for d in out:
        if d["url"] in seen:
            continue
        seen.add(d["url"])
        uniq.append(d)
    return uniq


def download_with_aria2(
    url: str,
    threads: int = 8,
    outdir: str = "downloads",
    filename: str = "",
    extra_args: List[str] = None,
) -> dict:
    """用 aria2c 多线程下载单个 URL。支持迅雷链接自动解码。"""
    os.makedirs(outdir, exist_ok=True)
    # 处理迅雷链接
    real_url = url
    if is_thunder_url(url):
        decoded = decode_thunder_url(url)
        if decoded:
            real_url = decoded
    filename = filename or pick_filename(real_url)
    cmd = ["aria2c",
           "-x", str(threads),
           "-s", str(threads),
           "--file-allocation=none",
           "--continue=true",
           "--allow-overwrite=true",
           "--dir", outdir,
           "--out", filename,
           ]
    if extra_args:
        cmd += extra_args
    cmd.append(real_url)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600
        )
        ok = proc.returncode == 0
        tail = (proc.stderr or proc.stdout or "").strip()
        if proc.returncode == 3:
            ok = True
        return {"ok": ok, "file": os.path.join(outdir, filename),
                "detail": tail[-400:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "file": os.path.join(outdir, filename),
                "detail": "aria2c 超时(10分钟)"}
    except FileNotFoundError:
        return {"ok": False, "file": os.path.join(outdir, filename),
                "detail": "aria2c 未安装"}


def download_with_ytdlp(
    url: str,
    outdir: str = "downloads",
    format_spec: str = "bestvideo+bestaudio/best",
    extra_args: List[str] = None,
) -> dict:
    """用 yt-dlp 下载视频/音频。"""
    os.makedirs(outdir, exist_ok=True)
    cmd = ["yt-dlp",
           "-f", format_spec,
           "-o", os.path.join(outdir, "%(title)s.%(ext)s"),
           "--no-playlist",
           "--continue",
           "--no-overwrites",
           ]
    if extra_args:
        cmd += extra_args
    cmd.append(url)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1800
        )
        ok = proc.returncode == 0
        tail = (proc.stderr or proc.stdout or "").strip()
        # 尝试从输出中提取文件名
        file_path = ""
        for line in tail.split("\n"):
            if "[Merger] Merging formats into" in line or "Destination:" in line:
                file_path = line.split(":", 1)[-1].strip().strip('"')
                break
        return {"ok": ok, "file": file_path or outdir,
                "detail": tail[-500:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "file": outdir, "detail": "yt-dlp 超时(30分钟)"}
    except FileNotFoundError:
        return {"ok": False, "file": outdir, "detail": "yt-dlp 未安装"}


def download_fallback(url: str, threads: int, outdir: str, filename: str = "") -> dict:
    """aria2c 不可用时的兜底下载（流式写文件，支持断点续传）。"""
    import requests
    os.makedirs(outdir, exist_ok=True)
    real_url = url
    if is_thunder_url(url):
        decoded = decode_thunder_url(url)
        if decoded:
            real_url = decoded
    filename = filename or pick_filename(real_url)
    fp = os.path.join(outdir, filename)
    partial = fp + ".part"
    try:
        resume_at = os.path.getsize(partial) if os.path.exists(partial) else 0
        headers = {"User-Agent": "Mozilla/5.0", "Range": f"bytes={resume_at}-"}
        with requests.get(real_url, headers=headers, stream=True, timeout=30) as r:
            if r.status_code == 200:
                resume_at = 0
            elif r.status_code != 206:
                r.raise_for_status()
            mode = "ab" if r.status_code == 206 and resume_at else "wb"
            with open(partial, mode) as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if chunk:
                        f.write(chunk)
        os.replace(partial, fp)
        return {"ok": True, "file": fp, "detail": "fallback(单线程)完成"}
    except Exception as e:
        return {"ok": False, "file": fp, "detail": f"fallback失败: {str(e)[:120]}"}


def batch_download(
    links: List[str],
    threads: int = 8,
    outdir: str = "downloads",
    verbose: bool = True,
    use_ytdlp: bool = False,
    ytdlp_format: str = "bestvideo+bestaudio/best",
) -> List[dict]:
    """批量下载一批链接，自动选择下载器。"""
    results = []
    has_aria2 = aria2_available()
    has_ytdlp = ytdlp_available()
    if not has_aria2 and verbose:
        print("  [!] 未检测到 aria2c，使用 Python 内置单线程下载；"
              "建议 `pkg install aria2` 或 `apt install aria2`。")
    if use_ytdlp and not has_ytdlp and verbose:
        print("  [!] 未检测到 yt-dlp，视频链接将尝试用 aria2c/兜底下载；"
              "建议 `pip install yt-dlp` 或 `pkg install yt-dlp`。")
    for i, ln in enumerate(links, 1):
        if verbose:
            print(f"  [{i}/{len(links)}] 下载 {ln[:70]} ...", flush=True)
        # 判断是否为视频链接（yt-dlp 支持的站点）
        is_video = use_ytdlp and has_ytdlp and _looks_like_video_url(ln)
        if is_video:
            res = download_with_ytdlp(ln, outdir=outdir)
        elif has_aria2:
            res = download_with_aria2(ln, threads=threads, outdir=outdir)
        else:
            res = download_fallback(ln, threads=threads, outdir=outdir)
        if verbose:
            flag = "✅" if res["ok"] else "❌"
            print(f"      {flag} {res['file']} | {res['detail'][:80]}")
        results.append(res)
    return results


def _looks_like_video_url(url: str) -> bool:
    """简单判断是否为 yt-dlp 支持的视频链接。"""
    video_domains = ("youtube.com", "youtu.be", "bilibili.com", "b23.tv",
                     "vimeo.com", "twitch.tv", "douyin.com", "tiktok.com",
                     "ixigua.com", "kuaishou.com", "weibo.com", "twitter.com",
                     "x.com", "instagram.com", "facebook.com")
    parsed = urlparse(url)
    return any(d in parsed.netloc for d in video_domains) or \
           url.endswith((".m3u8", ".mpd", ".ts"))


# 向后兼容：保留旧函数签名
def batch_download_legacy(
    links: List[str],
    threads: int = 8,
    outdir: str = "downloads",
    verbose: bool = True,
) -> List[dict]:
    return batch_download(links, threads, outdir, verbose, use_ytdlp=False)
