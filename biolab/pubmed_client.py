"""Thin wrapper over PubMed E-utilities. No logging, no DB access — see retrieval_log.py."""

import json
import os
import threading
import time
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen
from xml.etree import ElementTree as ET  # only for tostring() — safe, no untrusted parsing

import defusedxml.ElementTree as SafeET  # parses untrusted network XML; guards against entity-expansion ("billion laughs") attacks

from biolab.auth import current_identity

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
TIMEOUT_SECONDS = 10
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_BACKOFF_SECONDS = 1.0

NCBI_API_KEY = os.environ.get("NCBI_API_KEY") or None
# NCBI raises the rate limit from 3 req/s to 10 req/s for callers that send an api_key.
REQUESTS_PER_SECOND = 10.0 if NCBI_API_KEY else 3.0


class _RateLimiter:
    """Thread-safe client-side pacer so a burst of concurrent MCP tool calls
    can't exceed NCBI's rate limit, whether or not an API key is configured."""

    def __init__(self, requests_per_second: float):
        self._min_interval = 1.0 / requests_per_second
        self._lock = threading.Lock()
        self._next_allowed_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start_at = max(now, self._next_allowed_at)
            self._next_allowed_at = start_at + self._min_interval
        sleep_for = start_at - now
        if sleep_for > 0:
            time.sleep(sleep_for)


_rate_limiter = _RateLimiter(REQUESTS_PER_SECOND)

# Per-caller fairness layer, on top of the global limiter above. Only engages
# when server.py's auth middleware has set an explicit identity (a real public
# HTTP request); CLI/direct API/test usage leaves current_identity at its
# default of None and behaves exactly as before — a single global budget.
ANONYMOUS_REQUESTS_PER_SECOND = 1.0
_identity_limiters: dict[str, _RateLimiter] = {}
_identity_limiters_lock = threading.Lock()


def _identity_limiter() -> "_RateLimiter | None":
    identity = current_identity.get()
    if identity is None:
        return None
    with _identity_limiters_lock:
        limiter = _identity_limiters.get(identity)
        if limiter is None:
            rate = ANONYMOUS_REQUESTS_PER_SECOND if identity == "anonymous" else REQUESTS_PER_SECOND
            limiter = _RateLimiter(rate)
            _identity_limiters[identity] = limiter
        return limiter


def _with_api_key(params: dict) -> dict:
    if NCBI_API_KEY:
        params = {**params, "api_key": NCBI_API_KEY}
    return params


def _urlopen_with_retry(url: str):
    """urlopen with backoff on HTTP 429 — NCBI's rate limit (3 req/s unauthenticated,
    10 req/s with an API key) is a known, transient constraint, not an application
    error worth failing on. Client-side pacing (_rate_limiter, _identity_limiter)
    should keep this from firing in normal operation; the retry is a safety net."""
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        id_limiter = _identity_limiter()
        if id_limiter is not None:
            id_limiter.wait()
        _rate_limiter.wait()
        try:
            return urlopen(url, timeout=TIMEOUT_SECONDS)
        except HTTPError as e:
            if e.code == 429 and attempt < RATE_LIMIT_RETRIES:
                time.sleep(RATE_LIMIT_BACKOFF_SECONDS * (attempt + 1))
                continue
            raise


@dataclass
class PubMedPaper:
    pmid: str
    title: str
    abstract: str
    medline_status: str  # verbatim MedlineCitation/@Status, e.g. "MEDLINE", "Publisher"
    pub_status: str      # verbatim PubmedData/PublicationStatus, e.g. "ppublish", "aheadofprint"
    raw_xml: str          # this paper's own <PubmedArticle> element, verbatim


def search(query: str, max_results: int) -> list[str]:
    """esearch: query string -> list of PMIDs."""
    params = urlencode(_with_api_key({
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": max_results,
    }))
    with _urlopen_with_retry(f"{ESEARCH_URL}?{params}") as resp:
        data = json.load(resp)
    return data["esearchresult"]["idlist"]


