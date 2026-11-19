import json
from pathlib import Path
import unittest
import networkx as nx
from core.graph import build_graph
from core.rules import evaluate


def sample():
    return json.loads((Path(__file__).parents[1] / "demo/case_3.json").read_text(encoding="utf-8"))


class TemporalGraphTests(unittest.TestCase):
    def setUp(self):
        self.case = sample()
        self.person = self.case["declaration"]["declarant"]["id"]
        self.relative = self.case["declaration"]["family"][0]
        self.contract = self.case["registries"]["contracts"][0]

    def test_unknown_family_period_is_explicit_and_nominal_chain_survives(self):
        graph = build_graph(self.case, self.contract["signed_on"])
        self.assertTrue(nx.has_path(graph, self.person, self.contract["id"]))
        self.assertEqual(graph[self.person][self.relative["id"]]["temporal_status"], "unknown")
        self.assertIn("R04_CONTRACT", {s.rule for s in evaluate(self.case)})

    def test_expired_family_removes_current_chain(self):
        self.relative["to_date"] = "2024-01-01"
        graph = build_graph(self.case, self.contract["signed_on"])
        self.assertFalse(nx.has_path(graph, self.person, self.contract["id"]))
        self.assertNotIn("R04_CONTRACT", {s.rule for s in evaluate(self.case)})
        historical = build_graph(self.case, self.contract["signed_on"], include_historical=True)
        self.assertIn("завершена", historical[self.person][self.relative["id"]]["label"])

    def test_membership_ending_before_contract_removes_path(self):
        member = self.case["registries"]["organizations"][0]["members"][0]
        member["to_date"] = "2025-01-01"
        graph = build_graph(self.case, self.contract["signed_on"])
        self.assertFalse(nx.has_path(graph, self.person, self.contract["id"]))
        self.assertNotIn("R04_CONTRACT", {s.rule for s in evaluate(self.case)})

    def test_private_contract_has_separate_kind(self):
        self.contract["government"] = False
        graph = build_graph(self.case, self.contract["signed_on"])
        self.assertEqual(graph.nodes[self.contract["id"]]["kind"], "private_contract")
        self.assertNotIn("R04_CONTRACT", {s.rule for s in evaluate(self.case)})

    def test_every_chain_edge_has_provenance(self):
        graph = build_graph(self.case, self.contract["signed_on"])
        route = nx.shortest_path(graph, self.person, self.contract["id"])
        for left, right in zip(route, route[1:]):
            edge = graph[left][right]
            for field in ("source", "record_id", "as_of", "period"):
                self.assertTrue(edge[field])
