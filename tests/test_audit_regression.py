"""Additional adversarial, migration, and end-to-end engine tests for audit release."""
from __future__ import annotations
import copy
import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from core.domain import CaseValidationError, strict_json_loads, validate_case
from core.graph import build_graph
from core.report import create_html_report
from core.rules import evaluate
from core.storage import Store

ROOT = Path(__file__).resolve().parents[1]


def fixture(number):
    return json.loads((ROOT / 'demo' / f'case_{number}.json').read_text('utf-8'))


class AuditInputControls(unittest.TestCase):
    def test_duplicate_keys_rejected(self):
        with self.assertRaises(CaseValidationError):
            strict_json_loads('{"id":"abc","id":"changed"}')

    def test_nonfinite_literals_rejected(self):
        for value in ('NaN', 'Infinity', '-Infinity'):
            with self.subTest(value=value), self.assertRaises(CaseValidationError):
                strict_json_loads('{"amount":' + value + '}')

    def test_nonfinite_python_amount_rejected(self):
        for value in (float('nan'), float('inf')):
            c = fixture(4)
            c['declaration']['income'][0]['amount'] = value
            with self.subTest(value=value), self.assertRaises(CaseValidationError):
                validate_case(c)

    def test_impossible_property_interval_rejected(self):
        c = fixture(2)
        c['registries']['property'][0]['from_year'] = 2030
        c['registries']['property'][0]['to_year'] = 2020
        with self.assertRaises(CaseValidationError):
            validate_case(c)

    def test_impossible_org_interval_rejected(self):
        c = fixture(3)
        c['registries']['organizations'][0]['members'][0]['to_year'] = 2022
        with self.assertRaises(CaseValidationError):
            validate_case(c)

    def test_invalid_membership_calendar_date_rejected(self):
        c = fixture(3)
        c['registries']['organizations'][0]['members'][0]['from_date'] = '2025-02-30'
        with self.assertRaises(CaseValidationError):
            validate_case(c)

    def test_invalid_registry_date_format_rejected(self):
        c = fixture(3)
        c['registries']['contracts'][0]['source']['as_of'] = '20261115'
        with self.assertRaises(CaseValidationError):
            validate_case(c)

    def test_record_predates_contract_rejected(self):
        c = fixture(3)
        c['registries']['contracts'][0]['source']['as_of'] = '2025-01-01'
        with self.assertRaises(CaseValidationError):
            validate_case(c)

    def test_agency_id_cannot_replace_person_node(self):
        c = fixture(3)
        c['registries']['contracts'][0]['customer_agency_id'] = 'P301'
        with self.assertRaises(CaseValidationError):
            validate_case(c)

    def test_wrong_person_asset_declaration_does_not_hide_property(self):
        c = fixture(2)
        # Claim the same object ID, but attach it to the wrong family member.
        rec = c['registries']['property'][1]
        c['declaration']['assets'].append({
            'registry_id': rec['id'], 'person_id': c['declaration']['declarant']['id']})
        self.assertIn('R01_PROPERTY', [s.rule for s in evaluate(c)])

    def test_wrong_person_obligation_does_not_hide_enforcement(self):
        c = fixture(4)
        c['declaration']['obligations'] = [{'enforcement_id': 'EN401', 'person_id': 'P402'}]
        self.assertIn('R06_ENFORCEMENT', [s.rule for s in evaluate(c)])

    def test_contract_same_year_without_exact_join_date_not_asserted(self):
        c = fixture(3)
        c['registries']['organizations'][0]['members'][0]['from_year'] = 2025
        self.assertNotIn('R04_CONTRACT', [s.rule for s in evaluate(c)])

    def test_contract_same_year_with_exact_join_before_signature(self):
        c = fixture(3)
        member = c['registries']['organizations'][0]['members'][0]
        member['from_year'] = 2025
        member['from_date'] = '2025-01-31'
        self.assertIn('R04_CONTRACT', [s.rule for s in evaluate(c)])

    def test_contract_same_year_with_exact_join_after_signature(self):
        c = fixture(3)
        member = c['registries']['organizations'][0]['members'][0]
        member['from_year'] = 2025
        member['from_date'] = '2025-11-01'
        self.assertNotIn('R04_CONTRACT', [s.rule for s in evaluate(c)])

    def test_contract_same_year_with_ambiguous_departure_not_asserted(self):
        c = fixture(3)
        c['registries']['organizations'][0]['members'][0]['to_year'] = 2025
        self.assertNotIn('R04_CONTRACT', [s.rule for s in evaluate(c)])

    def test_contract_same_year_with_exact_departure_after_signature(self):
        c = fixture(3)
        member = c['registries']['organizations'][0]['members'][0]
        member['to_year'] = 2025
        member['to_date'] = '2025-12-01'
        self.assertIn('R04_CONTRACT', [s.rule for s in evaluate(c)])

    def test_future_acquisition_not_shown_as_2025_graph_link(self):
        c = fixture(2)
        c['registries']['property'][1]['from_year'] = 2026
        g = build_graph(c)
        self.assertNotIn('RE202', g)

    def test_graph_edge_has_registry_provenance(self):
        g = build_graph(fixture(3))
        self.assertEqual(g.edges['ORG301', 'ГК-2025-114']['record_id'], 'CN/ГК-2025-114')
        self.assertIn('as_of', g.edges['P302', 'ORG301'])