def fetch(pmids: list[str]) -> list[PubMedPaper]:
    """efetch: PMIDs -> parsed paper records, each carrying its own raw XML snapshot."""
    if not pmids:
        return []
    params = urlencode(_with_api_key({
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "abstract",
        "retmode": "xml",
    }))
    with _urlopen_with_retry(f"{EFETCH_URL}?{params}") as resp:
        root = SafeET.fromstring(resp.read())
    return [_parse_article(article) for article in root.findall("PubmedArticle")]


def search_and_fetch(query: str, max_results: int) -> list[PubMedPaper]:
    return fetch(search(query, max_results))


def _full_text(element: ET.Element | None) -> str:
    """Concatenate all text in an element, including inline markup like <sup>/<i>.

    .text / .findtext() only return text up to the first child element, which
    silently truncates real PubMed titles (e.g. "m<sup>5</sup>C" drops everything
    after the <sup> tag).
    """
    return "".join(element.itertext()) if element is not None else ""


def _parse_article(article: ET.Element) -> PubMedPaper:
    medline_citation = article.find("MedlineCitation")
    if medline_citation is None:
        raise ValueError("PubmedArticle missing required MedlineCitation element")
    pmid = medline_citation.findtext("PMID") or ""
    title = _full_text(medline_citation.find(".//ArticleTitle"))
    abstract = " ".join(
        _full_text(node) for node in medline_citation.findall(".//AbstractText")
    )
    medline_status = medline_citation.get("Status") or ""
    pub_status = article.findtext(".//PublicationStatus") or ""
    return PubMedPaper(
        pmid=pmid,
        title=title,
        abstract=abstract,
        medline_status=medline_status,
        pub_status=pub_status,
        raw_xml=ET.tostring(article, encoding="unicode"),
    )


def paper_to_retrieval_input(paper: PubMedPaper) -> dict:
    """Convert PubMedPaper to the input format expected by retrieval_log.write_retrieval."""
    import defusedxml.ElementTree as SafeET

    root = SafeET.fromstring(paper.raw_xml)
    medline_citation = root.find("MedlineCitation")
    article = medline_citation.find("Article") if medline_citation is not None else None

    def full_text(elem):
        return "".join(elem.itertext()) if elem is not None else ""

    title = full_text(article.find(".//ArticleTitle")) if article is not None else ""
    abstract = " ".join(
        full_text(node)
        for node in medline_citation.findall(".//AbstractText")
    ) if medline_citation is not None else ""

    authors = []
    if article is not None:
        for author in article.findall(".//Author"):
            lastname = full_text(author.find("LastName"))
            fore = full_text(author.find("ForeName"))
            initials = full_text(author.find("Initials"))
            if lastname or fore or initials:
                authors.append({
                    "lastname": lastname,
                    "forename": fore,
                    "initials": initials,
                })

    journal = {}
    if article is not None:
        journal_elem = article.find(".//Journal")
        if journal_elem is not None:
            journal = {
                "title": full_text(journal_elem.find("Title")),
                "iso_abbreviation": full_text(journal_elem.find("ISOAbbreviation")),
                "issn": full_text(journal_elem.find(".//ISSN")),
                "pub_date": full_text(journal_elem.find(".//PubDate")),
            }

    pub_types = [
        full_text(pt) for pt in root.findall(".//PublicationType")
    ]

    mesh_terms = [
        full_text(mh.find("DescriptorName"))
        for mh in root.findall(".//MeshHeading")
        if mh.find("DescriptorName") is not None
    ]

    doi = ""
    for id_elem in root.findall(".//ArticleId"):
        if id_elem.get("IdType") == "doi":
            doi = full_text(id_elem)
            break

    snapshot = {
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "journal": journal,
        "publication_types": pub_types,
        "mesh_terms": mesh_terms,
        "doi": doi,
        "medline_status": paper.medline_status,
        "pub_status": paper.pub_status,
    }

    source_metadata = {
        "medline_status": paper.medline_status,
        "pub_status": paper.pub_status,
    }

    return {
        "source": "pubmed",
        "external_id": paper.pmid,
        "source_metadata": source_metadata,
        "raw_response": paper.raw_xml,
        "snapshot": snapshot,
    }
