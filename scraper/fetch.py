# -*- coding: utf-8 -*-
"""HTTP 抓取模块：稳健请求、robots.txt 尊重、限速、UA、重试。"""
from __future__ import annotations

import time
from typing import Optional, Tuple

import requests
import urllib.robotparser

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36 AutoContentScraper/1.0"
)


class Fetcher:
    """带限速 / 重试 / robots 检查的 HTTP 抓取器。"""

    def __init__(
        self,
        user_agent: str = DEFAULT_UA,
        delay: float = 1.5,
        timeout: int = 12,
        max_retries: int = 2,
        respect_robots: bool = False,
    ):
        self.user_agent = user_agent
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.respect_robots = respect_robots
        self._rp_cache: dict = {}
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "image/webp,*/*;q=0.8"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            }
        )
        self._last_request = 0.0

    def _throttle(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.time()

    def _robot_ok(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        from urllib.parse import urlparse

        pr = urlparse(url)
        base = f"{pr.scheme}://{pr.netloc}"
        if pr.netloc not in self._rp_cache:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(base + "/robots.txt")
            try:
                rp.read()
            except Exception:
                # 读取失败一律放行（保守起见）
                rp = None
            self._rp_cache[pr.netloc] = rp
        rp = self._rp_cache[pr.netloc]
        if rp is None:
            return True
        return rp.can_fetch(self.user_agent, url)

    def get(self, url: str) -> Tuple[bool, Optional[requests.Response], str]:
        """抓取一个 URL。返回 (是否成功, response, 错误信息)。"""
        if not self._robot_ok(url):
            return False, None, "blocked-by-robots"
        last_err = ""
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = self._session.get(
                    url,
                    timeout=self.timeout,
                    allow_redirects=True,
                    headers={"Referer": url},
                )
                if resp.status_code in (403, 429, 503):
                    last_err = f"http-{resp.status_code}"
                    time.sleep(2 * (attempt + 1))
                    continue
                if resp.status_code >= 400:
                    return False, None, f"http-{resp.status_code}"
                resp.encoding = resp.apparent_encoding or resp.encoding or "utf-8"
                return True, resp, ""
            except requests.Timeout:
                last_err = "timeout"
            except requests.ConnectionError as e:
                last_err = f"conn-error:{str(e)[:60]}"
            except requests.RequestException as e:
                last_err = f"req-error:{str(e)[:60]}"
            time.sleep(1.0 * (attempt + 1))
        return False, None, last_err

    def get_text(self, url: str, max_bytes: int = 2_000_000) -> Tuple[bool, str, str]:
        """抓取并返回 (ok, text, err)。限制最大字节数。"""
        ok, resp, err = self.get(url)
        if not ok or resp is None:
            return False, "", err
        content = resp.content
        if len(content) > max_bytes:
            content = content[:max_bytes]
        text = content.decode("utf-8", errors="replace")
        if not text.strip():
            # 尝试用 apparent_encoding
            text = resp.text
        return True, text, ""
