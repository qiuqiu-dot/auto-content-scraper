# -*- coding: utf-8 -*-
"""信誉评估模块。

综合四个维度给一个候选站点打分(0-100)：
  1. 白名单基础分（命中则直接给高分）
  2. URL/域名启发式（是否官方、是否下载站、域名恶意词等）
  3. 页面内容质量（正文长度、广告脚本、下载链接、版权/破解特征）
  4. TLS/HTTPS 质量（SSLLabs 不做，仅据响应判断 http/https）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List
from urllib.parse import urlparse

import scraper.sites as sites
from scraper.content import ExtractedContent


@dataclass
class Reputation:
    domain_host: str = ""
    base_score: int = 50
    whitelist_hit: bool = False
    whitelist_note: str = ""
    penalties: List[str] = field(default_factory=list)
    bonuses: List[str] = field(default_factory=list)
    final_score: int = 50

    def average(self) -> int:
        return max(0, min(100, self.final_score))


_BAD_WORDS = ["hack", "crack", "keygen", "serial", "patch", "破解", "私服",
              "外挂", "辅助", "免费领取", "刷钻", "代练", "博彩", "彩票",
              "时时彩", "棋牌", "娱乐城", "买课", "积分墙", "灰色导航", "草榴",
              "成人", "赌博", "赌场", "盗版"]

_GOOD_WORDS = ["官方", "official", "open source", "开源", "github", "repository",
               "documentation", "文档", "tutorial", "教程", "sourceforge",
               "canonical", "gnu", "foundation", "基金会"]


def domain_host(url: str) -> str:
    try:
        return urlparse(url).netloc or "unknown"
    except Exception:
        return "unknown"


def score_url_level(url: str, netloc: str) -> "Reputation":
    r = Reputation(domain_host=netloc)
    score = 50

    # ---------- 1. 白名单 ----------
    m = sites.match_domain(netloc)
    if m:
        r.whitelist_hit = True
        r.whitelist_note = m[1][2] or ""
        score = m[1][1]
        r.bonuses.append(f"白名单:{m[0]}（{m[1][2] or m[1][0]}）")

    # ---------- 2. 域名启发式（仅非白名单时生效，白名单通过即可忽略部分惩罚） ----------
    host = netloc.lower()
    path = urlparse(url).path.lower()

    # 下载/资源站特征（中性加分，但注意捆绑）
    if any(w in host for w in ("download", "soft", "down", "mirror", "source", "app")):
        r.bonuses.append("域名含下载/镜像特征")
        score += 2
    # 恶意词（较大惩罚）
    for w in _BAD_WORDS:
        if w in (host + path):
            r.penalties.append(f"含可疑词:{w}")
            score -= 14
            break
    # 正向词
    for w in _GOOD_WORDS:
        if w in (host + path):
            score = min(score, score)  # 不错分，仅记录
            break

    # 顶级域加分/减分
    tld = (host.rsplit(".", 1)[-1] if "." in host else "")
    if tld in ("com", "org", "net", "io", "dev"):
        r.bonuses.append(f"顶级域 .{tld}(常见)")
        score += 2
    elif tld in ("cn", "cc", "tv", "xyz", "top", "icu", "vip", "info"):
        score -= 2
        r.penalties.append(f"顶级域 .{tld}(易滥用)")

    # 子域提示：http 明文 -> 减分
    if url.startswith("http://"):
        r.penalties.append("明文 http（无加密）")
        score -= 6

    r.base_score = score
    return r


def score_content_level(url: str, ec: ExtractedContent) -> Reputation:
    """基于页面内容的质量打分（在 url_level 之后叠加）。"""
    r = Reputation(domain_host=domain_host(url))
    score = r.base_score = 20
    # 正文长度合理则加
    if ec.text_len >= 300:
        score += 20
        r.bonuses.append(f"正文充实({ec.text_len}字)")
    elif ec.text_len >= 60:
        score += 8
    else:
        r.penalties.append("正文过短(可能是空壳站)")
        score -= 8

    # 广告脚本过多 -> 减
    if ec.scripts_ads >= 3:
        r.penalties.append(f"广告脚本过多({ec.scripts_ads})")
        score -= 10
    elif ec.scripts_ads >= 1:
        r.penalties.append("含广告脚本")
        score -= 3

    # 标题是否包含"下载/资源"关键词
    low_t = (ec.title + " " + ec.h1 + " " + url).lower()
    if "下载" in low_t or "download" in low_t:
        r.bonuses.append("标题/URL含下载特征(资源站)")
        score += 3

    # 有下载链接
    if ec.download_links:
        r.bonuses.append(f"检测到 {len(ec.download_links)} 个下载链接")
        score += 4

    # 版权/盗版特征
    for w in ("破解", "破解版", "注册机", "keygen", "crack", "盗版"):
        if w in low_t:
            r.penalties.append(f"含破解/盗版特征:{w}")
            score -= 18
            break
    # 若命中可疑下载链接(资源站形态)
    r.base_score = score
    return r


def final_reputation(url: str, ec: ExtractedContent) -> Reputation:
    """综合求最终评分。"""
    netloc = domain_host(url)
    u = score_url_level(url, netloc)
    if u.whitelist_hit:
        # 白名单站：以白名单分为主，内容只做小幅微调
        base = u.base_score
        c = score_content_level(url, ec)
        base = base + int(c.base_score * 0.05)   # 内容只影响 5%
        rep = u
        rep.final_score = max(0, min(100, base))
        return rep
    # 非白名单：URL 启发式 + 内容启发式各占一半
    c = score_content_level(url, ec)
    rep = u
    rep.penalties = list(dict.fromkeys(u.penalties + c.penalties))
    rep.bonuses = list(dict.fromkeys(u.bonuses + c.bonuses))
    w_url = 0.45
    w_content = 0.55
    rep.final_score = int(u.base_score * w_url + c.base_score * w_content
                          + _tld_bump(u.domain_host))
    rep.final_score = max(0, min(100, rep.final_score))
    return rep


def _tld_bump(host: str) -> int:
    """对 edu/go/mil/gov 等可信 TLD 额外加分。"""
    low = host.lower()
    for t in (".edu", ".gov", ".mil", ".ac."):
        if t in low:
            return 10
    return 0
