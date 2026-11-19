import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from core.domain import validate_case
from core.report import create_html_report
from core.storage import Store, STATUS_LABELS

FIXTURES = Path(__file__).resolve().parents[1] / 'demo'

def load(n):
    return json.loads((FIXTURES/f'case_{n}.json').read_text(encoding='utf-8'))

class TestStorage(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/'case.sqlite'
        self.store=Store(self.db)
        self.run_id=self.store.create_run(load(3))

    def tearDown(self): self.tmp.cleanup()

    def test_snapshot_persists(self):
        run=self.store.get_run(self.run_id)
        self.assertEqual(run['case_id'],'case_3')
        self.assertEqual(len(run['signals']),2)
        self.assertTrue(self.store.audit_integrity(self.run_id)[0])

    def test_new_review_logged(self):
        signal=self.store.get_run(self.run_id)['signals'][0]['id']
        self.store.update_review(self.run_id, signal, 'need_docs', 'Запрошена выписка', 'Эксперт 1')
        run=self.store.get_run(self.run_id)
        self.assertEqual(run['reviews'][signal]['note'],'Запрошена выписка')
        self.assertEqual(len(self.store.events(self.run_id)),2)
        self.assertTrue(self.store.audit_integrity(self.run_id)[0])

    def test_no_op_review_not_logged(self):
        signal=self.store.get_run(self.run_id)['signals'][0]['id']
        self.store.update_review(self.run_id, signal, 'new', '', 'Система')
        self.assertEqual(len(self.store.events(self.run_id)),1)

    def test_invalid_status_rejected(self):
        sig=self.store.get_run(self.run_id)['signals'][0]['id']
        with self.assertRaises(ValueError): self.store.update_review(self.run_id, sig, 'guilty', '', 'Analyst')

    def test_unknown_signal_rejected(self):
        with self.assertRaises(KeyError): self.store.update_review(self.run_id, 'SIG-OTHER','new','','A')

    def test_tampering_with_event_detected(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE events SET payload_json=? WHERE run_id=?', ('{}', self.run_id))
        self.assertFalse(self.store.audit_integrity(self.run_id)[0])

    def test_tampering_with_snapshot_detected(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE runs SET payload_json=? WHERE id=?', ('{}', self.run_id))
        self.assertFalse(self.store.audit_integrity(self.run_id)[0])

    def test_separate_cases(self):
        rid2=self.store.create_run(load(1))
        self.assertEqual(len(self.store.list_runs()),2)
        self.assertEqual(len(self.store.get_run(rid2)['signals']),0)
        self.assertTrue(self.store.audit_integrity(rid2)[0])

    def test_report_has_audit_and_evidence(self):
        run=self.store.get_run(self.run_id)
        report=create_html_report(run, self.store.events(self.run_id), self.store.audit_integrity(self.run_id)).decode('utf-8')
        self.assertIn('ORG/ORG301',report)
        self.assertIn('SHA-256',report)
        self.assertIn('не выносит',report)

    def test_report_escapes_injected_html(self):
        c=load(2)
        c['title']='<script>alert(1)</script>'
        rid=self.store.create_run(c)
        run=self.store.get_run(rid)
        report=create_html_report(run, self.store.events(rid), self.store.audit_integrity(rid)).decode('utf-8')
        self.assertNotIn('<script>',report)
        self.assertIn('&lt;script&gt;',report)

if __name__=='__main__':unittest.main()
