import copy
import json
import unittest
from pathlib import Path

from core.domain import CaseValidationError, validate_case
from core.rules import evaluate, coverage
from core.graph import build_graph

FIXTURES = Path(__file__).resolve().parents[1] / 'demo'

def load(n):
    return json.loads((FIXTURES/f'case_{n}.json').read_text(encoding='utf-8'))

class TestDemoRegression(unittest.TestCase):
    def test_all_case_outcomes(self):
        for n in range(1,5):
            with self.subTest(n=n):
                c = load(n)
                self.assertEqual(set(s.rule for s in evaluate(c)), set(c['expected_rules']))

    def test_clean_has_no_signals(self):
        self.assertEqual(evaluate(load(1)), [])

    def test_property_detects_spouse_ownership(self):
        signals = evaluate(load(2))
        self.assertEqual(len(signals), 1)
        self.assertIn('P202', signals[0].entities)
        self.assertEqual(signals[0].evidence[0].record_id,'PROP/RE202')

    def test_contract_produces_two_explainable_signals(self):
        signals = evaluate(load(3))
        self.assertEqual(set(s.rule for s in signals),{'R03_BUSINESS','R04_CONTRACT'})
        s = next(s for s in signals if s.rule=='R04_CONTRACT')
        self.assertEqual(s.severity,'medium')
        self.assertEqual(s.path, ('P301','P302','ORG301','ГК-2025-114'))
        self.assertEqual(len(s.evidence),3)

    def test_complex_has_high_priority_with_direct_procurement_role(self):
        signals = evaluate(load(4))
        chain = next(s for s in signals if s.rule=='R04_CONTRACT')
        self.assertEqual(chain.severity,'high')
        self.assertEqual(len(signals),6)

class TestNegativeControls(unittest.TestCase):
    def test_not_government_contract_no_signal(self):
        c=load(3);c['registries']['contracts'][0]['government']=False
        self.assertNotIn('R04_CONTRACT',{s.rule for s in evaluate(c)})

    def test_another_contractor_no_signal(self):
        c=load(3);c['registries']['contracts'][0]['contractor_org_id']='ORG-OTHER'
        self.assertNotIn('R04_CONTRACT',{s.rule for s in evaluate(c)})

    def test_unrelated_company_member_no_signal(self):
        c=load(3);c['registries']['organizations'][0]['members'][0]['person_id']='P999'
        self.assertNotIn('R04_CONTRACT',{s.rule for s in evaluate(c)})

    def test_declarant_procurement_role_not_enough_when_customer_differs(self):
        c=load(3);c['declaration']['declarant']['procurement_decision_role']=True
        self.assertEqual(next(s for s in evaluate(c) if s.rule=='R04_CONTRACT').severity,'medium')

    def test_spouse_org_declared_does_not_raise_business_missing(self):
        c=load(3);c['declaration']['organizations']=[{'person_id':'P302','org_id':'ORG301','role':'участник'}]
        self.assertNotIn('R03_BUSINESS',{s.rule for s in evaluate(c)})
        self.assertIn('R04_CONTRACT',{s.rule for s in evaluate(c)})

    def test_member_joined_after_contract_no_chain(self):
        c=load(3);c['registries']['organizations'][0]['members'][0]['from_year']=2026
        self.assertNotIn('R04_CONTRACT',{s.rule for s in evaluate(c)})

    def test_contract_outside_reporting_year_no_chain(self):
        c=load(3);c['registries']['contracts'][0]['signed_on']='2026-01-15'
        self.assertNotIn('R04_CONTRACT',{s.rule for s in evaluate(c)})

    def test_property_declared_no_signal(self):
        c=load(2);c['declaration']['assets'].append({'registry_id':'RE202','person_id':'P202','name':'Дом в Тихих Горах'})
        self.assertEqual(evaluate(c), [])

    def test_property_acquired_after_period_no_signal(self):
        c=load(2);c['registries']['property'][1]['from_year']=2026
        self.assertEqual(evaluate(c),[])

    def test_income_other_year_no_signal(self):
        c=load(4);c['registries']['income'][0]['year']=2024
        self.assertNotIn('R02_INCOME',{s.rule for s in evaluate(c)})

    def test_income_small_difference_below_threshold_no_signal(self):
        c=load(4);c['registries']['income'][0]['amount']=1560000
        self.assertNotIn('R02_INCOME',{s.rule for s in evaluate(c)})

    def test_closed_enforcement_no_signal(self):
        c=load(4);c['registries']['enforcement'][0]['status']='closed'
        self.assertNotIn('R06_ENFORCEMENT',{s.rule for s in evaluate(c)})

    def test_disclosed_enforcement_no_signal(self):
        c=load(4);c['declaration']['obligations']=[{'person_id':'P401','enforcement_id':'EN401'}]
        self.assertNotIn('R06_ENFORCEMENT',{s.rule for s in evaluate(c)})

    def test_foreign_asset_declared_no_signal(self):
        c=load(4);c['declaration']['assets'].append({'person_id':'P402','registry_id':'RE403','name':'Зарубежная квартира'})
        self.assertNotIn('R05_FOREIGN',{s.rule for s in evaluate(c)})

    def test_missing_registry_not_proof(self):
        c=load(1)
        c['registries']['property']=[]
        self.assertEqual(evaluate(c),[])
        self.assertTrue(any(x['Статус']=='Нет записей' for x in coverage(c)))

    def test_rule_is_stateless(self):
        c=load(3)
        self.assertEqual([s.to_dict() for s in evaluate(c)], [s.to_dict() for s in evaluate(c)])

