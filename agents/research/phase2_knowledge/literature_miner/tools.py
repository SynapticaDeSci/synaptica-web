"""Tools for Literature Miner agent — real academic search APIs."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (compatible; SynapticaResearch/1.0)"
ACADEMIC_SOURCE_SEARCH_FANOUT = 4

# ---------------------------------------------------------------------------
# ArXiv API (free, no key)
# ---------------------------------------------------------------------------

_ARXIV_API_URL = "http://export.arxiv.org/api/query"
_ARXIV_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


async def search_arxiv(
    keywords: List[str],
    max_results: int = 20,
    date_range: Optional[str] = None,
) -> Dict[str, Any]:
    """Search ArXiv for relevant papers using the real ArXiv API.

    Args:
        keywords: Search keywords.
        max_results: Maximum number of results (capped at 50).
        date_range: Unused — kept for interface compatibility.

    Returns:
        Dict with ``source``, ``papers``, ``total_found``, ``search_query``, ``searched_at``.
    """
    query = "+AND+".join(f"all:{quote_plus(kw)}" for kw in keywords[:8])
    capped = max(1, min(int(max_results), 50))
    params = {
        "search_query": query,
        "start": 0,
        "max_results": capped,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }

    papers: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(_ARXIV_API_URL, params=params)
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        for entry in root.findall("atom:entry", _ARXIV_NS):
            title_el = entry.find("atom:title", _ARXIV_NS)
            summary_el = entry.find("atom:summary", _ARXIV_NS)
            published_el = entry.find("atom:published", _ARXIV_NS)
            id_el = entry.find("atom:id", _ARXIV_NS)

            title = re.sub(r"\s+", " ", (title_el.text or "").strip()) if title_el is not None else ""
            abstract = re.sub(r"\s+", " ", (summary_el.text or "").strip()) if summary_el is not None else ""
            published_raw = (published_el.text or "").strip() if published_el is not None else ""
            arxiv_url = (id_el.text or "").strip() if id_el is not None else ""
            arxiv_id = arxiv_url.rsplit("/abs/", 1)[-1] if "/abs/" in arxiv_url else ""

            authors = []
            for author_el in entry.findall("atom:author", _ARXIV_NS):
                name_el = author_el.find("atom:name", _ARXIV_NS)
                if name_el is not None and name_el.text:
                    authors.append(name_el.text.strip())

            published_date = None
            if published_raw:
                try:
                    published_date = datetime.fromisoformat(
                        published_raw.replace("Z", "+00:00")
                    ).strftime("%Y-%m-%d")
                except ValueError:
                    pass

            if not title:
                continue

            papers.append({
                "title": title[:300],
                "authors": authors,
                "abstract": abstract[:4000],
                "published_date": published_date,
                "journal": None,
                "arxiv_id": arxiv_id,
                "doi": None,
                "url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else arxiv_url,
                "source": "ArXiv",
                "citations_count": 0,
                "relevance_score": 0.7,
            })
    except Exception as exc:
        logger.warning("ArXiv search failed: %s", exc)

    return {
        "source": "ArXiv",
        "papers": papers[:capped],
        "total_found": len(papers),
        "search_query": query,
        "searched_at": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Semantic Scholar API (free, optional API key for higher rate limits)
# ---------------------------------------------------------------------------

_S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_S2_CITATIONS_URL = "https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations"
_S2_FIELDS = "title,authors,abstract,year,citationCount,externalIds,url,publicationDate"


def _s2_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {"User-Agent": _USER_AGENT}
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()
    if api_key:
        headers["x-api-key"] = api_key
    return headers


async def search_semantic_scholar(
    keywords: List[str],
    max_results: int = 20,
    min_citations: Optional[int] = None,
) -> Dict[str, Any]:
    """Search Semantic Scholar for relevant papers.

    Args:
        keywords: Search keywords.
        max_results: Maximum results (capped at 100).
        min_citations: Optional minimum citation count filter.

    Returns:
        Dict with ``source``, ``papers``, ``total_found``, ``search_query``, ``searched_at``.
    """
    query = " ".join(keywords[:10])
    capped = max(1, min(int(max_results), 100))
    params = {
        "query": query,
        "limit": capped,
        "fields": _S2_FIELDS,
    }

    papers: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(_S2_SEARCH_URL, params=params, headers=_s2_headers())
            resp.raise_for_status()

        data = resp.json()
        for item in data.get("data") or []:
            citations = item.get("citationCount") or 0
            if min_citations is not None and citations < min_citations:
                continue

            authors = [
                a.get("name", "Unknown")
                for a in (item.get("authors") or [])
                if isinstance(a, dict)
            ]
            external_ids = item.get("externalIds") or {}
            doi = external_ids.get("DOI")
            arxiv_id = external_ids.get("ArXiv")
            pmid = external_ids.get("PubMed")

            pub_date = item.get("publicationDate")
            if not pub_date and item.get("year"):
                pub_date = f"{item['year']}-01-01"

            url = item.get("url") or ""
            if doi and not url:
                url = f"https://doi.org/{doi}"
            elif arxiv_id and not url:
                url = f"https://arxiv.org/abs/{arxiv_id}"

            title = (item.get("title") or "").strip()
            if not title:
                continue

            papers.append({
                "title": title[:300],
                "authors": authors,
                "abstract": (item.get("abstract") or "")[:4000],
                "published_date": pub_date,
                "journal": None,
                "arxiv_id": arxiv_id,
                "doi": doi,
                "pmid": pmid,
                "url": url,
                "source": "Semantic Scholar",
                "citations_count": citations,
                "relevance_score": 0.7,
                "s2_paper_id": item.get("paperId"),
            })
    except Exception as exc:
        logger.warning("Semantic Scholar search failed: %s", exc)

    return {
        "source": "Semantic Scholar",
        "papers": papers,
        "total_found": len(papers),
        "search_query": query,
        "searched_at": datetime.utcnow().isoformat(),
    }


async def fetch_semantic_scholar_citations(
    paper_id: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Fetch papers that cite a given Semantic Scholar paper (for iterative deepening).

    Args:
        paper_id: Semantic Scholar paper ID.
        limit: Max number of citing papers to return.

    Returns:
        List of paper dicts in the same format as search results.
    """
    url = _S2_CITATIONS_URL.format(paper_id=paper_id)
    params = {
        "fields": "title,authors,abstract,year,citationCount,externalIds,url,publicationDate",
        "limit": max(1, min(limit, 100)),
    }
    papers: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params, headers=_s2_headers())
            resp.raise_for_status()

        data = resp.json()
        for entry in data.get("data") or []:
            item = entry.get("citingPaper") or {}
            title = (item.get("title") or "").strip()
            if not title:
                continue

            authors = [
                a.get("name", "Unknown")
                for a in (item.get("authors") or [])
                if isinstance(a, dict)
            ]
            external_ids = item.get("externalIds") or {}
            doi = external_ids.get("DOI")
            pub_date = item.get("publicationDate")
            if not pub_date and item.get("year"):
                pub_date = f"{item['year']}-01-01"

            papers.append({
                "title": title[:300],
                "authors": authors,
                "abstract": (item.get("abstract") or "")[:4000],
                "published_date": pub_date,
                "journal": None,
                "arxiv_id": external_ids.get("ArXiv"),
                "doi": doi,
                "url": item.get("url") or (f"https://doi.org/{doi}" if doi else ""),
                "source": "Semantic Scholar (citation)",
                "citations_count": item.get("citationCount") or 0,
                "relevance_score": 0.6,
                "s2_paper_id": item.get("paperId"),
            })
    except Exception as exc:
        logger.warning("Semantic Scholar citations fetch failed for %s: %s", paper_id, exc)

    return papers


