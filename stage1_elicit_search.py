#!/usr/bin/env python3
"""
Stage 1: Elicit API Search → DOI List Extraction
=================================================
Research question을 Elicit API에 보내 관련 논문 DOI 리스트를 추출한다.

Usage:
    # config.yaml의 research_questions 사용
    python stage1_elicit_search.py

    # CLI에서 직접 query 지정
    python stage1_elicit_search.py --query "Bayesian inference in VWM" --collection "Bayesian_VWM"

    # 최대 결과 수 지정
    python stage1_elicit_search.py --query "..." --max-results 50

    # 필터 적용
    python stage1_elicit_search.py --query "..." --year-from 2015 --year-to 2025 --has-pdf
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import yaml


# ─── Config ─────────────────────────────────────────────────
def load_config(config_path: str = "config.yaml") -> dict:
    """config.yaml을 로드하고 필수 키를 검증한다."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(path) as f:
        cfg = yaml.safe_load(f)

    # Validate Elicit config
    elicit = cfg.get("elicit", {})
    if not elicit.get("api_key"):
        raise ValueError("elicit.api_key is required in config.yaml")
    return cfg


# ─── Logging ────────────────────────────────────────────────
def setup_logging(cfg: dict) -> logging.Logger:
    """파이프라인 로깅을 설정한다."""
    log_dir = Path(cfg.get("pipeline", {}).get("log_dir", "./logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_level = cfg.get("pipeline", {}).get("log_level", "INFO")

    logger = logging.getLogger("stage1")
    logger.setLevel(getattr(logging, log_level))

    # File handler
    fh = logging.FileHandler(
        log_dir / f"stage1_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    )
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(ch)

    return logger


# ─── Elicit Search API ──────────────────────────────────────
class ElicitSearchClient:
    """Elicit /v1/search API 클라이언트."""

    def __init__(self, api_key: str, base_url: str = "https://elicit.com/api/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    def search(
        self,
        query: str,
        max_results: int = 100,
        filters: dict | None = None,
    ) -> dict:
        """
        Elicit search API를 호출하여 논문 목록을 반환한다.

        Args:
            query: 자연어 research question
            max_results: 최대 반환 논문 수 (Pro: 1~100)
            filters: 검색 필터 (minYear, maxYear, hasPdf, typeTags 등)

        Returns:
            {"papers": [...], "metadata": {...}}
        """
        payload: dict[str, Any] = {
            "query": query,
            "maxResults": min(max_results, 100),  # Pro tier cap
        }
        if filters:
            payload["filters"] = filters

        resp = self.session.post(f"{self.base_url}/search", json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def search_paginated(
        self,
        query: str,
        total_results: int = 100,
        filters: dict | None = None,
        delay: float = 1.0,
        logger: logging.Logger | None = None,
    ) -> list[dict]:
        """
        100개 이상 결과가 필요할 때 반복 호출한다.
        Elicit은 offset/cursor를 지원하지 않으므로,
        maxResults를 직접 지정하는 방식으로 한 번에 가져온다.
        Pro tier 최대 100개/request이므로 100 이하면 1회 호출.

        Note: Pro tier는 100/request, 100 requests/day 제한
        """
        log = logger or logging.getLogger("stage1")
        all_papers = []

        # Pro tier는 한 번에 최대 100개
        batch_size = min(total_results, 100)
        result = self.search(query, max_results=batch_size, filters=filters)
        papers = result.get("papers", [])
        all_papers.extend(papers)
        log.info(f"  Retrieved {len(papers)} papers (requested {batch_size})")

        return all_papers


# ─── Elicit Reports API (on-demand) ─────────────────────────
class ElicitReportsClient:
    """Elicit /v1/reports API 클라이언트 (on-demand 사용)."""

    def __init__(self, api_key: str, base_url: str = "https://elicit.com/api/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        })

    def create_report(
        self,
        research_question: str,
        max_search_papers: int = 50,
        max_extract_papers: int = 10,
    ) -> dict:
        """Report 생성을 요청한다. 즉시 reportId를 반환."""
        payload = {
            "researchQuestion": research_question,
            "maxSearchPapers": max_search_papers,
            "maxExtractPapers": max_extract_papers,
        }
        resp = self.session.post(f"{self.base_url}/reports", json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def get_report(self, report_id: str, include_body: bool = False) -> dict:
        """Report 상태를 조회한다."""
        url = f"{self.base_url}/reports/{report_id}"
        if include_body:
            url += "?include=reportBody"
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def wait_for_report(
        self,
        report_id: str,
        poll_interval: int = 5,
        max_wait: int = 300,
        logger: logging.Logger | None = None,
    ) -> dict:
        """Report 완료까지 polling한다 (5~15분 소요)."""
        log = logger or logging.getLogger("stage1")
        elapsed = 0
        while elapsed < max_wait:
            result = self.get_report(report_id, include_body=True)
            status = result.get("status", "unknown")
            if status == "completed":
                log.info(f"  Report completed in {elapsed}s")
                return result
            elif status == "failed":
                raise RuntimeError(f"Report failed: {result}")
            log.info(f"  Report status: {status} ({elapsed}s elapsed)")
            time.sleep(poll_interval)
            elapsed += poll_interval
        raise TimeoutError(f"Report did not complete within {max_wait}s")


# ─── Output ─────────────────────────────────────────────────
def save_results(
    papers: list[dict],
    query: str,
    collection_name: str,
    output_dir: str = "./outputs",
) -> Path:
    """검색 결과를 JSON 파일로 저장한다."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = collection_name.replace(" ", "_")[:50]
    filename = f"stage1_{safe_name}_{timestamp}.json"
    filepath = out / filename

    # DOI 리스트만 별도 추출
    dois = [p["doi"] for p in papers if p.get("doi")]

    output = {
        "metadata": {
            "query": query,
            "collection_name": collection_name,
            "timestamp": datetime.now().isoformat(),
            "total_papers": len(papers),
            "papers_with_doi": len(dois),
        },
        "dois": dois,
        "papers": papers,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return filepath


def print_summary(papers: list[dict], query: str):
    """검색 결과 요약을 콘솔에 출력한다."""
    dois = [p["doi"] for p in papers if p.get("doi")]
    no_doi = [p for p in papers if not p.get("doi")]

    print(f"\n{'='*60}")
    print(f"Query: {query}")
    print(f"{'='*60}")
    print(f"Total papers:    {len(papers)}")
    print(f"With DOI:        {len(dois)}")
    print(f"Without DOI:     {len(no_doi)}")

    if papers:
        years = [p["year"] for p in papers if p.get("year")]
        if years:
            print(f"Year range:      {min(years)} - {max(years)}")

        citations = [p.get("citedByCount", 0) for p in papers]
        print(f"Citation range:  {min(citations)} - {max(citations)}")

    print(f"\nTop 5 papers:")
    for i, p in enumerate(papers[:5], 1):
        doi_str = p.get("doi", "NO DOI")
        cite = p.get("citedByCount", 0)
        print(f"  {i}. [{p.get('year','')}] {p.get('title','')[:70]}")
        print(f"     DOI: {doi_str}  |  Cited: {cite}")

    if no_doi:
        print(f"\n⚠ Papers without DOI (will be skipped in Stage 2):")
        for p in no_doi[:3]:
            print(f"  - {p.get('title','')[:70]}")
    print()


# ─── Filters Builder ────────────────────────────────────────
def build_filters(cfg: dict, args: argparse.Namespace) -> dict:
    """config와 CLI args를 결합하여 Elicit 필터를 구성한다."""
    filters = {}
    cfg_filters = cfg.get("elicit", {}).get("filters", {})

    # Year range (CLI overrides config)
    year_from = args.year_from or cfg_filters.get("year_from")
    year_to = args.year_to or cfg_filters.get("year_to")
    if year_from:
        filters["minYear"] = year_from
    if year_to:
        filters["maxYear"] = year_to

    # Boolean filters
    if args.has_pdf:
        filters["hasPdf"] = True

    # Study type
    study_type = cfg_filters.get("study_type")
    if study_type:
        filters["typeTags"] = [study_type] if isinstance(study_type, str) else study_type

    # Keywords
    if args.include_keywords:
        filters["includeKeywords"] = args.include_keywords
    if args.exclude_keywords:
        filters["excludeKeywords"] = args.exclude_keywords

    return filters if filters else {}


# ─── Main ───────────────────────────────────────────────────
def run_stage1(
    cfg: dict,
    queries: list[dict] | None = None,
    logger: logging.Logger | None = None,
    filters: dict | None = None,
    max_results: int | None = None,
) -> list[dict]:
    """
    Stage 1을 실행한다. 다른 스테이지에서 프로그래매틱하게 호출 가능.

    Args:
        cfg: config dict
        queries: [{"query": "...", "collection_name": "..."}]
        logger: logger instance
        filters: Elicit search filters
        max_results: override max results

    Returns:
        list of {"query": ..., "collection_name": ..., "papers": [...], "output_file": ...}
    """
    log = logger or logging.getLogger("stage1")
    elicit_cfg = cfg["elicit"]
    client = ElicitSearchClient(elicit_cfg["api_key"], elicit_cfg.get("base_url", "https://elicit.com/api/v1"))

    if queries is None:
        queries = cfg.get("research_questions", [])

    if not queries:
        log.error("No research questions provided")
        return []

    mr = max_results or elicit_cfg.get("max_results_per_query", 100)
    output_dir = cfg.get("extraction", {}).get("output_dir", "./outputs")
    results = []

    for i, q in enumerate(queries, 1):
        query_text = q["query"]
        collection = q.get("collection_name", f"search_{i}")
        log.info(f"[{i}/{len(queries)}] Searching: {query_text[:80]}...")

        try:
            papers = client.search_paginated(
                query=query_text,
                total_results=mr,
                filters=filters,
                logger=log,
            )
            outfile = save_results(papers, query_text, collection, output_dir)
            log.info(f"  → {len(papers)} papers saved to {outfile}")
            print_summary(papers, query_text)

            results.append({
                "query": query_text,
                "collection_name": collection,
                "papers": papers,
                "output_file": str(outfile),
            })

        except requests.HTTPError as e:
            log.error(f"  ❌ Elicit API error: {e.response.status_code} - {e.response.text[:200]}")
        except Exception as e:
            log.error(f"  ❌ Unexpected error: {e}")

        # Rate limit: 100 requests/day for Pro
        if i < len(queries):
            time.sleep(1)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Stage 1: Elicit API → DOI List Extraction"
    )
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--query", "-q", help="Override: single research question")
    parser.add_argument("--collection", "-c", help="Override: Zotero collection name")
    parser.add_argument("--max-results", "-n", type=int, help="Max results per query")
    parser.add_argument("--year-from", type=int, help="Filter: min publication year")
    parser.add_argument("--year-to", type=int, help="Filter: max publication year")
    parser.add_argument("--has-pdf", action="store_true", help="Filter: only papers with PDF")
    parser.add_argument("--include-keywords", nargs="+", help="Filter: include keywords")
    parser.add_argument("--exclude-keywords", nargs="+", help="Filter: exclude keywords")
    args = parser.parse_args()

    # Load config
    cfg = load_config(args.config)
    logger = setup_logging(cfg)
    logger.info("Stage 1: Elicit Search starting...")

    # Build queries
    if args.query:
        queries = [{"query": args.query, "collection_name": args.collection or "cli_search"}]
    else:
        queries = cfg.get("research_questions", [])

    # Build filters
    filters = build_filters(cfg, args)
    if filters:
        logger.info(f"Filters: {filters}")

    # Run
    results = run_stage1(
        cfg=cfg,
        queries=queries,
        logger=logger,
        filters=filters,
        max_results=args.max_results,
    )

    # Final summary
    total_papers = sum(len(r["papers"]) for r in results)
    total_dois = sum(len([p for p in r["papers"] if p.get("doi")]) for r in results)
    logger.info(f"\nStage 1 complete: {total_papers} papers found, {total_dois} with DOI")

    for r in results:
        logger.info(f"  → {r['collection_name']}: {r['output_file']}")

    return results


if __name__ == "__main__":
    main()
