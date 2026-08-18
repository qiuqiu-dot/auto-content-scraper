# -*- coding: utf-8 -*-
"""命令行入口：Bing 搜索 -> 信誉评估 -> 抓取内容 -> 导出报告。"""
from __future__ import annotations

import argparse
import csv
import datetime
import html
import json
import os
import sys
import time
from typing import Dict, List
from urllib.parse import urlparse

# 兼容直接运行脚本与 -m 调用
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scraper.sites as sites
from scraper.bing_search import search_multiple
from scraper.content import extract, is_download_or_resource_site
from scraper.fetch import Fetcher
from scraper.reputation import final_reputation
import scraper.aria2 as aria2

DEFAULT_QUERIES = [
    "优质下载站 软件 绿色免安装 推荐",
    "靠谱 资源站 好用的下载网站 推荐 2025",
    "开源 软件 下载 镜像源 精选",
    "文档 教程 资源站 优质 content 推荐",
    "github 优质 项目 资源 列表 awesome",
]

OUT_DIRNAME = "results"
_RESPECT_ROBOTS = False


def make_outdir(base: str) -> str:
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = os.path.join(base, OUT_DIRNAME, ts)
    os.makedirs(outdir, exist_ok=True)
    return outdir


def build_report_site(row: dict) -> Dict:
    return {
        "title": row["title"],
        "url": row["url"],
        "netloc": row["netloc"],
        "reputation": row["reputation"],
        "whitelist_hit": row["whitelist_hit"],
        "whitelist_note": row["whitelist_note"],
        "text_len": row["text_len"],
        "n_download_links": row["n_download_links"],
        "download_links": row.get("download_links", []),
        "snippet": row.get("snippet", "")[:200],
        "note": row.get("note", ""),
    }


def render_html(title: str, rows: List[dict], meta: dict) -> str:
    """生成自包含 HTML 报告。"""
    cards = []
    for r in rows:
        score = r["reputation"]
        color = "#27ae60" if score >= 70 else ("#f39c12" if score >= 45 else "#e74c3c")
        dl_list = "".join(
            f'<li><a href="{html.escape(x["url"])}" target="_blank" '
            f'rel="noopener">{html.escape(x.get("text") or x["url"])}</a></li>'
            for x in r.get("download_links", [])[:6]
        )
        badges = []
        if r["whitelist_hit"]:
            badges.append('<span class="badge ok">✅ 白名单</span>')
        if r.get("note"):
            badges.append(f'<span class="badge note">{html.escape(r["note"])}</span>')
        badges.append(f'<span class="badge n">{r["text_len"]} 字正文</span>')
        if r["n_download_links"]:
            badges.append(f'<span class="badge d">{r["n_download_links"]} 个下载链接</span>')
        cards.append(f"""
<div class="card">
  <div class="head">
    <span class="score" style="--c:{color}">{score}</span>
    <div class="tinfo">
      <h3><a href="{html.escape(r['url'])}" target="_blank" rel="noopener">{html.escape(r['title'] or r['url'])}</a></h3>
      <div class="netloc">{html.escape(r['netloc'])}</div>
    </div>
  </div>
  <div class="badges">{''.join(badges)}</div>
  <p class="snip">{html.escape(r.get('snippet',''))}</p>
  {f'<ul class="dl">{dl_list}</ul>' if dl_list else ''}
</div>""")
    return f"""<!doctype html>
<html lang="zh">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;margin:24px;background:#fafbfc;color:#222}}
  h1{{font-size:22px}} .sub{{color:#888;margin:4px 0 20px}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}}
  .card{{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.04)}}
  .head{{display:flex;gap:12px;align-items:flex-start}} .score{{font-size:22px;font-weight:800;color:var(--c)}}
  h3{{margin:0 0 2px;font-size:16px}} .netloc{{color:#999;font-size:12px}}
  .badges{{margin:10px 0 6px}} .badge{{display:inline-block;font-size:11px;padding:2px 8px;border-radius:20px;background:#f1f5f9;color:#374151;margin-right:6px}}
  .badge.ok{{background:#dcfce7;color:#166534}} .badge.note{{background:#fef9c3;color:#854d0e}} .badge.d{{background:#ecfdf5;color:#065f46}}
  .snip{{color:#555;font-size:13px;line-height:1.6}} .dl{{font-size:12px;padding-left:18px;margin:8px 0 0;max-height:90px;overflow:auto}}
  footer{{margin-top:24px;color:#999;font-size:12px}}
</style></head>
<body>
<h1>{html.escape(title)}</h1>
<div class="sub">共 {len(rows)} 个站点 · 搜索关键字 {meta.get('queries','')} · 生成于 {meta.get('time','')}</div>
<div class="grid">{''.join(cards)}</div>
<footer>由 Auto Content Scraper 自动生成，请遵守目标站点 robots.txt 与使用条款。</footer>
</body></html>
"""


