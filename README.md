# Auto Content Scraper

自动抓取「网上优质内容 / 资源站 / 下载站」的程序。
通过 **Bing 搜索** 或 **手动输入网址** 发现/抓取内容，结合 **信誉站白名单库** 与启发式打分做可信度评估，
并支持 **aria2 多线程下载** 页面中的文件链接。结果导出为 JSON / CSV / HTML 报告。

## 功能

- 🔍 **Bing 搜索**：多关键字批量搜索，自动解析自然结果（标题、URL、摘要），支持翻页。
- 🔗 **手动网址抓取**：直接输入一个或多个网址抓取，无需搜索。
- 🏅 **信誉评估**：内置 90+ 个信誉较好的下载/资源/官方站白名单；站外站点按域名 + 页面内容启发式打分（自动识别盗版/破解/广告站降分）。
- 📦 **内容抓取**：抽取正文、标题、meta、链接与下载链接；遵循限速、超时重试；robots.txt 默认关闭以增强可用性（可 `--respect-robots` 开启）。
- ⚡ **aria2 多线程下载**：把页面/结果里识别到的文件链接交给 aria2c，用 `-x/-s` 指定分段线程数高速下载。
- 📄 **导出**：JSON 全量 + CSV 摘要 + 自包含 HTML 可视化报告。

## 目录结构

```
auto-content-scraper/
├── scraper/
│   ├── __init__.py
│   ├── main.py          # 命令行入口
│   ├── bing_search.py   # Bing 搜索结果解析
│   ├── sites.py         # 信誉白名单库 + 域名/类型判定
│   ├── fetch.py         # HTTP 抓取（robots、限速、UA、重试）
│   ├── reputation.py    # 信誉打分与过滤
│   ├── content.py       # 正文/链接/元信息/下载链接抽取
│   ├── aria2.py         # aria2 多线程下载 + 兜底下载
├── results/             # 导出的 JSON / CSV / HTML
├── requirements.txt
└── README.md
```

## 安装

```bash
cd auto-content-scraper
pip install requests beautifulsoup4
# aria2 下载（按系统）：
#   Termux:  pkg install aria2
#   Debian/Ubuntu/Mac:  apt/brew install aria2
#   Windows: 下载 aria2c.exe 并放入 PATH
```

## 使用方法

### 1) Bing 搜索抓取资源站
```bash
python -m scraper.main                                             # 默认关键字
python -m scraper.main --interactive                               # 交互输入关键字
python -m scraper.main -q "下载站 推荐" -q "linux 发行版 iso" -m 20  # 多关键字
```

### 2) 手动输入网址抓取
```bash
python -m scraper.main --url https://example.com/download          # 抓单个网址
python -m scraper.main --url https://a.com/ --url https://b.com/   # 多个网址
python -m scraper.main --url-file urls.txt                         # 每行一个网址
```

### 3) aria2 多线程下载
```bash
# 抓取下载页并自动把页内文件链接交给 aria2，16 线程分段下载
python -m scraper.main --url https://example.com/downloadpage --download --threads 16

# 从之前生成的 scrape.json 提取下载链接批量下载
python -m scraper.main --download-json results/20260817_xxx/scrape.json --threads 16
```

### 常用参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--query` / `-q` | 内置一组 | 搜索关键字（可多次） |
| `--results` / `-r` | 10 | 每关键字 Bing 结果条数 |
| `--max-sites` / `-m` | 20 | 最多抓取评估站点数 |
| `--url` | - | 手动要抓取的网址（可多次，或 `--url-file`） |
| `--url-file` | - | URL 文件路径，每行一个网址 |
| `--download` | off | 抓取完成后，把页面内识别到的下载链接交给 aria2 下载 |
| `--threads` / `-t` | 8 | aria2 多线程下载线程数（-x/-s，默认8） |
| `--download-json` | - | 从已生成的 scrape.json 提取下载链接并下载 |
| `--dl-out` | downloads/ | 下载输出目录（默认 downloads/） |
| `--reputable-only` | judge | 只保留高信誉(yes)? 全部(no)? 智能过滤(judge) |
| `--min-score` | 40 | 保留的最低信用分（0-100） |
| `--delay` / `-d` | 1.5 | 抓取间隔秒（限速） |
| `--timeout` | 12 | 每页超时秒 |
| `--respect-robots` | off | 遵守抓取目标 robots.txt（默认关闭以增强可用性） |
| `--output` / `-o` | `.` | 输出根目录 |

## 输出

- `results/<时间戳>/scrape.json` — 全量结构化数据
- `results/<时间戳>/scrape.csv` — 站点摘要（Excel 友好）
- `results/<时间戳>/report.html` — 自包含可视化报告（双击打开）
- `downloads/` — aria2 下载的文件（可用 `--dl-out` 改目录）

## 说明与合规

- 下载由 aria2c 执行：`-xN` 每服务器并发连接、`-sN` 分段数，二者通常都设为 `--threads N`。
  aria2c 未安装时自动退化为 Python 内置单线程下载（会明确提示）。
- 请遵守目标网站 robots.txt 与使用条款，控制速率；本程序仅用于个人学习/研究。
- Bing 可能对高频请求返回验证码，遇到请降低频率或稍后再试。