class TestValidation(unittest.TestCase):
    def test_invalid_json_top_level(self):
        with self.assertRaises(CaseValidationError): validate_case([])

    def test_duplicate_person_ids(self):
        c=load(2);c['declaration']['family'][0]['id']='P201'
        with self.assertRaises(CaseValidationError): validate_case(c)

    def test_duplicate_registry_ids(self):
        c=load(2);c['registries']['property'].append(copy.deepcopy(c['registries']['property'][0]))
        with self.assertRaises(CaseValidationError): validate_case(c)

    def test_missing_provenance(self):
        c=load(2);del c['registries']['property'][0]['source']
        with self.assertRaises(CaseValidationError):validate_case(c)

    def test_negative_financial_amount(self):
        c=load(2);c['declaration']['income'][0]['amount']=-1
        with self.assertRaises(CaseValidationError):validate_case(c)

    def test_id_collision_between_person_and_registry(self):
        c=load(2);c['registries']['property'][0]['id']='P201'
        with self.assertRaises(CaseValidationError):validate_case(c)

    def test_same_name_different_person_id_does_not_create_spouse_chain(self):
        c=load(3)
        c['registries']['organizations'][0]['members'][0]['person_id']='ANOTHER_PERSON'
        self.assertNotIn('R04_CONTRACT',{s.rule for s in evaluate(c)})

    def test_invalid_source_date(self):
        c=load(2);c['registries']['property'][0]['source']['as_of']='yesterday'
        with self.assertRaises(CaseValidationError): validate_case(c)

class TestGraph(unittest.TestCase):
    def test_complete_chain(self):
        g=build_graph(load(3))
        for a,b in zip(['P301','P302','ORG301'],['P302','ORG301','ГК-2025-114']):
            self.assertTrue(g.has_edge(a,b),f'{a}->{b}')

    def test_not_invent_unknown_participants(self):
        c=load(3);c['registries']['organizations'][0]['members'][0]['person_id']='UNKNOWN'
        g=build_graph(c)
        self.assertNotIn('ORG301',g)

    def test_properties_have_provenance(self):
        g=build_graph(load(2))
        self.assertEqual(g.nodes['RE202']['record_id'],'PROP/RE202')

if __name__=='__main__':unittest.main()
