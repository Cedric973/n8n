---
name: crawl4ai
description: >
  Crawl and scrape websites into clean, LLM-ready Markdown or structured JSON using the
  open-source Crawl4AI Python library (github.com/unclecode/crawl4ai). Use when the user
  wants to scrape a web page or site, turn web content into Markdown for RAG/agents,
  extract structured data (prices, listings, articles, tables) from pages, deep-crawl a
  site, run batch/parallel crawls, or build a web-to-data pipeline — especially when the
  output feeds an LLM. Covers install, the async crawler API, CSS/XPath and LLM extraction
  strategies, deep crawling, dispatchers for concurrency, and the `crwl` CLI. NOT for
  simple single-request HTML fetches where `requests`/`httpx` suffice, and NOT for driving
  an authenticated browser session interactively (use a browser-automation skill for that).
---

# Crawl4AI — LLM-Friendly Web Crawler & Scraper

Crawl4AI turns web pages into clean Markdown or structured JSON, purpose-built for RAG,
agents, and data pipelines. It runs a real (Playwright/Chromium) browser under an async
API, so it handles JS-rendered pages, sessions, proxies, and hooks.

## When to use this skill

- "Scrape this page / site into Markdown" or "turn this into clean text for an LLM"
- Extract structured records (products, prices, articles, tables) from one or many pages
- Deep-crawl a site (BFS/DFS/best-first) with URL filters and scorers
- Batch-crawl many URLs concurrently with memory-aware dispatching
- Build a web-to-RAG / web-to-JSON pipeline

Prefer plain `httpx`/`requests` + `BeautifulSoup` when the target is a static endpoint and
you don't need JS rendering, Markdown conversion, or crawl orchestration.

## Setup

```bash
pip install -U crawl4ai
crawl4ai-setup      # installs Playwright browsers + runs post-install checks
crawl4ai-doctor     # verify the install
# If browsers fail to install:
python -m playwright install --with-deps chromium
```

## Core pattern — page to Markdown

```python
import asyncio
from crawl4ai import AsyncWebCrawler

async def main():
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url="https://www.nbcnews.com/business")
        print(result.markdown)          # clean, LLM-ready Markdown
        # result.cleaned_html, result.links, result.media, result.success also available

asyncio.run(main())
```

## Configuration objects

`BrowserConfig` controls the browser; `CrawlerRunConfig` controls a single crawl run.

```python
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

browser_cfg = BrowserConfig(headless=True, verbose=False)      # proxy=..., user_agent=...
run_cfg = CrawlerRunConfig(
    cache_mode=CacheMode.BYPASS,        # ENABLED | BYPASS | DISABLED — control caching
    word_count_threshold=10,            # drop tiny text blocks
    exclude_external_links=True,
    screenshot=False,
    wait_for="css:.content",            # wait for a selector before scraping
)

async with AsyncWebCrawler(config=browser_cfg) as crawler:
    result = await crawler.arun(url="https://example.com", config=run_cfg)
```

## Structured extraction

**CSS/XPath (fast, deterministic, no LLM):** use `JsonCssExtractionStrategy` with a schema.

```python
import json
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

schema = {
    "name": "Products",
    "baseSelector": "div.product-card",
    "fields": [
        {"name": "title", "selector": "h2", "type": "text"},
        {"name": "price", "selector": ".price", "type": "text"},
        {"name": "url",   "selector": "a",     "type": "attribute", "attribute": "href"},
    ],
}
run_cfg = CrawlerRunConfig(extraction_strategy=JsonCssExtractionStrategy(schema))

async with AsyncWebCrawler() as crawler:
    result = await crawler.arun(url="https://example.com/shop", config=run_cfg)
    data = json.loads(result.extracted_content)   # list[dict]
```

**LLM extraction (flexible, schema-guided):** use `LLMExtractionStrategy` + `LLMConfig`
when the layout is irregular or you need semantic extraction. Prefer CSS first for cost/speed.

```python
from pydantic import BaseModel
from crawl4ai import LLMConfig
from crawl4ai.extraction_strategy import LLMExtractionStrategy

class Product(BaseModel):
    name: str
    price: str

strategy = LLMExtractionStrategy(
    llm_config=LLMConfig(provider="openai/gpt-4o-mini", api_token="env:OPENAI_API_KEY"),
    schema=Product.model_json_schema(),
    extraction_type="schema",
    instruction="Extract every product name and price.",
)
```

`RegexExtractionStrategy` is available for pattern-based pulls (emails, prices) with no LLM.

## Deep crawling a site

```python
from crawl4ai import CrawlerRunConfig
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
from crawl4ai.deep_crawling.filters import FilterChain, DomainFilter, URLPatternFilter

run_cfg = CrawlerRunConfig(
    deep_crawl_strategy=BFSDeepCrawlStrategy(
        max_depth=2,
        max_pages=25,
        filter_chain=FilterChain([
            DomainFilter(allowed_domains=["docs.crawl4ai.com"]),
            URLPatternFilter(patterns=["*/core/*"]),
        ]),
    ),
    stream=True,      # process results as they arrive
)

async with AsyncWebCrawler() as crawler:
    async for result in await crawler.arun(url="https://docs.crawl4ai.com", config=run_cfg):
        print(result.url, len(result.markdown or ""))
```

Strategies: `BFSDeepCrawlStrategy`, `DFSDeepCrawlStrategy`, `BestFirstCrawlingStrategy`
(pair with scorers like `KeywordRelevanceScorer`, `FreshnessScorer`, `PathDepthScorer`).

## Batch / concurrent crawling

`arun_many` + a dispatcher crawls many URLs with memory-aware concurrency.

```python
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher

urls = ["https://a.com", "https://b.com", "https://c.com"]
dispatcher = MemoryAdaptiveDispatcher(memory_threshold_percent=80.0, max_session_permit=10)

async with AsyncWebCrawler() as crawler:
    results = await crawler.arun_many(urls, config=CrawlerRunConfig(), dispatcher=dispatcher)
    for r in results:
        print(r.url, r.success)
```

## CLI (`crwl`)

```bash
crwl https://www.nbcnews.com/business -o markdown         # page -> markdown
crwl https://docs.crawl4ai.com --deep-crawl bfs --max-pages 10
crwl https://example.com/products -q "Extract all product prices"   # LLM Q&A extraction
```

## Notes

- Always use the async API inside `asyncio.run(...)`; reuse one `AsyncWebCrawler` for many URLs.
- Respect target sites: check `robots.txt`, rate-limit, and honor terms of service.
- Docker deployment exists but is **secure-by-default** (auth on, loopback bind) as of v0.9.x —
  treat the request body as an untrusted trust boundary.
- See `references/api-cheatsheet.md` for the full public API surface.
- Contributors to the crawl4ai repo itself: the upstream `/c4ai-check` command
  (adversarial + regression testing) is captured in `references/c4ai-check.md`.
