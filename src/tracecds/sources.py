"""Fetch FDA drug labels (Structured Product Labeling) from openFDA.

openFDA drug labels are U.S. government data and may be redistributed.
Each passage keeps a link back to the label on DailyMed so a clinician can
check the original wording.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any, Iterable

from .chunking import chunk_text
from .schema import Passage
from .tables import html_table_to_markdown

OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"
DAILYMED_URL = "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}"

# Label sections indexed, with human-readable names.
SECTIONS: dict[str, str] = {
    "boxed_warning": "Boxed Warning",
    "indications_and_usage": "Indications and Usage",
    "dosage_and_administration": "Dosage and Administration",
    "dosage_forms_and_strengths": "Dosage Forms and Strengths",
    "contraindications": "Contraindications",
    "warnings_and_cautions": "Warnings and Precautions",
    "warnings": "Warnings",
    "precautions": "Precautions",
    "adverse_reactions": "Adverse Reactions",
    "drug_interactions": "Drug Interactions",
    "use_in_specific_populations": "Use in Specific Populations",
    "pregnancy": "Pregnancy",
    "pediatric_use": "Pediatric Use",
    "geriatric_use": "Geriatric Use",
    "overdosage": "Overdosage",
    "mechanism_of_action": "Mechanism of Action",
}


def fetch_label(generic_name: str, api_key: str | None = None, timeout: int = 30) -> dict[str, Any]:
    """Return the most recent openFDA label record for a generic drug name."""
    query = f'openfda.generic_name:"{generic_name}"'
    params = {"search": query, "limit": "1", "sort": "effective_time:desc"}
    if api_key:
        params["api_key"] = api_key
    url = f"{OPENFDA_LABEL_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "TraceCDS/0.1 (research)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    results = payload.get("results") or []
    if not results:
        raise LookupError(f"No openFDA label found for '{generic_name}'")
    return results[0]


def _format_date(raw: str) -> str:
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if re.fullmatch(r"\d{8}", raw or "") else raw or ""


def label_to_passages(label: dict[str, Any], drug: str | None = None) -> list[Passage]:
    """Split one label record into section-tagged passages, tables kept whole."""
    openfda = label.get("openfda", {})
    name = drug or (openfda.get("generic_name") or ["unknown"])[0].lower()
    brand = (openfda.get("brand_name") or [""])[0]
    set_id = label.get("set_id", "")
    url = DAILYMED_URL.format(set_id=set_id) if set_id else ""
    title = f"FDA label: {name}" + (f" ({brand})" if brand else "")
    date = _format_date(label.get("effective_time", ""))

    passages: list[Passage] = []
    for key, section in SECTIONS.items():
        for i, block in enumerate(label.get(key, []) or []):
            for j, chunk in enumerate(chunk_text(block)):
                passages.append(Passage(
                    passage_id=f"{name}:{key}:{i}:{j}", text=chunk, drug=name,
                    section=section, source_title=title, source_url=url,
                    effective_date=date))
        for i, html in enumerate(label.get(f"{key}_table", []) or []):
            md = html_table_to_markdown(html)
            if md:
                passages.append(Passage(
                    passage_id=f"{name}:{key}_table:{i}", text=md, drug=name,
                    section=f"{section} (table)", source_title=title,
                    source_url=url, effective_date=date, is_table=True))
    return passages


def build_corpus(drugs: Iterable[str], api_key: str | None = None) -> list[Passage]:
    """Fetch labels for several drugs and return all passages."""
    corpus: list[Passage] = []
    for drug in drugs:
        label = fetch_label(drug, api_key=api_key)
        corpus.extend(label_to_passages(label, drug=drug.lower()))
    return corpus


def save_corpus(passages: list[Passage], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for p in passages:
            f.write(json.dumps(p.to_dict(), ensure_ascii=False) + "\n")


def load_corpus(path: str) -> list[Passage]:
    with open(path, encoding="utf-8") as f:
        return [Passage.from_dict(json.loads(line)) for line in f if line.strip()]