def gather(
    queries: List[str],
    pages: int,
    max_sites: int,
    min_score: int,
    delay: float,
    timeout: int,
    reputable_only: str,  # 'yes' | 'no' | 'judge'
) -> List[dict]:
    """主流程：搜索 -> 排序候选 -> 抓取评估 -> 返回结果列表。"""
    print("\n[1/3] 开始 Bing 搜索...")
    found = search_multiple(queries, pages=pages, delay=delay * 0.4, timeout=timeout)
    print(f"\n  共收集到 {len(found)} 条候选 URL。")

    # 去重（按 netloc 计数注意不要过度去重，这里按 URL 去重）
    seen_url: set = set()
    cands: List[dict] = []
    for r in found:
        if r.url in seen_url:
            continue
        seen_url.add(r.url)
        cands.append({"title": r.title, "url": r.url, "snippet": r.snippet})

    # 优先白名单站 + 域名计数排序，保证抓取量在控制在 max_sites 内
    cands.sort(key=lambda x: (sites.is_reputable(urlparse(x["url"]).netloc), x["url"]),
               reverse=True)

    # [2/3] 抓取与评估
    import scraper.main as _m
    respect = _m._RESPECT_ROBOTS
    fetcher = Fetcher(delay=delay, timeout=timeout, respect_robots=respect)
    rows: List[dict] = []
    print(f"\n[2/3] 开始抓取评估（最多 {max_sites} 个站点，间隔 {delay}s）...")
    for i, c in enumerate(cands[:max_sites], 1):
        url = c["url"]
        netloc = urlparse(url).netloc
        print(f"  [{i}/{min(max_sites, len(cands))}] 抓取 {netloc} ...", end=" ", flush=True)
        ok, html_text, err = fetcher.get_text(url)
        if not ok:
            print(f"跳过（{err}）")
            continue
        ec = extract(html_text, base_url=url)
        rep = final_reputation(url, ec)
        _, feats = is_download_or_resource_site(ec, url)
        note = sites.summarize(netloc)
        if feats:
            note += "；特征:" + ",".join(feats)

        # 过滤逻辑
        drop = False
        if reputable_only == "yes" and rep.final_score < min_score:
            drop = True
        elif reputable_only == "judge" and rep.final_score < 30:
            drop = True
        if drop:
            print(f"信用分 {rep.final_score}，低于门槛，丢弃。")
            # 仍记录但标记 low
            row = {
                "title": ec.title or c["title"],
                "url": url, "netloc": netloc,
                "snippet": c["snippet"],
                "text_len": ec.text_len,
                "reputation": rep.final_score,
                "whitelist_hit": rep.whitelist_hit,
                "whitelist_note": rep.whitelist_note,
                "n_download_links": len(ec.download_links),
                "download_links": ec.download_links,
                "penalties": rep.penalties,
                "bonuses": rep.bonuses,
                "note": note,
                "status": "low",
            }
            rows.append(row)
            continue
        print(f"信用 {rep.final_score} ✅")
        rows.append({
            "title": ec.title or c["title"],
            "url": url, "netloc": netloc,
            "snippet": c["snippet"],
            "text_len": ec.text_len,
            "reputation": rep.final_score,
            "whitelist_hit": rep.whitelist_hit,
            "whitelist_note": rep.whitelist_note,
            "n_download_links": len(ec.download_links),
            "download_links": ec.download_links,
            "penalties": rep.penalties,
            "bonuses": rep.bonuses,
            "note": note,
            "status": "ok",
        })
        time.sleep(delay * 0.3)

    # [3/3] 排序输出
    rows.sort(key=lambda x: (x["reputation"], x["text_len"]), reverse=True)
    return rows


