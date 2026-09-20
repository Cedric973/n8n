# Crawl4AI — Public API Cheat-Sheet

Importable from the top-level `crawl4ai` package (`from crawl4ai import ...`).
Grouped by purpose. Source: `crawl4ai/__init__.py` `__all__`.

## Core
- `AsyncWebCrawler` — main entry point; `.arun(url, config=...)`, `.arun_many(urls, config=..., dispatcher=...)`
- `CrawlResult` — result object: `.markdown`, `.cleaned_html`, `.extracted_content`, `.links`, `.media`, `.success`, `.status_code`, `.screenshot`
- `CacheMode` — `ENABLED` / `BYPASS` / `DISABLED`
- `CrawlerHub`, `Crawl4aiDockerClient`

## Configuration
- `BrowserConfig` — browser-level (headless, proxy, user_agent, viewport, cookies)
- `CrawlerRunConfig` — per-run (cache_mode, extraction_strategy, deep_crawl_strategy, wait_for, screenshot, stream, word_count_threshold, exclude_external_links)
- `HTTPCrawlerConfig` — lightweight HTTP-only crawling (no browser)
- `LLMConfig` — provider + api_token for LLM-backed features
- `GeolocationConfig`, `ProxyConfig`, `SeedingConfig`, `VirtualScrollConfig`

## Extraction strategies
- `JsonCssExtractionStrategy` — CSS-selector schema (fast, no LLM) ← prefer this
- `JsonXPathExtractionStrategy`, `JsonLxmlExtractionStrategy` — XPath / lxml variants
- `LLMExtractionStrategy` — schema/block extraction via an LLM
- `RegexExtractionStrategy` — regex patterns (emails, prices, etc.)
- `CosineStrategy` — semantic clustering
- `ExtractionStrategy` — base class

## Markdown & content filtering
- `DefaultMarkdownGenerator`, `MarkdownGenerationResult`
- `PruningContentFilter` — heuristic noise removal ("fit markdown")
- `BM25ContentFilter` — query-relevant filtering
- `LLMContentFilter` — LLM-based relevance filtering
- `RelevantContentFilter` — base class

## Table extraction
- `DefaultTableExtraction`, `LLMTableExtraction`, `NoTableExtraction`, `TableExtractionStrategy`

## Scraping strategies
- `WebScrapingStrategy`, `LXMLWebScrapingStrategy`, `ContentScrapingStrategy`

## Deep crawling (also under `crawl4ai.deep_crawling`)
- Strategies: `BFSDeepCrawlStrategy`, `DFSDeepCrawlStrategy`, `BestFirstCrawlingStrategy`, `DeepCrawlStrategy`
- Filters: `FilterChain`, `URLPatternFilter`, `ContentTypeFilter`, `DomainFilter`, `SEOFilter`, `URLFilter`
- Scorers: `KeywordRelevanceScorer`, `DomainAuthorityScorer`, `FreshnessScorer`, `PathDepthScorer`, `CompositeScorer`, `URLScorer`
- `DeepCrawlDecorator`, `FilterStats`

## Adaptive crawling
- `AdaptiveCrawler`, `AdaptiveConfig`, `CrawlState`, `CrawlStrategy`, `StatisticalStrategy`

## Dispatchers & concurrency (also under `crawl4ai.async_dispatcher`)
- `MemoryAdaptiveDispatcher` — memory-aware concurrency (recommended for batch)
- `SemaphoreDispatcher` — fixed concurrency
- `RateLimiter`, `BaseDispatcher`
- `CrawlerMonitor`, `DisplayMode` — live progress UI

## URL seeding / discovery
- `AsyncUrlSeeder`, `DomainMapper`, `DomainMapperConfig`, `LinkPreview`

## Proxy rotation
- `ProxyRotationStrategy`, `RoundRobinProxyStrategy`

## Chunking
- `ChunkingStrategy`, `RegexChunking`

## Logging / profiles
- `AsyncLogger`, `AsyncLoggerBase`, `BrowserProfiler`

## CLI
- `crwl <url> -o markdown` — crawl to markdown
- `crwl <url> --deep-crawl bfs --max-pages N`
- `crwl <url> -q "question"` — LLM extraction
- `crawl4ai-setup`, `crawl4ai-doctor` — install / health check