# ---------------------------------------------------------------------------
# PubMed / NCBI E-utilities API (free, optional API key)
# ---------------------------------------------------------------------------

_PUBMED_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_PUBMED_FETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


async def search_pubmed(
    keywords: List[str],
    max_results: int = 20,
) -> Dict[str, Any]:
    """Search PubMed for relevant biomedical literature.

    Args:
        keywords: Search keywords.
        max_results: Maximum results (capped at 50).

    Returns:
        Dict with ``source``, ``papers``, ``total_found``, ``search_query``, ``searched_at``.
    """
    query = " AND ".join(f'"{kw}"' if " " in kw else kw for kw in keywords[:8])
    capped = max(1, min(int(max_results), 50))

    api_key = os.getenv("NCBI_API_KEY", "").strip()
    base_params: Dict[str, Any] = {}
    if api_key:
        base_params["api_key"] = api_key

    papers: List[Dict[str, Any]] = []
    try:
        # Step 1: Search for PMIDs
        search_params = {
            **base_params,
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": capped,
            "sort": "relevance",
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            search_resp = await client.get(_PUBMED_SEARCH_URL, params=search_params)
            search_resp.raise_for_status()

        search_data = search_resp.json()
        id_list = (search_data.get("esearchresult") or {}).get("idlist") or []
        if not id_list:
            return {
                "source": "PubMed",
                "papers": [],
                "total_found": 0,
                "search_query": query,
                "searched_at": datetime.utcnow().isoformat(),
            }

        # Step 2: Fetch article details
        fetch_params = {
            **base_params,
            "db": "pubmed",
            "id": ",".join(id_list),
            "retmode": "xml",
            "rettype": "abstract",
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            fetch_resp = await client.get(_PUBMED_FETCH_URL, params=fetch_params)
            fetch_resp.raise_for_status()

        root = ET.fromstring(fetch_resp.text)
        for article_el in root.findall(".//PubmedArticle"):
            medline = article_el.find("MedlineCitation")
            if medline is None:
                continue
            article = medline.find("Article")
            if article is None:
                continue

            title_el = article.find("ArticleTitle")
            title = "".join(title_el.itertext()).strip() if title_el is not None else ""
            if not title:
                continue

            # Abstract
            abstract_parts: List[str] = []
            abstract_el = article.find("Abstract")
            if abstract_el is not None:
                for text_el in abstract_el.findall("AbstractText"):
                    label = text_el.get("Label", "")
                    text = "".join(text_el.itertext()).strip()
                    if label:
                        abstract_parts.append(f"{label}: {text}")
                    else:
                        abstract_parts.append(text)
            abstract = " ".join(abstract_parts)

            # Authors
            authors: List[str] = []
            author_list = article.find("AuthorList")
            if author_list is not None:
                for author_el in author_list.findall("Author"):
                    last = author_el.find("LastName")
                    first = author_el.find("ForeName")
                    if last is not None and last.text:
                        name = last.text.strip()
                        if first is not None and first.text:
                            name = f"{first.text.strip()} {name}"
                        authors.append(name)

            # Journal
            journal_el = article.find("Journal/Title")
            journal = (journal_el.text or "").strip() if journal_el is not None else None

            # Publication date
            pub_date = None
            pub_date_el = article.find("Journal/JournalIssue/PubDate")
            if pub_date_el is not None:
                year_el = pub_date_el.find("Year")
                month_el = pub_date_el.find("Month")
                day_el = pub_date_el.find("Day")
                if year_el is not None and year_el.text:
                    year = year_el.text.strip()
                    month = (month_el.text.strip() if month_el is not None and month_el.text else "01")
                    day = (day_el.text.strip() if day_el is not None and day_el.text else "01")
                    month_map = {
                        "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
                        "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
                        "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
                    }
                    month = month_map.get(month, month)
                    try:
                        pub_date = f"{year}-{int(month):02d}-{int(day):02d}"
                    except (ValueError, TypeError):
                        pub_date = f"{year}-01-01"

            # PMID
            pmid_el = medline.find("PMID")
            pmid = (pmid_el.text or "").strip() if pmid_el is not None else ""

            # DOI
            doi = None
            article_id_list = article_el.find("PubmedData/ArticleIdList")
            if article_id_list is not None:
                for aid in article_id_list.findall("ArticleId"):
                    if aid.get("IdType") == "doi" and aid.text:
                        doi = aid.text.strip()
                        break

            papers.append({
                "title": title[:300],
                "authors": authors,
                "abstract": abstract[:4000],
                "published_date": pub_date,
                "journal": journal,
                "arxiv_id": None,
                "doi": doi,
                "pmid": pmid,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else (f"https://doi.org/{doi}" if doi else ""),
                "source": "PubMed",
                "citations_count": 0,
                "relevance_score": 0.7,
            })
    except Exception as exc:
        logger.warning("PubMed search failed: %s", exc)

    return {
        "source": "PubMed",
        "papers": papers,
        "total_found": len(papers),
        "search_query": query,
        "searched_at": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# OpenAlex API (free, no key required)
# ---------------------------------------------------------------------------

_OPENALEX_SEARCH_URL = "https://api.openalex.org/works"


def _reconstruct_openalex_abstract(inverted_index: Dict[str, List[int]]) -> str:
    """Reconstruct abstract text from OpenAlex inverted index format."""
    if not inverted_index:
        return ""
    position_word: List[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            position_word.append((pos, word))
    position_word.sort(key=lambda x: x[0])
    return " ".join(w for _, w in position_word)


async def search_openalex(
    keywords: List[str],
    max_results: int = 25,
) -> Dict[str, Any]:
    """Search OpenAlex for scholarly works.

    Args:
        keywords: Search keywords.
        max_results: Maximum results (capped at 50).

    Returns:
        Dict with ``source``, ``papers``, ``total_found``, ``search_query``, ``searched_at``.
    """
    query = " ".join(keywords[:10])
    capped = max(1, min(int(max_results), 50))
    params: Dict[str, Any] = {
        "search": query,
        "per_page": capped,
        "mailto": "research@synaptica.ai",
    }

    papers: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                _OPENALEX_SEARCH_URL,
                params=params,
                headers={"User-Agent": _USER_AGENT},
            )
            resp.raise_for_status()

        data = resp.json()
        for item in data.get("results") or []:
            title = (item.get("title") or "").strip()
            if not title:
                continue

            abstract = _reconstruct_openalex_abstract(
                item.get("abstract_inverted_index") or {}
            )

            authors = []
            for authorship in (item.get("authorships") or []):
                author_obj = authorship.get("author") or {}
                name = (author_obj.get("display_name") or "").strip()
                if name:
                    authors.append(name)

            doi = item.get("doi") or ""
            if doi.startswith("https://doi.org/"):
                doi = doi[len("https://doi.org/"):]

            pub_date = item.get("publication_date")
            year = item.get("publication_year")
            if not pub_date and year:
                pub_date = f"{year}-01-01"

            # Best open-access URL
            oa = item.get("open_access") or {}
            oa_url = oa.get("oa_url") or ""
            url = oa_url or (f"https://doi.org/{doi}" if doi else "")

            # Primary location for journal
            primary = item.get("primary_location") or {}
            source_obj = primary.get("source") or {}
            journal = (source_obj.get("display_name") or "").strip() or None

            papers.append({
                "title": title[:300],
                "authors": authors,
                "abstract": abstract[:4000],
                "published_date": pub_date,
                "journal": journal,
                "arxiv_id": None,
                "doi": doi or None,
                "url": url,
                "source": "OpenAlex",
                "citations_count": item.get("cited_by_count") or 0,
                "relevance_score": 0.7,
            })
    except Exception as exc:
        logger.warning("OpenAlex search failed: %s", exc)

    return {
        "source": "OpenAlex",
        "papers": papers,
        "total_found": len(papers),
        "search_query": query,
        "searched_at": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# Parallel academic search across all sources
# ---------------------------------------------------------------------------


async def search_all_academic_sources(
    keywords: List[str],
    max_results_per_source: int = 20,
) -> List[Dict[str, Any]]:
    """Run ArXiv, Semantic Scholar, PubMed, and OpenAlex searches in parallel.

    Returns a flat list of all papers found across all sources.
    """
    results = await asyncio.gather(
        search_arxiv(keywords, max_results=max_results_per_source),
        search_semantic_scholar(keywords, max_results=max_results_per_source),
        search_pubmed(keywords, max_results=max_results_per_source),
        search_openalex(keywords, max_results=max_results_per_source),
        return_exceptions=True,
    )
    all_papers: List[Dict[str, Any]] = []
    for result in results:
        if isinstance(result, Exception):
            logger.warning("Academic source search error: %s", result)
            continue
        if isinstance(result, dict):
            all_papers.extend(result.get("papers") or [])
    return all_papers


# ---------------------------------------------------------------------------
# Utility functions (kept from original, still used by the agent)
# ---------------------------------------------------------------------------


async def calculate_relevance_score(
    paper: Dict[str, Any],
    keywords: List[str],
    research_question: str,
) -> float:
    """Calculate relevance score for a paper.

    Args:
        paper: Paper metadata.
        keywords: Research keywords.
        research_question: The research question.

    Returns:
        Relevance score (0-1).
    """
    score = 0.0

    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
    keyword_matches = sum(1 for kw in keywords if kw.lower() in text)
    keyword_score = min(keyword_matches / max(len(keywords), 1), 1.0) * 0.4
    score += keyword_score

    rq_words = research_question.lower().split()
    rq_matches = sum(1 for word in rq_words if len(word) > 3 and word in text)
    rq_score = min(rq_matches / max(len(rq_words), 1), 1.0) * 0.3
    score += rq_score

    if "published_date" in paper and paper["published_date"]:
        try:
            pub_date = datetime.fromisoformat(str(paper["published_date"]))
            days_old = (datetime.now() - pub_date).days
            if days_old < 365:
                recency_score = 0.15
            elif days_old < 730:
                recency_score = 0.12
            elif days_old < 1095:
                recency_score = 0.08
            else:
                recency_score = 0.05
            score += recency_score
        except (ValueError, TypeError):
            score += 0.075
    else:
        score += 0.075

    citations = paper.get("citations_count") or 0
    if citations > 50:
        citation_score = 0.15
    elif citations > 20:
        citation_score = 0.12
    elif citations > 10:
        citation_score = 0.08
    elif citations > 5:
        citation_score = 0.05
    else:
        citation_score = 0.02
    score += citation_score

    return round(min(score, 1.0), 2)


async def deduplicate_papers(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate papers from multiple sources.

    Args:
        papers: List of papers from various sources.

    Returns:
        Deduplicated list of papers.
    """
    seen: Dict[str, int] = {}
    unique_papers: List[Dict[str, Any]] = []

    for paper in papers:
        title = re.sub(r"\s+", " ", (paper.get("title") or "").strip().lower())
        first_author = ""
        authors = paper.get("authors")
        if isinstance(authors, list) and authors:
            first_author = str(authors[0]).lower().strip()
        signature = f"{title[:50]}_{first_author}"

        # Also dedupe by DOI if available
        doi = (paper.get("doi") or "").strip().lower()
        doi_key = f"doi:{doi}" if doi else ""

        existing_idx = seen.get(signature)
        if existing_idx is None and doi_key:
            existing_idx = seen.get(doi_key)
        if existing_idx is not None:
            existing = unique_papers[existing_idx]
            if not existing.get("doi") and paper.get("doi"):
                existing["doi"] = paper["doi"]
            if not existing.get("arxiv_id") and paper.get("arxiv_id"):
                existing["arxiv_id"] = paper["arxiv_id"]
            if not existing.get("abstract") and paper.get("abstract"):
                existing["abstract"] = paper["abstract"]
            if (paper.get("citations_count") or 0) > (existing.get("citations_count") or 0):
                existing["citations_count"] = paper["citations_count"]
        else:
            idx = len(unique_papers)
            seen[signature] = idx
            if doi_key:
                seen[doi_key] = idx
            unique_papers.append(paper)

    return unique_papers


async def rank_papers_by_relevance(
    papers: List[Dict[str, Any]],
    keywords: List[str],
    research_question: str,
    top_n: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Rank papers by relevance to research question.

    Args:
        papers: List of papers to rank.
        keywords: Research keywords.
        research_question: The research question.
        top_n: Return only top N papers.

    Returns:
        Ranked list of papers.
    """
    for paper in papers:
        paper["relevance_score"] = await calculate_relevance_score(
            paper, keywords, research_question
        )

    papers.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

    if top_n:
        return papers[:top_n]
    return papers


async def create_paper_url(paper: Dict[str, Any]) -> str:
    """Create URL for accessing the paper."""
    if paper.get("arxiv_id"):
        return f"https://arxiv.org/abs/{paper['arxiv_id']}"
    if paper.get("doi"):
        return f"https://doi.org/{paper['doi']}"
    if paper.get("pmid"):
        return f"https://pubmed.ncbi.nlm.nih.gov/{paper['pmid']}/"
    if paper.get("url"):
        return paper["url"]
    title = (paper.get("title") or "").replace(" ", "+")
    return f"https://scholar.google.com/scholar?q={title}"


async def extract_paper_metadata(raw_paper_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract and normalize paper metadata from raw source data."""
    authors = raw_paper_data.get("authors", [])
    if isinstance(authors, str):
        authors = [a.strip() for a in authors.split(",")]

    pub_date = raw_paper_data.get("published_date", "")
    if pub_date and not str(pub_date).startswith("20"):
        try:
            pub_date = datetime.fromisoformat(str(pub_date)).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pub_date = None

    return {
        "title": raw_paper_data.get("title", "Unknown Title"),
        "authors": authors,
        "abstract": raw_paper_data.get("abstract", "No abstract available"),
        "published_date": pub_date,
        "journal": raw_paper_data.get("journal"),
        "arxiv_id": raw_paper_data.get("arxiv_id"),
        "doi": raw_paper_data.get("doi"),
        "url": await create_paper_url(raw_paper_data),
        "citations_count": raw_paper_data.get("citations_count"),
        "source": raw_paper_data.get("source", "Unknown"),
    }


async def search_web_for_research(
    keywords: List[str],
    research_question: str,
    max_results: int = 10,
) -> Dict[str, Any]:
    """Search the web for research papers and technical resources.

    Uses DuckDuckGo HTML scraping as a lightweight fallback web search.

    Args:
        keywords: Search keywords.
        research_question: The research question.
        max_results: Maximum results.

    Returns:
        Dict with web search results formatted as papers.
    """
    papers: List[Dict[str, Any]] = []
    query = " ".join(keywords[:5])

    try:
        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                search_url,
                headers={"User-Agent": _USER_AGENT},
            )
            if response.status_code == 200:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(response.text, "html.parser")
                for result in soup.select(".result")[:max_results]:
                    link = result.select_one(".result__a")
                    snippet = result.select_one(".result__snippet")
                    if link is None:
                        continue
                    href = link.get("href", "")
                    text = link.get_text(strip=True)
                    if not text or not href:
                        continue
                    papers.append({
                        "title": text[:200],
                        "authors": ["Web Source"],
                        "abstract": (snippet.get_text(" ", strip=True) if snippet else "")[:2000],
                        "published_date": None,
                        "journal": None,
                        "arxiv_id": None,
                        "doi": None,
                        "url": href,
                        "source": "Web Search",
                        "citations_count": 0,
                        "relevance_score": 0.5,
                    })
    except Exception as exc:
        logger.warning("Web search for research failed: %s", exc)

    return {
        "source": "Web Search",
        "papers": papers[:max_results],
        "total_found": len(papers),
        "search_query": query,
        "searched_at": datetime.utcnow().isoformat(),
    }