def fetch_urls_manual(urls: List[str], delay: float, timeout: int) -> List[dict]:
    """不经过搜索，直接抓取用户手动给出的 URL 列表。"""
    fetcher = Fetcher(delay=delay, timeout=timeout)
    rows = []
    print(f"\n手动抓取 {len(urls)} 个 URL...")
    for i, url in enumerate(urls, 1):
        netloc = urlparse(url).netloc
        print(f"  [{i}/{len(urls)}] 抓取 {netloc} ...", end=" ", flush=True)
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        ok, html_text, err = fetcher.get_text(url)
        if not ok:
            print(f"失败（{err}）")
            rows.append({"title": "", "url": url, "netloc": netloc,
                         "snippet": "", "text_len": 0, "reputation": 0,
                         "whitelist_hit": False, "whitelist_note": "",
                         "n_download_links": 0, "download_links": [],
                         "penalties": [err], "bonuses": [], "note": sites.summarize(netloc),
                         "status": "error"})
            continue
        ec = extract(html_text, base_url=url)
        rep = final_reputation(url, ec)
        print(f"信用 {rep.final_score} ✅")
        rows.append({
            "title": ec.title or url, "url": url, "netloc": netloc,
            "snippet": ec.description, "text_len": ec.text_len,
            "text": ec.text if ec.text_len <= 6000 else ec.text[:6000] + "\n…[内容过长已截断]",
            "reputation": rep.final_score, "whitelist_hit": rep.whitelist_hit,
            "whitelist_note": rep.whitelist_note,
            "n_download_links": len(ec.download_links),
            "download_links": ec.download_links,
            "penalties": rep.penalties, "bonuses": rep.bonuses,
            "note": sites.summarize(netloc), "status": "ok",
        })
    rows.sort(key=lambda x: (x["reputation"], x["text_len"]), reverse=True)
    return rows


def print_to_terminal(rows: List[dict], show_text: bool = True) -> None:
    """把抓取结果直接打印到终端（默认输出方式，配合 -f 才落盘）。"""
    print("\n" + "=" * 68)
    print("抓取结果总览")
    print("=" * 68)
    if not rows:
        print("（无结果）")
        return
    for i, r in enumerate(rows, 1):
        netloc = r.get("netloc", "")
        rep = r.get("reputation", 0)
        st = r.get("status", "")
        mark = {"ok": "✅", "low": "⚠️", "error": "❌"}.get(st, "・")
        print(f"\n{'─'*60}")
        print(f"{mark} [{i}] {r.get('title', '')}")
        print(f"    网址 : {r.get('url', '')}")
        print(f"    信用 : {rep}/100  正文 {r.get('text_len', 0)} 字  "
              f"下载链接 {r.get('n_download_links', 0)} 个")
        note = r.get("note", "")
        if note:
            print(f"    备注 : {note}")
        if r.get("download_links"):
            print("    下载链接:")
            for dl in r.get("download_links", [])[:6]:
                print(f"        ↳ {dl.get('url', '')}")
        if show_text:
            txt = (r.get("text") or "").strip()
            if txt:
                print(f"    --- 正文预览（{len(txt)} 字符）---")
                # 每行限宽便于阅读
                import shutil as _sh
                w = _sh.get_terminal_size((100, 24)).columns - 8
                w = max(40, w)
                for ln in txt.split("\n"):
                    while len(ln) > w:
                        print("    " + ln[:w])
                        ln = ln[w:]
                    if ln:
                        print("    " + ln)
    print("\n" + "=" * 68)


def run_downloads(rows: List[dict], threads: int, outdir: str) -> List[dict]:
    """从结果里提取下载链接并用 aria2 批量下载。"""
    links = aria2.find_download_links(rows)
    if not links:
        print("\n[下载] 结果里没有识别到可下载文件链接。")
        print("提示：可以用 --download 直接抓某个下载页，程序会把页内的可下载链接交给 aria2。")
        return []
    print(f"\n[下载] 从结果提取到 {len(links)} 个可下载链接，开始 aria2 多线程下载"
          f"（线程: -x{threads}/-s{threads}）...")
    results = aria2.batch_download(
        [l["url"] for l in links], threads=threads, outdir=outdir
    )
    ok_count = sum(1 for r in results if r["ok"])
    print(f"\n[下载] 完成：成功 {ok_count} / {len(results)}。输出目录: {outdir}")
    return results


def export(rows: List[dict], outdir: str, queries: List[str], title: str):
    print(f"\n[3/3] 导出报告到 {outdir}")
    meta = {"queries": ";".join(queries), "time": datetime.datetime.now().isoformat(
        timespec="seconds")}

    # JSON 全量
    json_path = os.path.join(outdir, "scrape.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "results": rows}, f, ensure_ascii=False, indent=2)
    print(f"  JSON : {json_path}")

    # CSV 摘要
    csv_path = os.path.join(outdir, "scrape.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "reputation", "netloc", "title", "url", "text_len",
            "n_download_links", "whitelist_hit", "whitelist_note", "note"])
        w.writeheader()
        for r in rows:
            w.writerow({
                "reputation": r["reputation"], "netloc": r["netloc"],
                "title": r["title"], "url": r["url"],
                "text_len": r["text_len"], "n_download_links": r["n_download_links"],
                "whitelist_hit": r["whitelist_hit"],
                "whitelist_note": r["whitelist_note"], "note": r["note"],
            })
    print(f"  CSV  : {csv_path}")

    # HTML 报告
    html_path = os.path.join(outdir, "report.html")
    rhtml = render_html(title, rows, meta)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(rhtml)
    print(f"  HTML : {html_path}")
    return {"json": json_path, "csv": csv_path, "html": html_path}


