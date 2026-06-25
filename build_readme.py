#!/usr/bin/env python3
"""扫描 articles/ 目录，生成 README.md 作为索引页。

会被每日 Actions 调用：列出最新一期 + 按日期倒序的历史归档。
"""

import os
import re
from datetime import datetime, timezone

ARTICLES_DIR = "articles"
README = "README.md"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


def collect_dates():
    if not os.path.isdir(ARTICLES_DIR):
        return []
    files = [f for f in os.listdir(ARTICLES_DIR) if DATE_RE.match(f)]
    return sorted((f[:-3] for f in files), reverse=True)


def main():
    dates = collect_dates()
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")

    lines = [
        "# AI 文章每日精选",
        "",
        "自动抓取通俗易懂、偏工程化的 AI 文章，过滤掉偏底层调模型/学术论文类内容。",
        "数据源：Hacker News、DEV.to、InfoQ 中文、少数派、阮一峰周刊。",
        "",
        f"> 由 GitHub Actions 每天自动更新 · 最近更新 {now}",
        "",
        "## 最新一期",
        "",
        f"- [查看最新精选](articles/latest.md)",
        "",
        "## 历史归档",
        "",
    ]

    if dates:
        for d in dates:
            lines.append(f"- [{d}](articles/{d}.md)")
    else:
        lines.append("_暂无归档，等待首次运行。_")
    lines.append("")

    with open(README, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"已生成 {README}，共 {len(dates)} 期归档")


if __name__ == "__main__":
    main()
