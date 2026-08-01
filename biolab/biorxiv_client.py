"""Thin wrapper over the bioRxiv/medRxiv details API. No logging, no DB access — see retrieval_log.py.

No free-text search endpoint exists on this API — only date-range + category listing. Any
"search" here is really "list preprints from the last 30 days, filtered by category."
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.request import urlopen

BASE_URL = "https://api.biorxiv.org"
TIMEOUT_SECONDS = 15
PAGE_SIZE = 100


@dataclass
class BioRxivPreprint:
    title: str
    authors: str
    doi: str
    date: str
    category: str
    type: str
    abstract: str
    jatsxml: str
    full_jats_xml: str  # empty when the JATS URL doesn't resolve — best effort


def _list_by_date_range(server: str, start_date: str, end_date: str, category: str, max_results: int) -> list[dict]:
    preprints: list[dict] = []
    cursor = 0
    while len(preprints) < max_results:
        url = f"{BASE_URL}/details/{server}/{start_date}/{end_date}/{cursor}"
        with urlopen(url, timeout=TIMEOUT_SECONDS) as resp:
            data = json.load(resp)
        collection = data.get("collection") or []
        if not collection:
            break
        for p in collection:
            if len(preprints) >= max_results:
                break
            if category and category != "all" and p.get("category", "").lower() != category.lower():
                continue
            preprints.append(p)
        if len(collection) < PAGE_SIZE:
            break
        cursor += PAGE_SIZE
    return preprints


def fetch_jats_xml(jats_url: str) -> str:
    """Best-effort full JATS XML fetch — not every preprint's URL resolves."""
    if not jats_url:
        return ""
    try:
        with urlopen(jats_url, timeout=TIMEOUT_SECONDS) as resp:
            return resp.read().decode("utf-8")
    except Exception:
        return ""


def list_and_fetch(server: str, category: str, max_results: int) -> list[BioRxivPreprint]:
    """List preprints from the last 30 days for a category (the API requires a date range)."""
    end_date = datetime.now(UTC).strftime("%Y-%m-%d")
    start_date = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")

    raw_preprints = _list_by_date_range(server, start_date, end_date, category, max_results)
    return [
        BioRxivPreprint(
            title=p.get("title", ""),
            authors=p.get("authors", ""),
            doi=p.get("doi", ""),
            date=p.get("date", ""),
            category=p.get("category", ""),
            type=p.get("type", ""),
            abstract=p.get("abstract", ""),
            jatsxml=p.get("jatsxml", ""),
            full_jats_xml=fetch_jats_xml(p.get("jatsxml", "")),
        )
        for p in raw_preprints
    ]


def _parse_authors(author_string: str) -> list[dict]:
    """Author string format: "Sinha, A. K.; Lee, C.; Holt, J. C."."""
    if not author_string:
        return []
    authors = []
    for raw_part in author_string.split(";"):
        part = raw_part.strip()
        if not part:
            continue
        if "," in part:
            lastname, initials = part.split(",", 1)
            authors.append({"lastname": lastname.strip(), "initials": initials.strip()})
        else:
            authors.append({"lastname": part})
    return authors


def paper_to_retrieval_input(preprint: BioRxivPreprint, server: str) -> dict:
    """Convert BioRxivPreprint to the input format expected by retrieval_log.write_retrieval."""
    external_id = preprint.doi or f"{preprint.date}-{preprint.category}"

    snapshot = {
        "title": preprint.title,
        "abstract": preprint.abstract,
        "authors": _parse_authors(preprint.authors),
        "journal": {"title": "bioRxiv", "pub_date": preprint.date},
        "publication_types": [t for t in ("preprint", preprint.type) if t],
        "doi": preprint.doi,
    }

    # bioRxiv has no PubMed-style pub_status field; a hash of the raw response
    # stands in, so the source_metadata shape stays consistent across sources.
    jats_hash = hashlib.sha256(preprint.full_jats_xml.encode("utf-8")).hexdigest()
    source_metadata = {
        "medline_status": preprint.category,
        "pub_status": f"{server}:{jats_hash[:24]}",
    }

    return {
        "source": "biorxiv",
        "external_id": external_id,
        "source_metadata": source_metadata,
        "raw_response": preprint.full_jats_xml,
        "snapshot": snapshot,
    }