def main():
    p = argparse.ArgumentParser(
        description="自动抓取网上优质下载/资源站内容，支持手动网址抓取与 aria2 多线程下载")
    p.add_argument("--query", "-q", action="append", help="搜索关键字（可多次）")
    p.add_argument("--results", "-r", type=int, default=10, help="每关键字 Bing 结果条数(页)")
    p.add_argument("--max-sites", "-m", type=int, default=20, help="最多抓取评估的站点数")
    # ---- 手动网址抓取 ----
    p.add_argument("--url", action="append", help="手动要抓取的网址（可多次，或 --url-file）")
    p.add_argument("--url-file", help="URL 文件路径，每行一个网址")
    # ---- 下载 ----
    p.add_argument("--download", action="store_true",
                   help="抓取完成后，把页面内识别到的下载链接交给 aria2 下载")
    p.add_argument("--threads", "-t", type=int, default=8,
                   help="aria2 多线程下载线程数（-x/-s，默认8）")
    p.add_argument("--download-json", help="从已生成的 scrape.json 提取下载链接并下载")
    p.add_argument("--dl-out", default="downloads", help="下载输出目录（默认 downloads/）")
    # ---- 显示/保存 ----
    p.add_argument("-f", "--save", action="store_true",
                   help="保存到文件（默认只在终端显示结果，加 -f 才导出 JSON/CSV/HTML）")
    # ---- 评估/其它 ----
    p.add_argument("--min-score", type=int, default=40, help="保留的最低信用分")
    p.add_argument("--reputable-only", choices=["yes", "no", "judge"], default="judge",
                   help="只保留高信誉(yes)? 全部(no)? 智能过滤(judge)")
    p.add_argument("--delay", "-d", type=float, default=1.5, help="抓取间隔(秒)")
    p.add_argument("--timeout", type=int, default=12, help="每页超时(秒)")
    p.add_argument("--interactive", action="store_true", help="交互模式")
    p.add_argument("--respect-robots", action="store_true",
                   help="遵守抓取目标 robots.txt（默认关闭以增强可用性）")
    p.add_argument("--output", "-o", default=".", help="输出根目录")
    args = p.parse_args()

    global _RESPECT_ROBOTS
    _RESPECT_ROBOTS = args.respect_robots

    # ---------- 模式A：从已有 JSON 里下载 ----------
    if args.download_json:
        with open(args.download_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        rows = data.get("results", [])
        run_downloads(rows, threads=args.threads, outdir=args.dl_out)
        return

    # ---------- 模式B：手动网址抓取（可选 +下载） ----------
    urls = list(args.url or [])
    if args.url_file:
        with open(args.url_file, "r", encoding="utf-8") as f:
            urls += [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    if urls:
        rows = fetch_urls_manual(urls, delay=args.delay, timeout=args.timeout)
        print_to_terminal(rows, show_text=not getattr(args, "no_text", False))
        if args.save:
            outdir = make_outdir(args.output)
            title = "手动网址抓取报告"
            export(rows, outdir, ["手动URL"], title)
        if args.download:
            run_downloads(rows, threads=args.threads, outdir=args.dl_out)
        return

    # ---------- 模式C：Bing 搜索（可选 +下载） ----------
    queries = args.query or list(DEFAULT_QUERIES)
    if args.interactive:
        print("==== 交互模式 ====")
        q = input("输入搜索关键字(逗号分隔，留空用默认): ").strip()
        if q:
            queries = [x.strip() for x in q.split("，" if "，" in q else ",") if x.strip()]

    title = "优质下载 / 资源站自动抓取报告"
    rows = gather(
        queries=queries,
        pages=max(1, round(args.results / 10)),
        max_sites=args.max_sites,
        min_score=args.min_score,
        delay=args.delay,
        timeout=args.timeout,
        reputable_only=args.reputable_only,
    )
    if args.save:
        outdir = make_outdir(args.output)
        export(rows, outdir, queries, title)
    print_to_terminal(rows, show_text=False)

    if args.download:
        run_downloads(rows, threads=args.threads, outdir=args.dl_out)
    elif not args.save:
        print("\n提示：加 -f 保存到文件；加 --download --threads <N> 可下载页内文件链接。")


if __name__ == "__main__":
    main()
