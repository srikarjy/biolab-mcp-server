"""Thin wrapper over the ClinicalTrials.gov API v2. No logging, no DB access — see retrieval_log.py."""

import hashlib
import json
from dataclasses import dataclass
from urllib.parse import urlencode
from urllib.request import urlopen

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
TIMEOUT_SECONDS = 15


@dataclass
class ClinicalTrialStudy:
    nct_id: str
    brief_title: str
    official_title: str
    organization: str
    overall_status: str
    start_date: str
    completion_date: str
    study_type: str
    phase: str
    brief_summary: str
    conditions: list[str]
    full_json: str  # verbatim study record, exactly as ClinicalTrials.gov returned it


def search(query: str, max_results: int) -> list[dict]:
    """Condition/disease search: query string -> list of raw study dicts."""
    params = urlencode({
        "query.cond": query,
        "pageSize": max_results,
        "format": "json",
    })
    with urlopen(f"{BASE_URL}?{params}", timeout=TIMEOUT_SECONDS) as resp:
        data = json.load(resp)
    return data.get("studies", [])


def fetch_study(nct_id: str) -> str:
    """The full study record, verbatim, for one NCT ID."""
    params = urlencode({"format": "json"})
    with urlopen(f"{BASE_URL}/{nct_id}?{params}", timeout=TIMEOUT_SECONDS) as resp:
        return resp.read().decode("utf-8")


def search_and_fetch(query: str, max_results: int) -> list[ClinicalTrialStudy]:
    studies = search(query, max_results)
    results = []
    for s in studies:
        protocol = s.get("protocolSection", {})
        identification = protocol.get("identificationModule", {})
        status = protocol.get("statusModule", {})
        description = protocol.get("descriptionModule", {})
        conditions_module = protocol.get("conditionsModule", {})
        design = protocol.get("designModule", {})

        nct_id = identification.get("nctId", "")
        phases = design.get("phases") or []

        results.append(ClinicalTrialStudy(
            nct_id=nct_id,
            brief_title=identification.get("briefTitle", ""),
            official_title=identification.get("officialTitle", ""),
            organization=identification.get("organization", {}).get("fullName", ""),
            overall_status=status.get("overallStatus", ""),
            start_date=status.get("startDateStruct", {}).get("date", ""),
            completion_date=status.get("completionDateStruct", {}).get("date", ""),
            study_type=design.get("studyType", ""),
            phase=", ".join(phases),
            brief_summary=description.get("briefSummary", ""),
            conditions=conditions_module.get("conditions") or [],
            full_json=fetch_study(nct_id),
        ))
    return results


def paper_to_retrieval_input(study: ClinicalTrialStudy) -> dict:
    """Convert ClinicalTrialStudy to the input format expected by retrieval_log.write_retrieval."""
    snapshot = {
        "title": study.brief_title,
        "abstract": study.brief_summary,
        "authors": [{"lastname": study.organization}] if study.organization else [],
        "journal": {"title": "ClinicalTrials.gov", "pub_date": study.start_date},
        "publication_types": [t for t in (study.study_type, study.phase) if t],
        "doi": "",
    }

    # ClinicalTrials.gov has no PubMed-style pub_status field; a hash of the raw
    # response stands in, so the source_metadata shape stays consistent across sources.
    full_json_hash = hashlib.sha256(study.full_json.encode("utf-8")).hexdigest()
    source_metadata = {
        "medline_status": study.overall_status,
        "pub_status": full_json_hash[:32],
    }

    return {
        "source": "clinicaltrials",
        "external_id": study.nct_id,
        "source_metadata": source_metadata,
        "raw_response": study.full_json,
        "snapshot": snapshot,
    }
