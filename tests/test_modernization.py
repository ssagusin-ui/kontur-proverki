from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

from core.domain import CaseValidationError, validate_case
from core.rules import evaluate
from core.storage import Store


def dataset(number):
    return json.loads((Path(__file__).parents[1] / "demo" / f"case_{number}.json").read_text(encoding="utf-8"))


class ModernizationTests(unittest.TestCase):
    def test_malformed_reference_and_period_return_validation_error(self):
        case = dataset(3)
        case["registries"]["organizations"][0]["members"][0]["from_year"] = "2020"
        with self.assertRaises(CaseValidationError):
            validate_case(case)
        case = dataset(3)
        case["registries"]["contracts"][0]["contractor_org_id"] = []
        with self.assertRaises(CaseValidationError):
            validate_case(case)

    def test_unsigned_agency_id_cannot_escalate_priority(self):
        case = dataset(3)
        declarant = case["declaration"]["declarant"]
        declarant["procurement_decision_role"] = True
        declarant.pop("agency_id", None)
        case["registries"]["contracts"][0].pop("customer_agency_id", None)
        signal = next(s for s in evaluate(case) if s.rule == "R04_CONTRACT")
        self.assertEqual(signal.severity, "medium")

    def test_family_relation_ended_before_signing(self):
        case = dataset(3)
        case["declaration"]["family"][0]["to_date"] = "2024-01-01"
        self.assertNotIn("R04_CONTRACT", {s.rule for s in evaluate(case)})

    def test_repeated_income_records_remain_separate_and_persist(self):
        case = dataset(4)
        rows = case["registries"]["income"]
        repeated = deepcopy(rows[0])
        repeated["id"] += "-SECOND"
        repeated["source"]["record_id"] += "-SECOND"
        rows.append(repeated)
        matches = [s for s in evaluate(case) if s.rule == "R02_INCOME"]
        self.assertEqual(len(matches), 2)
        self.assertEqual(len({s.id for s in matches}), 2)
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "case.sqlite"
            rid = Store(db).create_run(case)
            self.assertTrue(Store(db).audit_integrity(rid)[0])
