#!/usr/bin/env python3
"""搜索 AI 相关文章，输出文章链接。

偏向「通俗易懂 + 工程化」的内容，过滤掉偏底层调模型/学术论文类的文章。
只用 Python 标准库，无需安装依赖，也不需要 API key。

数据源（全部免费、无需 key）：
  - Hacker News (Algolia Search API)  —— 英文工程类讨论
  - DEV.to API                        —— 英文、偏入门/实战的工程博客
  - 一组中文 RSS 源                     —— 中文科技/AI 资讯

用法示例：
  python3 ai_articles.py
  python3 ai_articles.py --query "AI agent" --limit 30
  python3 ai_articles.py --lang zh            # 只看中文源
  python3 ai_articles.py --out articles.md    # 同时保存为 markdown
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

TIMEOUT = 12
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ai-articles-script/1.0"

# ---------------------------------------------------------------------------
# 打分关键词：决定一篇文章是否「通俗 + 工程化」并值得推荐
# ---------------------------------------------------------------------------

# 加分：工程化 / 实战 / 通俗（命中越多分越高）
ENGINEERING_KEYWORDS = [
    # 英文
    "engineering", "engineer", "production", "deploy", "deployment", "build",
    "building", "architecture", "system design", "scalable", "scaling", "pipeline",
    "infrastructure", "best practice", "practical", "hands-on", "tutorial", "guide",
    "how to", "case study", "in practice", "real world", "lessons", "workflow",
    "rag", "agent", "agents", "tool use", "api", "integration", "prompt",
    "observability", "monitoring", "cost", "latency", "evaluation", "eval",
    "vector", "embedding", "orchestration", "framework", "devops", "mlops", "llmops",
    # 中文
    "工程", "工程化", "实战", "实践", "落地", "部署", "上线", "架构", "系统设计",
    "教程", "入门", "指南", "案例", "踩坑", "经验", "应用", "如何", "怎么",
    "流水线", "智能体", "提示词", "向量", "检索增强", "成本", "优化实践",
]

# 减分 / 倾向过滤：偏底层调模型、训练、学术研究
EXCLUDE_KEYWORDS = [
    # 英文
    "fine-tune", "fine tuning", "finetune", "pretrain", "pre-train", "pretraining",
    "gradient", "backprop", "loss function", "hyperparameter", "weight decay",
    "arxiv", "paper", "benchmark", "sota", "state-of-the-art", "ablation",
    "transformer architecture", "attention mechanism", "tensor", "cuda kernel",
    "quantization", "distillation", "lora", "qlora", "rlhf", "dpo",
    "tokenizer training", "dataset curation", "scaling laws",
    # 中文
    "微调", "预训练", "训练技巧", "梯度", "损失函数", "超参", "论文解读",
    "蒸馏", "量化", "注意力机制", "权重", "数据集构建", "强化学习训练",
]

# AI 主题词：用于在通用源（如中文 RSS）里筛出 AI 相关文章
AI_TOPIC_KEYWORDS = [
    "ai", "a.i", "artificial intelligence", "machine learning", "deep learning",
    "llm", "large language model", "gpt", "chatgpt", "claude", "gemini", "llama",
    "agent", "rag", "neural", "openai", "anthropic", "copilot", "diffusion",
    "人工智能", "大模型", "大语言模型", "机器学习", "深度学习", "智能体",
    "生成式", "多模态", "提示词", "向量数据库",
]


def _kw_hits(text, keywords):
    text = text.lower()
    return sum(1 for kw in keywords if kw in text)


def _pop_bonus(pop):
    if pop >= 100:
        return 3
    if pop >= 50:
        return 2
    if pop >= 20:
        return 1
    return 0


def score_article(title, summary="", pop=0):
    """给文章打分；返回 (score, is_ai)。分数越高越值得推荐。

    思路：只要是 AI 相关且不偏「调模型/学术」，就保留（工程词非必须）；
    工程化内容加分、热度高的好文加分，调模型/论文类减分沉底。
    """
    text = f"{title} {summary}".lower()
    is_ai = _kw_hits(text, AI_TOPIC_KEYWORDS) > 0
    eng = _kw_hits(text, ENGINEERING_KEYWORDS)
    exclude = _kw_hits(text, EXCLUDE_KEYWORDS)
    score = eng * 2 - exclude * 3 + _pop_bonus(pop)
    return score, is_ai


# ---------------------------------------------------------------------------
# 数据获取
# ---------------------------------------------------------------------------

def _http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def fetch_hackernews(query, max_items=40, min_points=15):
    """Hacker News：英文工程类讨论，按热度过滤。"""
    out = []
    q = urllib.parse.quote(query)
    url = (
        f"https://hn.algolia.com/api/v1/search?query={q}"
        f"&tags=story&hitsPerPage={max_items}"
    )
    try:
        data = json.loads(_http_get(url))
    except Exception as e:
        print(f"  [warn] Hacker News 获取失败: {e}", file=sys.stderr)
        return out
    for h in data.get("hits", []):
        title = h.get("title") or ""
        link = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        if not title or (h.get("points") or 0) < min_points:
            continue
        out.append({
            "title": title.strip(),
            "url": link,
            "source": "Hacker News",
            "lang": "en",
            "extra": f"{h.get('points', 0)}分",
            "pop": h.get("points") or 0,
            "summary": "",
        })
    return out


def fetch_devto(tags=("ai", "machinelearning", "llm", "chatgpt", "rag"), per_tag=15):
    """DEV.to：英文、偏入门与实战的工程博客。"""
    out = []
    for tag in tags:
        url = f"https://dev.to/api/articles?tag={tag}&per_page={per_tag}&top=30"
        try:
            data = json.loads(_http_get(url))
        except Exception as e:
            print(f"  [warn] DEV.to(tag={tag}) 获取失败: {e}", file=sys.stderr)
            continue
        for a in data:
            title = (a.get("title") or "").strip()
            if not title:
                continue
            out.append({
                "title": title,
                "url": a.get("url", ""),
                "source": "DEV.to",
                "lang": "en",
                "extra": f"{a.get('positive_reactions_count', 0)}赞·{a.get('reading_time_minutes', '?')}分钟",
                "pop": a.get("positive_reactions_count") or 0,
                "summary": a.get("description", "") or "",
            })
    return out


# 中文 RSS 源（通用科技/AI 资讯，按标题里的 AI 关键词二次筛选）
CN_RSS_FEEDS = [
    ("InfoQ 中文", "https://www.infoq.cn/feed"),
    ("少数派", "https://sspai.com/feed"),
    ("阮一峰的网络日志", "https://www.ruanyifeng.com/blog/atom.xml"),
]


def _strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _localname(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find_child(el, names):
    """按 localname 查找子节点，忽略命名空间（兼容 RSS 与 Atom）。"""
    for ch in el:
        if _localname(ch.tag) in names:
            return ch
    return None


def _parse_rss_regex(name, raw):
    """XML 解析失败时的兜底：用正则从 <item>/<entry> 里抠标题和链接。"""
    out = []
    text = raw.decode("utf-8", "ignore")
    blocks = re.findall(r"<(?:item|entry)\b.*?</(?:item|entry)>", text, re.S | re.I)
    for b in blocks:
        tm = re.search(r"<title[^>]*>(.*?)</title>", b, re.S | re.I)
        lm = re.search(r"<link[^>]*href=[\"'](.*?)[\"']", b, re.I) or \
            re.search(r"<link[^>]*>(.*?)</link>", b, re.S | re.I)
        if not tm or not lm:
            continue
        title = _strip_html(re.sub(r"<!\[CDATA\[|\]\]>", "", tm.group(1)))
        link = lm.group(1).strip()
        if title and link:
            out.append({"title": title, "url": link, "source": name,
                        "lang": "zh", "extra": "", "summary": ""})
    return out


def fetch_rss(name, url, max_items=25):
    """解析 RSS / Atom，返回条目列表；解析失败则用正则兜底。"""
    out = []
    try:
        raw = _http_get(url)
    except Exception as e:
        print(f"  [warn] RSS {name} 获取失败: {e}", file=sys.stderr)
        return out

    try:
        root = ET.fromstring(raw)
    except Exception:
        items = _parse_rss_regex(name, raw)
        if not items:
            print(f"  [warn] RSS {name} 解析失败（XML 非法且兜底未命中）", file=sys.stderr)
        return items[:max_items]

    items = [el for el in root.iter() if _localname(el.tag) in ("item", "entry")]
    for it in items[:max_items]:
        title_el = _find_child(it, ("title",))
        link_el = _find_child(it, ("link",))
        summ_el = _find_child(it, ("description", "summary", "content"))

        title = _strip_html(title_el.text) if title_el is not None else ""
        if link_el is not None:
            link = (link_el.get("href") or link_el.text or "").strip()
        else:
            link = ""
        summary = _strip_html(summ_el.text) if summ_el is not None else ""

        if not title or not link:
            continue
        out.append({
            "title": title,
            "url": link,
            "source": name,
            "lang": "zh",
            "extra": "",
            "summary": summary[:200],
        })
    return out


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def gather(query, lang):
    articles = []
    if lang in ("en", "both"):
        print("• 抓取 Hacker News ...", file=sys.stderr)
        articles += fetch_hackernews(query)
        print("• 抓取 DEV.to ...", file=sys.stderr)
        articles += fetch_devto()
    if lang in ("zh", "both"):
        for name, url in CN_RSS_FEEDS:
            print(f"• 抓取 RSS：{name} ...", file=sys.stderr)
            articles += fetch_rss(name, url)
    return articles


def rank_and_filter(articles, min_score):
    seen = set()
    ranked = []
    for a in articles:
        url = a["url"]
        if not url or url in seen:
            continue
        seen.add(url)
        score, is_ai = score_article(a["title"], a.get("summary", ""), a.get("pop", 0))
        if not is_ai:
            continue
        if score < min_score:
            continue
        a["score"] = score
        ranked.append(a)
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked


def render(ranked, limit):
    lines = []
    header = f"# AI 工程化文章推荐（{datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M')}）\n"
    lines.append(header)
    if not ranked:
        lines.append("没有匹配到合适的文章，试试调低 --min-score 或换个 --query。")
        return "\n".join(lines)
    for i, a in enumerate(ranked[:limit], 1):
        meta = " · ".join(x for x in [a["source"], a.get("extra", "")] if x)
        lines.append(f"{i}. [{a['title']}]({a['url']})")
        lines.append(f"   ↳ {meta}  (相关度 {a['score']})")
        if a.get("summary"):
            lines.append(f"   {a['summary'][:120]}")
        lines.append("")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="搜索通俗易懂、偏工程化的 AI 文章")
    p.add_argument("--query", default="AI engineering LLM", help="Hacker News 搜索关键词")
    p.add_argument("--lang", choices=["zh", "en", "both"], default="both", help="文章语言")
    p.add_argument("--limit", type=int, default=25, help="最多输出多少篇")
    p.add_argument("--min-score", type=int, default=0, help="相关度阈值，越高越偏工程化/严格（默认0=保留所有AI好文）")
    p.add_argument("--out", help="把结果同时保存为 markdown 文件")
    args = p.parse_args()

    articles = gather(args.query, args.lang)
    print(f"\n共抓取 {len(articles)} 条，开始打分过滤 ...\n", file=sys.stderr)
    ranked = rank_and_filter(articles, args.min_score)
    output = render(ranked, args.limit)
    print(output)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\n已保存到 {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
