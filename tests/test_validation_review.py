import json
from pathlib import Path
import tempfile
import unittest

from core.domain import CaseValidationError, strict_json_loads, validate_case
from core.storage import Store


def sample(number=1):
    return json.loads((Path(__file__).parents[1] / "demo" / f"case_{number}.json").read_text(encoding="utf-8"))


class ValidationReviewTests(unittest.TestCase):
    def test_missing_income_person_has_record_location(self):
        case = sample()
        del case["declaration"]["income"][0]["person_id"]
        with self.assertRaisesRegex(CaseValidationError, r"declaration.income, запись № 1.*person_id"):
            validate_case(case)
        self.assertEqual(validate_case(case, strict_required=False)["id"], case["id"])

    def test_invalid_person_types_are_rejected_with_location(self):
        for value in (None, [], {}, 17, "", " "):
            with self.subTest(value=value):
                case = sample()
                case["declaration"]["income"][0]["person_id"] = value
                with self.assertRaisesRegex(CaseValidationError, r"declaration.income, запись № 1.*person_id"):
                    validate_case(case)

    def test_invalid_income_amount_has_location(self):
        case = sample()
        case["declaration"]["income"][0]["amount"] = "100"
        with self.assertRaisesRegex(CaseValidationError, r"declaration.income, запись № 1.*amount"):
            validate_case(case)

    def test_required_registry_reference_has_location(self):
        case = sample()
        del case["registries"]["property"][0]["owner_id"]
        with self.assertRaisesRegex(CaseValidationError, r"registries.property, запись № 1.*owner_id"):
            validate_case(case)

    def test_valid_file_can_follow_invalid_json(self):
        with self.assertRaises(CaseValidationError):
            strict_json_loads("{")
        case = sample()
        self.assertEqual(validate_case(strict_json_loads(json.dumps(case))), validate_case(case))

    def test_reviewer_only_change_persists_and_exact_repeat_is_noop(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "checks.db"
            store = Store(path)
            rid = store.create_run(sample(3))
            signal_id = store.get_run(rid)["signals"][0]["id"]
            store.update_review(rid, signal_id, "need_docs", "Уточнить документы", "Эксперт 1")
            store.update_review(rid, signal_id, "need_docs", "Уточнить документы", "Эксперт 2")
            store.update_review(rid, signal_id, "need_docs", "Уточнить документы", "Эксперт 2")
            reopened = Store(path)
            review = reopened.get_run(rid)["reviews"][signal_id]
            self.assertEqual(review["reviewer"], "Эксперт 2")
            self.assertEqual(review["status"], "need_docs")
            self.assertEqual(review["note"], "Уточнить документы")
            events = reopened.events(rid)
            self.assertEqual(len(events), 3)
            payload = json.loads(events[-1]["payload_json"])
            self.assertEqual(payload["before"]["reviewer"], "Эксперт 1")
            self.assertEqual(payload["after"]["reviewer"], "Эксперт 2")
            self.assertTrue(reopened.audit_integrity(rid)[0])
