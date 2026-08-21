# -*- coding: utf-8 -*-
"""GitHub 交互工具：基于 gh CLI (gh api) 的仓库克隆、发行版下载、仓库搜索。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import List, Optional, Dict, Any


def gh_available() -> bool:
    return shutil.which("gh") is not None


def run_gh(args: List[str], capture: bool = True) -> subprocess.CompletedProcess:
    """运行 gh 命令。"""
    cmd = ["gh"] + args
    return subprocess.run(cmd, capture_output=capture, text=True, timeout=120)


def run_gh_api(args: List[str]) -> Optional[Dict]:
    """运行 gh api 命令并返回 JSON。"""
    try:
        res = subprocess.run(["gh", "api"] + args, capture_output=True, text=True, timeout=60)
        if res.returncode == 0:
            return json.loads(res.stdout)
        return None
    except Exception:
        return None


def gh_auth_status() -> bool:
    """检查 gh 是否已认证。"""
    try:
        res = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        return res.returncode == 0
    except Exception:
        return False


def ensure_gh_auth() -> bool:
    """确保已登录，未登录则引导登录。"""
    if gh_auth_status():
        return True
    print("  [!] gh 未登录，正在启动登录流程...")
    try:
        subprocess.run(["gh", "auth", "login"], check=True)
        return True
    except subprocess.CalledProcessError:
        print("  [❌] 登录失败")
        return False


def get_release_assets(repo: str, tag: str) -> List[Dict]:
    """获取指定发行版的资源列表（使用 gh api）。"""
    data = run_gh_api([f"repos/{repo}/releases/tags/{tag}", "--jq", ".assets[] | {name, size, url, browser_download_url}"])
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return [data] if data else []


# ==================== 1. 克隆仓库 ====================
def clone_repo(repo: str, dest: str = "", shallow: bool = False) -> Dict[str, Any]:
    """
    克隆仓库。
    repo 格式: owner/repo 或 完整 URL
    """
    if not ensure_gh_auth():
        return {"ok": False, "error": "gh 未登录"}

    args = ["repo", "clone", repo]
    if dest:
        args.append(dest)
    if shallow:
        args.extend(["--", "--depth=1"])

    print(f"  [克隆] gh repo clone {repo} ...")
    try:
        res = subprocess.run(["gh"] + args, capture_output=True, text=True, timeout=300)
        ok = res.returncode == 0
        return {"ok": ok, "output": res.stdout.strip(), "error": res.stderr.strip() if not ok else ""}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "克隆超时"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def clone_multiple(repos: List[str], base_dir: str = ".", shallow: bool = False) -> List[Dict]:
    """批量克隆。"""
    results = []
    for i, repo in enumerate(repos, 1):
        print(f"  [{i}/{len(repos)}] 克隆 {repo} ...")
        dest = os.path.join(base_dir, repo.split("/")[-1])
        res = clone_repo(repo, dest, shallow)
        results.append({"repo": repo, **res})
    return results


# ==================== 2. 下载发行版 ====================
def list_releases(repo: str, limit: int = 10) -> List[Dict]:
    """列出仓库的发行版（使用 gh api）。"""
    if not ensure_gh_auth():
        return []

    try:
        data = run_gh_api([f"repos/{repo}/releases", "--jq", f".[:{limit}] | .[] | {{tag_name: .tag_name, name: .name, published_at: .published_at, draft: .draft, prerelease: .prerelease, assets_count: (.assets | length)}}"])
        if data is None:
            return []
        if isinstance(data, list):
            return data
        return [data] if data else []
    except Exception as e:
        print(f"  [❌] 解析发行版失败: {e}")
        return []


def download_release_assets(repo: str, tag: str = "", outdir: str = "downloads", pattern: str = "") -> Dict:
    """
    下载指定发行版的资源。
    tag 为空则下载最新发行版。
    pattern 为文件名匹配正则（可选）。
    """
    if not ensure_gh_auth():
        return {"ok": False, "error": "gh 未登录"}

    os.makedirs(outdir, exist_ok=True)

    # 获取发行版列表
    releases = list_releases(repo, limit=10)
    if not releases:
        return {"ok": False, "error": "无发行版"}

    target = releases[0] if not tag else next((r for r in releases if r["tag_name"] == tag), None)
    if not target:
        return {"ok": False, "error": f"未找到标签: {tag}"}

    tag_name = target["tag_name"]
    # 单独获取该发行版的 assets
    assets = get_release_assets(repo, tag_name)
    if not assets:
        return {"ok": False, "error": f"发行版 {tag_name} 无资源文件"}

    # 过滤资源
    if pattern:
        assets = [a for a in assets if re.search(pattern, a["name"])]
        if not assets:
            return {"ok": False, "error": f"无匹配 {pattern} 的资源"}

    print(f"  [发行版] {repo} @ {tag_name} - 共 {len(assets)} 个资源")
    downloaded = []

    for asset in assets:
        name = asset["name"]
        url = asset["browser_download_url"]
        print(f"    ↓ {name} ...")
        # 使用 gh release download 下载单个 asset
        cmd = ["gh", "release", "download", tag_name, "-R", repo, "-p", name, "-D", outdir]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            ok = res.returncode == 0
            downloaded.append({"name": name, "ok": ok, "error": res.stderr if not ok else ""})
            if ok:
                print(f"      ✅ {name}")
            else:
                print(f"      ❌ {name}: {res.stderr[:100]}")
        except subprocess.TimeoutExpired:
            downloaded.append({"name": name, "ok": False, "error": "下载超时"})
        except Exception as e:
            downloaded.append({"name": name, "ok": False, "error": str(e)})

    ok_count = sum(1 for d in downloaded if d["ok"])
    return {"ok": ok_count > 0, "tag": tag_name, "downloaded": downloaded, "total": len(downloaded), "success": ok_count}


def download_latest_release(repo: str, outdir: str = "downloads", pattern: str = "") -> Dict:
    """下载最新发行版资源（简化版）。"""
    return download_release_assets(repo, tag="", outdir=outdir, pattern=pattern)


# ==================== 3. 搜索仓库 ====================
def search_repos(query: str, limit: int = 20, language: str = "", stars: str = "") -> List[Dict]:
    """
    搜索仓库（使用 gh api）。
    query: 搜索关键词
    language: 语言筛选（如 python, go, rust）
    stars: 星标筛选（如 >1000, 100..1000）
    """
    if not ensure_gh_auth():
        return []

    q = query
    if language:
        q += f" language:{language}"
    if stars:
        q += f" stars:{stars}"

    try:
        data = run_gh_api(["/search/repositories", "-f", f"q={q}", "--jq", f".items[:{limit}] | .[] | {{full_name: .full_name, description: .description, stargazers_count: .stargazers_count, language: .language, html_url: .html_url, topics: .topics, updated_at: .updated_at}}"])
        if data is None:
            return []
        if isinstance(data, list):
            return data
        return [data] if data else []
    except Exception as e:
        print(f"  [❌] 搜索异常: {e}")
        return []


def search_repos_interactive() -> Optional[Dict]:
    """交互式搜索并选择仓库。"""
    query = input("  搜索关键词: ").strip()
    if not query:
        return None

    language = input("  语言筛选 (可留空): ").strip() or None
    stars = input("  星标筛选 如 >1000 / 100..1000 (可留空): ").strip() or None
    limit = 20

    print(f"  [搜索] {query} ...")
    results = search_repos(query, limit=limit, language=language or "", stars=stars or "")
    if not results:
        print("  无结果")
        return None

    print("\n  找到以下仓库:")
    for i, r in enumerate(results, 1):
        desc = r.get("description") or "无描述"
        lang = r.get("language") or "未知"
        stars = r.get("stargazers_count", 0)
        print(f"  [{i}] {r['full_name']} ⭐{stars} ({lang})")
        print(f"       {desc[:80]}")

    choice = input("\n  选择编号 (回车取消): ").strip()
    if not choice.isdigit():
        return None
    idx = int(choice) - 1
    if 0 <= idx < len(results):
        return results[idx]
    return None


def get_repo_topics(repo: str) -> List[str]:
    """获取仓库的 topics 标签。"""
    data = run_gh_api([f"repos/{repo}/topics", "--jq", ".names[]"])
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return [data] if data else []


def set_repo_topics(repo: str, topics: List[str]) -> bool:
    """设置仓库 topics。"""
    try:
        topics_json = json.dumps(topics)
        res = run_gh(["api", f"/repos/{repo}/topics", "-X", "PUT", "-f", f"names={topics_json}"])
        return res.returncode == 0
    except Exception:
        return False


# ==================== 交互菜单 ====================
def github_interactive_menu() -> None:
    """GitHub 专区交互主菜单。"""
    if not gh_available():
        print("  [❌] 未安装 gh CLI，请先安装: https://cli.github.com/")
        return
    if not ensure_gh_auth():
        return

    while True:
        print("\n" + "=" * 50)
        print("        GitHub 专区")
        print("=" * 50)
        print("  1) 克隆仓库 (gh repo clone)")
        print("  2) 下载发行版")
        print("  3) 搜索仓库 (可选标签/语言/星标)")
        print("  4) 返回主菜单")
        print("-" * 50)
        choice = input("  请选择 [1-4]: ").strip()

        if choice == "1":
            interactive_clone()
        elif choice == "2":
            interactive_download_release()
        elif choice == "3":
            interactive_search()
        elif choice == "4":
            break
        else:
            print("  无效选择")


def interactive_clone() -> None:
    """交互式克隆。"""
    print("\n--- 克隆仓库 ---")
    repo = input("  仓库 (owner/repo 或 URL): ").strip()
    if not repo:
        return
    dest = input("  目标目录 (留空=当前目录下同名文件夹): ").strip()
    shallow = input("  浅克隆 (--depth=1) ? [y/N]: ").strip().lower() == "y"
    res = clone_repo(repo, dest or None, shallow)
    if res["ok"]:
        print(f"  ✅ 克隆成功")
    else:
        print(f"  ❌ 失败: {res.get('error', '未知错误')}")


def interactive_download_release() -> None:
    """交互式下载发行版。"""
    print("\n--- 下载发行版 ---")
    repo = input("  仓库 (owner/repo): ").strip()
    if not repo:
        return
    tag = input("  标签 (留空=最新): ").strip() or None
    pattern = input("  文件名匹配正则 (留空=全部): ").strip() or None
    outdir = input("  输出目录 (默认 downloads/): ").strip() or "downloads"

    res = download_release_assets(repo, tag or "", outdir, pattern or "")
    if res["ok"]:
        print(f"\n  ✅ 完成: {res['success']}/{res['total']} 个文件")
        for d in res["downloaded"]:
            status = "✅" if d["ok"] else "❌"
            print(f"    {status} {d['name']}")
    else:
        print(f"  ❌ 失败: {res.get('error', '未知错误')}")


def interactive_search() -> None:
    """交互式搜索并后续操作。"""
    print("\n--- 搜索仓库 ---")
    repo = search_repos_interactive()
    if not repo:
        return

    print(f"\n  选中: {repo['full_name']} ⭐{repo.get('stargazers_count',0)}")
    print("  后续操作:")
    print("    1) 克隆该仓库")
    print("    2) 下载其最新发行版")
    print("    3) 查看详情")
    print("    0) 返回")
    sub = input("  选择: ").strip()
    if sub == "1":
        shallow = input("  浅克隆? [y/N]: ").strip().lower() == "y"
        clone_repo(repo["full_name"], None, shallow)
    elif sub == "2":
        download_latest_release(repo["full_name"])
    elif sub == "3":
        print(f"  描述: {repo.get('description') or '无'}")
        print(f"  语言: {repo.get('language') or '未知'}")
        print(f"  链接: {repo['html_url']}")
        print(f"  更新: {repo.get('updated_at')}")
        topics = get_repo_topics(repo["full_name"])
        if topics:
            print(f"  标签: {', '.join(topics)}")


def download_latest_release(repo: str, outdir: str = "downloads", pattern: str = "") -> Dict:
    """下载最新发行版资源（简化版）。"""
    return download_release_assets(repo, tag="", outdir=outdir, pattern=pattern)


# ==================== 批量操作 ====================
def batch_clone_from_file(filepath: str, base_dir: str = ".", shallow: bool = False) -> List[Dict]:
    """从文件批量克隆（每行一个 owner/repo）。"""
    if not os.path.exists(filepath):
        print(f"  [❌] 文件不存在: {filepath}")
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        repos = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    return clone_multiple(repos, base_dir, shallow)
