"""Thin wrapper over PubMed E-utilities. No logging, no DB access — see retrieval_log.py."""

from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import urlopen
from xml.etree import ElementTree as ET  # only for tostring() — safe, no untrusted parsing
import json

import defusedxml.ElementTree as SafeET  # parses untrusted network XML; guards against
                                          # entity-expansion ("billion laughs") attacks

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
TIMEOUT_SECONDS = 10


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
    params = urlencode({
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": max_results,
    })
    with urlopen(f"{ESEARCH_URL}?{params}", timeout=TIMEOUT_SECONDS) as resp:
        data = json.load(resp)
    return data["esearchresult"]["idlist"]


def fetch(pmids: list[str]) -> list[PubMedPaper]:
    """efetch: PMIDs -> parsed paper records, each carrying its own raw XML snapshot."""
    if not pmids:
        return []
    params = urlencode({
        "db": "pubmed",
        "id": ",".join(pmids),
        "rettype": "abstract",
        "retmode": "xml",
    })
    with urlopen(f"{EFETCH_URL}?{params}", timeout=TIMEOUT_SECONDS) as resp:
        root = SafeET.fromstring(resp.read())
    return [_parse_article(article) for article in root.findall("PubmedArticle")]


def search_and_fetch(query: str, max_results: int) -> list[PubMedPaper]:
    return fetch(search(query, max_results))


def _full_text(element: ET.Element | None) -> str:
    """Concatenate all text in an element, including inline markup like <sup>/<i>.

    .text / .findtext() only return text up to the first child element, which
    silently truncates real PubMed titles (e.g. "m<sup>5</sup>C" drops everything
    after the <sup> tag). See QUESTIONS_AND_ANSWERS.md for the real PMID this bug
    was caught on.
    """
    return "".join(element.itertext()) if element is not None else ""


def _parse_article(article: ET.Element) -> PubMedPaper:
    medline_citation = article.find("MedlineCitation")
    pmid = medline_citation.findtext("PMID")
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
