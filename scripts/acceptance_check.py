"""Repeatable offline acceptance of the analytical core, journal and exports.

Run from project root: python scripts/acceptance_check.py
No actual registry data or user database is touched.
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.domain import strict_json_loads, validate_case
from core.graph import build_graph
from core.report import create_html_report
from core.rules import evaluate
from core.storage import Store


def main() -> int:
    expected = {'case_1': 0, 'case_2': 1, 'case_3': 2, 'case_4': 6}
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / 'acceptance.sqlite')
        for cid, count in expected.items():
            case = validate_case(strict_json_loads((ROOT / 'demo' / f'{cid}.json').read_text(encoding='utf-8')))
            signals = evaluate(case)
            assert len(signals) == count, f'{cid}: expected {count}, got {len(signals)}'
            graph = build_graph(case)
            run_id = store.create_run(case)
            run = store.get_run(run_id)
            assert len(run['signals']) == count
            assert store.audit_integrity(run_id)[0], f'{cid}: bad event chain'
            if signals:
                sid = run['signals'][0]['id']
                store.update_review(run_id, sid, 'need_docs', 'Запрошены подтверждающие записи', 'Проверяющий')
                assert Store(store.path).get_run(run_id)['reviews'][sid]['status'] == 'need_docs'
            integrity = store.audit_integrity(run_id)
            assert integrity[0], f'{cid}: {integrity[1]}'
            html = create_html_report(store.get_run(run_id), store.events(run_id), integrity)
            assert b'<html ' in html and b'</html>' in html
            json.dumps(store.get_run(run_id), ensure_ascii=False)
            print(f'PASS {cid}: signals={count}, nodes={len(graph.nodes)}, HTML={len(html)} bytes, storage=OK')
        assert store.summary()['runs'] == len(expected)
    print('PASS: all four scenarios, review persistence, audit chain and exports')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
