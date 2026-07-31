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
    after the <sup> tag).
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
