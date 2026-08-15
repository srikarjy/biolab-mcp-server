"""Retraction status for PubMed papers, from PubMed's own record metadata.

A retracted paper's MedlineCitation carries two independent markers, either of
which is authoritative:
  - a PublicationType of "Retracted Publication" in PublicationTypeList
  - a CommentsCorrections entry with RefType="RetractionIn", which also names
    the retraction notice (its citation string and PMID)

Both are checked; PubMed's indexing lag means one can appear before the other.
"Expression of Concern In" is surfaced separately — it is a formal editorial
warning, not a retraction, and conflating the two would overstate the record.

No logging or DB access here (same separation as pubmed_client.py); the
server-side tool wrapper is responsible for the audit trail.
"""

from dataclasses import dataclass
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

import defusedxml.ElementTree as SafeET

from biolab.pubmed_client import EFETCH_URL, _urlopen_with_retry, _with_api_key


@dataclass
class RetractionStatus:
    pmid: str
    retracted: bool
    concern: bool  # formal Expression of Concern (not a retraction)
    # Citation string of the retraction notice, when PubMed links one.
    notice: str
    notice_pmid: str


def check(pmids: list[str]) -> list[RetractionStatus]:
    """efetch the PMIDs and read each record's retraction markers.

    A PMID that PubMed doesn't return (bad id, suppressed record) is simply
    absent from the result — callers must not treat absence as "not retracted".
    """
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
    return [_parse_status(article) for article in root.findall("PubmedArticle")]


def _parse_status(article: ET.Element) -> RetractionStatus:
    citation = article.find("MedlineCitation")
    if citation is None:
        raise ValueError("PubmedArticle missing required MedlineCitation element")
    pmid = citation.findtext("PMID") or ""

    pub_types = {
        (node.text or "").strip()
        for node in citation.findall(".//PublicationTypeList/PublicationType")
    }
    retracted = "Retracted Publication" in pub_types

    concern = False
    notice = ""
    notice_pmid = ""
    for entry in citation.findall(".//CommentsCorrectionsList/CommentsCorrections"):
        ref_type = entry.get("RefType") or ""
        if ref_type == "RetractionIn":
            retracted = True
            notice = (entry.findtext("RefSource") or "").strip()
            notice_pmid = (entry.findtext("PMID") or "").strip()
        elif ref_type == "ExpressionOfConcernIn":
            concern = True

    return RetractionStatus(
        pmid=pmid,
        retracted=retracted,
        concern=concern,
        notice=notice,
        notice_pmid=notice_pmid,
    )
