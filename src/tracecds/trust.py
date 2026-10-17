"""Classify web sources by how authoritative they are for healthcare information.

approved    Government health and regulatory agencies, the National Library of
            Medicine, major peer-reviewed medical journals, and national medical
            professional societies.
reputable   Recognized academic medical centers and clinical references. Useful,
            but not regulatory or peer-reviewed sources.
unverified  Everything else (news sites, blogs, encyclopedias, forums, vendors).
            Answers may still use them, but the user is told plainly.

The lists are deliberately conservative and easy to edit.
"""

from __future__ import annotations

from urllib.parse import urlparse

APPROVED = {
    # U.S. government health and regulatory agencies
    "fda.gov", "cdc.gov", "nih.gov", "medlineplus.gov", "cms.gov", "hhs.gov", "ahrq.gov",
    "cancer.gov", "clinicaltrials.gov", "healthdata.gov", "va.gov", "health.mil",
    "uspreventiveservicestaskforce.org", "samhsa.gov",
    # International public-health and regulatory bodies
    "who.int", "ema.europa.eu", "nice.org.uk", "canada.ca",
    # Peer-reviewed journals and evidence syntheses
    "nejm.org", "jamanetwork.com", "thelancet.com", "bmj.com", "cochranelibrary.com",
    "annals.org", "ahajournals.org", "pediatrics.aappublications.org",
    # National medical professional societies
    "aafp.org", "aap.org", "healthychildren.org", "acog.org", "aad.org", "heart.org",
    "diabetes.org", "idsociety.org", "acponline.org", "asco.org", "psychiatry.org",
}

REPUTABLE = {
    "mayoclinic.org", "clevelandclinic.org", "hopkinsmedicine.org", "mskcc.org",
    "mdanderson.org", "stanfordhealthcare.org", "massgeneral.org", "uptodate.com",
    "merckmanuals.com", "nhs.uk", "kidshealth.org", "childrenshospital.org", "chop.edu",
}

LABELS = {
    "approved": "Approved healthcare source",
    "reputable": "Recognized medical institution (not a regulatory or peer-reviewed source)",
    "unverified": "Not an approved healthcare source",
}

RANK = {"approved": 0, "reputable": 1, "unverified": 2}


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _matches(host: str, domains: set[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def classify(url: str) -> str:
    """Return the trust tier for a URL."""
    host = domain_of(url)
    if _matches(host, APPROVED):
        return "approved"
    if _matches(host, REPUTABLE) or host.endswith(".edu"):
        return "reputable"
    return "unverified"
