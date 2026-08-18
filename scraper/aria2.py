# -*- coding: utf-8 -*-
"""aria2 多线程下载模块。

把抓取到的下载链接交给 aria2c 分段下载（-x / -s 设置并发线程数）。
若系统未安装 aria2c，则自动退化为 Python 内置的断点/单线程下载，并给出提示。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import List
from urllib.parse import urlparse, unquote


def aria2_available() -> bool:
    return shutil.which("aria2c") is not None


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
    # 兜底：用 netloc+query hash
    nm = urlparse(url).netloc.replace("/", "_")
    return nm or "download"


def is_downloadable_url(url: str) -> bool:
    """判断一个 URL 是否像是可下载文件（通过扩展名）。"""
    p = unquote(urlparse(url).path).lower()
    exts = (".exe", ".msi", ".apk", ".dmg", ".pkg", ".deb", ".rpm", ".zip",
            ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".iso", ".dll",
            ".whl", ".bin", ".run", ".jar", ".msu", ".img", ".snap", ".ova",
            ".mp4", ".zip.001")
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
    """用 aria2c 多线程下载单个 URL。返回 (stdout 摘要, 是否成功)。"""
    os.makedirs(outdir, exist_ok=True)
    filename = filename or pick_filename(url)
    cmd = ["aria2c",
           "-x", str(threads),      # 每服务器允许的并发连接数
           "-s", str(threads),      # 每文件拆分段数
           "--file-allocation=none",
           "--continue=true",
           "--allow-overwrite=true",
           "--dir", outdir,
           "--out", filename,
           ]
    if extra_args:
        cmd += extra_args
    cmd.append(url)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600
        )
        ok = proc.returncode == 0
        tail = (proc.stderr or proc.stdout or "").strip()
        # aria2c 返回 0 表示全部完成；3 表示部分完成但可用
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


def download_fallback(url: str, threads: int, outdir: str, filename: str = "") -> dict:
    """aria2c 不可用时的兜底下载（流式写文件，支持断点续传）。"""
    import requests
    os.makedirs(outdir, exist_ok=True)
    filename = filename or pick_filename(url)
    fp = os.path.join(outdir, filename)
    partial = fp + ".part"
    try:
        resume_at = os.path.getsize(partial) if os.path.exists(partial) else 0
        headers = {"User-Agent": "Mozilla/5.0", "Range": f"bytes={resume_at}-"}
        with requests.get(url, headers=headers, stream=True, timeout=30) as r:
            if r.status_code == 200:
                resume_at = 0  # 服务器不支持断点
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
) -> List[dict]:
    """批量下载一批链接，失败会自动切换 aria2/兜底实现。"""
    results = []
    has_aria2 = aria2_available()
    if not has_aria2 and verbose:
        print("  [!] 未检测到 aria2c，使用 Python 内置单线程下载；"
              "建议 `pkg install aria2` 或 `apt install aria2`。")
    for i, ln in enumerate(links, 1):
        if verbose:
            print(f"  [{i}/{len(links)}] 下载 {ln[:70]} ...", flush=True)
        if has_aria2:
            res = download_with_aria2(ln, threads=threads, outdir=outdir)
        else:
            res = download_fallback(ln, threads=threads, outdir=outdir)
        if verbose:
            flag = "✅" if res["ok"] else "❌"
            print(f"      {flag} {res['file']} | {res['detail'][:80]}")
        results.append(res)
    return results
