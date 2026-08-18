# -*- coding: utf-8 -*-
"""信誉站白名单库 + 下载/资源站点判定。

维护一份「网上信誉较好的下载站/资源站」域名白名单，并提供域名匹配和分类函数。
白名单之外仍可被抓取，只是会经过启发式信誉打分。
"""
from __future__ import annotations

from typing import Dict, Optional


# 域名 -> (类别, 评分基准/100, 备注)
# 类别：software / download-site / resource / doc / code / news / search / unknown
REPUTABLE_DOMAINS: Dict[str, tuple] = {
    "github.com": ("code", 100, "全球最大开源代码托管"),
    "raw.githubusercontent.com": ("code", 100, "GitHub 原始文件"),
    "api.github.com": ("code", 100, "GitHub API"),
    "gitcode.com": ("code", 88, "GitCode 代码托管"),
    "gitee.com": ("code", 88, "码云/Gitee 代码托管"),
    "sourceforge.net": ("software", 90, "SourceForge 开源软件发布"),
    "gitlab.com": ("code", 90, "GitLab 代码托管"),
    "pypi.org": ("code", 95, "Python 包索引"),
    "npmjs.com": ("code", 95, "npm 包注册表"),
    "crates.io": ("code", 95, "Rust crate 索引"),
    "maven.apache.org": ("code", 90, "Maven 中央仓库"),
    "microsoft.com": ("software", 100, "微软官方"),
    "apple.com": ("software", 100, "苹果官方"),
    "support.apple.com": ("software", 100, "苹果技术支持"),
    "ubuntu.com": ("software", 95, "Ubuntu 官方"),
    "ubuntuusers.de": ("doc", 85, "Ubuntu 用户社区"),
    "debian.org": ("software", 95, "Debian 官方"),
    "kali.org": ("software", 92, "Kali 官方"),
    "kernel.org": ("code", 95, "Linux 内核官方"),
    "archlinux.org": ("software", 95, "Arch Linux 官方"),
    "linuxmint.com": ("software", 90, "Linux Mint 官方"),
    "fedora.org": ("software", 92, "Fedora 官方"),
    "opensuse.org": ("software", 92, "openSUSE 官方"),
    "redhat.com": ("software", 90, "Red Hat 官方"),
    "oracle.com": ("software", 90, "Oracle 官方"),
    "adobe.com": ("software", 85, "Adobe 官方"),
    "mozilla.org": ("software", 95, "Mozilla 官方(Firefox)"),
    "electronjs.org": ("code", 90, "Electron 官方"),
    "nodejs.org": ("code", 92, "Node.js 官方"),
    "python.org": ("code", 95, "Python 官方"),
    "jetbrains.com": ("software", 90, "JetBrains 官方"),
    "vmware.com": ("software", 85, "VMware 官方"),
    "docker.com": ("software", 90, "Docker 官方"),
    "docker.io": ("software", 90, "Docker Hub"),
    "postgresql.org": ("code", 92, "PostgreSQL 官方"),
    "mysql.com": ("code", 90, "MySQL 官方"),
    "sqlite.org": ("code", 90, "SQLite 官方"),
    "redis.io": ("code", 90, "Redis 官方"),
    "nginx.org": ("code", 92, "Nginx 官方"),
    "apache.org": ("code", 95, "Apache 软件基金会"),
    "apachecn.org": ("doc", 85, "ApacheCN 中文文档"),
    "baidu.com": ("search", 80, "百度(搜索/收录)"),
    "123pan.com": ("resource", 82, "123网盘"),
    "alipan.com": ("resource", 82, "阿里云盘"),
    "aliyundrive.com": ("resource", 82, "阿里云盘"),
    "pan.baidu.com": ("resource", 80, "百度网盘"),
    "quark.cn": ("resource", 80, "夸克网盘"),
    "lanzou.com": ("resource", 78, "蓝奏云"),
    "lanzoux.com": ("resource", 78, "蓝奏云"),
    "xiapi.com": ("resource", 75, "下载吧"),
    "wikipedia.org": ("doc", 95, "维基百科"),
    "baike.baidu.com": ("doc", 82, "百度百科"),
    "zhihu.com": ("news", 85, "知乎"),
    "stackoverflow.com": ("doc", 95, "Stack Overflow"),
    "stackexchange.com": ("doc", 92, "Stack Exchange"),
    "runoob.com": ("doc", 82, "菜鸟教程"),
    "w3schools.com": ("doc", 85, "W3Schools"),
    "w3school.com.cn": ("doc", 80, "W3School 中文"),
    "geeksforgeeks.org": ("doc", 88, "GeeksforGeeks"),
    "mdn.mozilla.org": ("doc", 95, "MDN Web 文档"),
    "developer.mozilla.org": ("doc", 95, "MDN Web 文档"),
    "csdn.net": ("doc", 72, "CSDN(注意广告/转载)"),
    "cnblogs.com": ("doc", 78, "博客园"),
    "jianshu.com": ("doc", 75, "简书"),
    "freecodecamp.org": ("doc", 90, "freeCodeCamp"),
    "nimhosoft.com": ("download-site", 78, "柠檬软件站"),
    "ruanmei.com": ("download-site", 76, "软媒软件"),
    "pc6.com": ("download-site", 72, "PC6 下载站"),
    "onlinedown.net": ("download-site", 70, "华军软件园"),
    "skycn.com": ("download-site", 70, "天空下载"),
    "duote.com": ("download-site", 68, "多特软件"),
    "xitongcheng.cc": ("download-site", 62, "系统城"),
    "wanshe.com": ("download-site", 55, "玩搜(需谨慎)"),
    "gnu.org": ("code", 90, "GNU 项目官方"),
    "opensource.org": ("doc", 88, "开源促进会"),
    "filecr.com": ("download-site", 68, "FileCR 软件"),
    "archive.org": ("resource", 92, "互联网档案馆"),
    "gutenberg.org": ("resource", 92, "古登堡计划(公版书)"),
    "z-lib.io": ("resource", 60, "Z-Library(注意版权)"),
    "zhijianshu.com": ("resource", 55, "直简书"),
    "dev.to": ("doc", 82, "DEV Community"),
    "medium.com": ("doc", 78, "Medium"),
    "crunchbase.com": ("resource", 75, "Crunchbase"),
    "alternativeto.net": ("resource", 85, "AlternativeTo 替代软件"),
    "producthunt.com": ("resource", 82, "Product Hunt"),
    "distrowatch.com": ("resource", 80, "DistroWatch 发行版"),
}


