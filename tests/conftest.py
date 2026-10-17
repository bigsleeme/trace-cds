import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tracecds.sources import label_to_passages  # noqa: E402

# Synthetic label shaped like an openFDA record. Text is invented for testing only.
FAKE_LABEL = {
    "set_id": "00000000-test-0000-0000-000000000000",
    "effective_time": "20250115",
    "openfda": {"generic_name": ["EXAMPLEDRUG"], "brand_name": ["Examplex"]},
    "indications_and_usage": ["1 INDICATIONS AND USAGE Exampledrug is indicated as an adjunct to diet "
                              "and exercise to improve glycemic control in adults with type 2 diabetes."],
    "dosage_and_administration": ["2 DOSAGE AND ADMINISTRATION The recommended starting dose of exampledrug "
                                  "is 500 mg orally twice a day with meals. Increase the dose in increments "
                                  "of 500 mg weekly. The maximum recommended dose is 2550 mg per day."],
    "dosage_and_administration_table": ["<table><caption>Table 1. Dosing by kidney function</caption>"
                                        "<tr><th>eGFR (mL/min)</th><th>Recommendation</th></tr>"
                                        "<tr><td>45 or more</td><td>No adjustment</td></tr>"
                                        "<tr><td>30 to 44</td><td>Do not initiate</td></tr></table>"],
    "contraindications": ["4 CONTRAINDICATIONS Exampledrug is contraindicated in patients with severe "
                          "renal impairment (eGFR below 30 mL/min). It is also contraindicated in patients "
                          "with hypersensitivity to exampledrug."],
    "warnings_and_cautions": ["5 WARNINGS AND PRECAUTIONS Lactic acidosis has been reported with exampledrug. "
                              "Discontinue exampledrug if lactic acidosis is suspected."],
}


@pytest.fixture
def passages():
    return label_to_passages(FAKE_LABEL, drug="exampledrug")