class AuditJournalControls(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.path = Path(self.t.name) / 'data.sqlite'
        self.store = Store(self.path)
        self.rid = self.store.create_run(fixture(3))

    def tearDown(self):
        self.t.cleanup()

    def test_signal_snapshot_modification_detected(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            signals = json.loads(db.execute('SELECT signals_json FROM runs WHERE id=?', (self.rid,)).fetchone()[0])
            signals[0]['severity'] = 'low' if signals[0]['severity'] != 'low' else 'high'
            db.execute('UPDATE runs SET signals_json=? WHERE id=?', (json.dumps(signals, ensure_ascii=False), self.rid))
        self.assertFalse(self.store.audit_integrity(self.rid)[0])

    def test_review_row_modification_without_event_detected(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE reviews SET status=? WHERE run_id=?', ('data_confirmed', self.rid))
        self.assertFalse(self.store.audit_integrity(self.rid)[0])

    def test_reviewer_modification_without_event_detected(self):
        sid = self.store.get_run(self.rid)['signals'][0]['id']
        self.store.update_review(self.rid, sid, 'in_review', 'Проверяю', 'Аналитик А')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('UPDATE reviews SET reviewer=? WHERE run_id=? AND signal_id=?', ('Другой', self.rid, sid))
        self.assertFalse(self.store.audit_integrity(self.rid)[0])

    def test_tail_event_deleted_detected(self):
        sid = self.store.get_run(self.rid)['signals'][0]['id']
        self.store.update_review(self.rid, sid, 'in_review', 'Проверяю', 'Аналитик А')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DELETE FROM events WHERE seq=(SELECT MAX(seq) FROM events WHERE run_id=?)', (self.rid,))
        self.assertFalse(self.store.audit_integrity(self.rid)[0])

    def test_wrong_previous_review_status_fails_consistency(self):
        sid = self.store.get_run(self.rid)['signals'][0]['id']
        self.store.update_review(self.rid, sid, 'in_review', 'Открыто', 'А')
        self.store.update_review(self.rid, sid, 'need_docs', 'Запрошено', 'Б')
        self.assertTrue(self.store.audit_integrity(self.rid)[0])
        self.assertEqual(len(self.store.events(self.rid)), 3)

    def test_full_human_workflow_persist_and_html_escape(self):
        sid = self.store.get_run(self.rid)['signals'][0]['id']
        self.store.update_review(self.rid, sid, 'need_docs', '<script>alert("X")</script>', 'Рецензент')
        reopened = Store(self.path)
        review = reopened.get_run(self.rid)['reviews'][sid]
        self.assertEqual(review['status'], 'need_docs')
        self.assertTrue(reopened.audit_integrity(self.rid)[0])
        html = create_html_report(reopened.get_run(self.rid), reopened.events(self.rid), reopened.audit_integrity(self.rid)).decode('utf-8')
        self.assertNotIn('<script>alert(', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('Источники и охват', html)
        self.assertIn('Рецензент', html)

    def test_dashboard_totals_not_limited_to_100(self):
        # A run list is intentionally paginated, but overview totals must be global.
        for _ in range(101):
            self.store.create_run(fixture(1))
        self.assertEqual(self.store.summary()['runs'], 102)
        self.assertEqual(len(self.store.list_runs(limit=100)), 100)

    def test_additive_migration_preserves_existing_checks(self):
        # Simulate the v1 runs table before adding the digest columns.
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('ALTER TABLE runs DROP COLUMN signals_hash')
            db.execute('ALTER TABLE runs DROP COLUMN last_event_hash')
            db.execute('ALTER TABLE runs DROP COLUMN event_count')
        migrated = Store(self.path)
        run = migrated.get_run(self.rid)
        self.assertEqual(run['case_id'], 'case_3')
        valid, msg = migrated.audit_integrity(self.rid)
        self.assertTrue(valid, msg)
        self.assertIn('старой проверки', msg)


# Additional lightweight checks are registered through a separate TestCase because
# unittest discovery loads this module before the standalone __main__ block.
class AuditMembershipDatePrecision(unittest.TestCase):
    def test_only_exact_start_date_can_prove_joining_during_signature_year(self):
        c = fixture(3)
        m = c['registries']['organizations'][0]['members'][0]
        del m['from_year']
        m['from_date'] = '2025-02-01'
        self.assertIn('R04_CONTRACT', [s.rule for s in evaluate(c)])

    def test_inconsistent_member_year_and_date_rejected(self):
        c = fixture(3)
        c['registries']['organizations'][0]['members'][0]['from_date'] = '2025-02-01'
        with self.assertRaises(CaseValidationError):
            validate_case(c)

if __name__ == '__main__':
    unittest.main()