# 下载/资源站特征关键词
DOWNLOAD_KEYWORDS = [
    "下载",
    "download",
    "软件",
    "snap",
    "app",
    "resource",
    "mirror",
    "镜像",
    "release",
    "发行版",
    "iso",
    "源码",
    "源码包",
]

RESOURCE_KEYWORDS = [
    "教程",
    "tutorial",
    "文档",
    "document",
    "wiki",
    "帮助",
    "resource",
    "资源",
    "素材",
    "模板",
    "素材库",
    "tool",
    "工具",
]


def is_reputable(url_netloc):
    return match_domain(url_netloc) is not None


def match_domain(url_netloc):
    host = url_netloc.strip().lower()
    if ":" in host:
        host = host.split(":", 1)[0]
    parts = host.split(".")
    for i in range(len(parts)):
        cand = ".".join(parts[i:])
        if cand in REPUTABLE_DOMAINS:
            return (cand, REPUTABLE_DOMAINS[cand])
    return None


def domain_score(url_netloc):
    m = match_domain(url_netloc)
    if m:
        return m[1][1]
    return -1


def guess_type_from_path(url):
    low = url.lower()
    if any(x in low for x in (".apk", ".exe", ".msi", ".dmg", ".deb", ".rpm", "download", "download.", "/download/")):
        return "software"
    if any(x in low for x in (".pdf", ".doc", ".epub", ".txt", ".md")):
        return "doc"
    if any(x in low for x in (".zip", ".tar", ".gz", ".7z", ".rar", "/repo/", "releases", ".iso")):
        return "package"
    return "page"


def summarize(domain):
    m = match_domain(domain)
    if m:
        return m[0] + " -> " + (m[1][2] or m[1][0]) + " (类别:" + m[1][0] + ",基准:" + str(m[1][1]) + "/100)"
    return domain + " -> 白名单外(需启发式评估)"
