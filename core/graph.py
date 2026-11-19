"""Build a provenance-aware graph, rather than drawing a predetermined four-node chain."""
from __future__ import annotations
from datetime import date
import networkx as nx

from core.domain import validate_case, member_active_in_year, member_at_contract_date

NODE_LABELS = {
    "declarant": "Декларант", "family": "Член семьи", "organization": "Организация",
    "contract": "Госконтракт", "property": "Недвижимость", "enforcement": "Производство",
    "agency": "Заказчик",
    "private_contract": "Частный контракт",
}


def _period(record):
    first = record.get("from_date", record.get("from_year"))
    last = record.get("to_date", record.get("to_year"))
    if first is None and last is None:
        return "Период не указан"
    return f"{first or 'начало не указано'} — {last or 'окончание не указано'}"


def relation_status(record: dict, moment: date) -> str:
    first = record.get("from_date", str(record["from_year"]) + "-01-01" if "from_year" in record else None)
    last = record.get("to_date", str(record["to_year"]) + "-12-31" if "to_year" in record else None)
    if last and last < moment.isoformat():
        return "historical"
    if first and first > moment.isoformat():
        return "future"
    if not first or ("from_date" not in record and record.get("from_year") == moment.year) or ("to_date" not in record and record.get("to_year") == moment.year):
        return "unknown"
    return "active"


def build_graph(case: dict, as_of: date | str | None = None, include_historical: bool = False) -> nx.DiGraph:
    case = validate_case(case, strict_required=False)
    dec, regs = case["declaration"], case["registries"]
    graph = nx.DiGraph()
    moment = date.fromisoformat(as_of) if isinstance(as_of, str) else as_of
    moment = moment or date(case["year"], 12, 31)
    graph.graph["as_of"] = moment.isoformat()

    def connect(left, right, record, *, status=None, **metadata):
        status = status or relation_status(record, moment)
        metadata.update(temporal_status=status, period=_period(record), relation_type=metadata["label"])
        if status in ("historical", "future") and not include_historical:
            return
        suffix = {"historical": "завершена", "future": "ещё не возникла", "unknown": "период требует уточнения"}
        if status in suffix:
            metadata["label"] += " · " + suffix[status]
        previous = graph.get_edge_data(left, right)
        rank = {"active": 2, "unknown": 1, "historical": 0, "future": 0}
        if previous and rank[previous["temporal_status"]] > rank[status]:
            return
        graph.add_edge(left, right, **metadata)
    main = dec["declarant"]
    graph.add_node(main["id"], label=main["name"], kind="declarant", source="Декларация", record_id=main["id"])
    people = {main["id"]: main}
    for member in dec.get("family", []):
        people[member["id"]] = member
        graph.add_node(member["id"], label=member["name"], kind="family", source="Декларация", record_id=member["id"])
        connect(main["id"], member["id"], member, label="Семейная связь", source="Декларация", record_id=member["id"], as_of=str(case["year"]) + "-12-31")

    for obj in regs.get("property", []):
        pid = obj.get("owner_id")
        if pid not in people:
            continue
        meta = obj["source"]
        status = relation_status(obj, moment)
        if not include_historical and (status in ("historical", "future") or int(meta["as_of"][:4]) < moment.year):
            continue
        graph.add_node(obj["id"], label=obj.get("name", obj["id"]), kind="property", source=meta["name"], record_id=meta["record_id"])
        connect(pid, obj["id"], obj, status="unknown" if meta["as_of"] < moment.isoformat() and status == "active" else status,
                label="Владение", source=meta["name"], record_id=meta["record_id"], as_of=meta["as_of"])

    for org in regs.get("organizations", []):
        members = [m for m in org.get("members", []) if m.get("person_id") in people
                   and (include_historical or member_active_in_year(m, moment.year) or not {"from_date", "from_year"} & m.keys())]
        if not members:
            continue
        meta = org["source"]
        graph.add_node(org["id"], label=org.get("name", org["id"]), kind="organization", source=meta["name"], record_id=meta["record_id"])
        for member in members:
            if as_of is not None and meta["as_of"] < moment.isoformat():
                continue
            if as_of is not None and not member_at_contract_date(member, moment) and not include_historical:
                continue
            connect(member["person_id"], org["id"], member, label=str(member.get("role", "Участие")), source=meta["name"], record_id=meta["record_id"], as_of=meta["as_of"])

    for contract in regs.get("contracts", []):
        signed_on = contract.get("signed_on")
        if signed_on and signed_on[:4] != str(case["year"]):
            continue
        org_id = contract.get("contractor_org_id")
        if org_id not in graph or graph.nodes[org_id]["kind"] != "organization":
            continue
        meta = contract["source"]
        if signed_on and signed_on > moment.isoformat() and not include_historical:
            continue
        kind = "contract" if contract["government"] else "private_contract"
        graph.add_node(contract["id"], label=f"{contract['id']} · {contract.get('subject', 'Контракт')}", kind=kind, source=meta["name"], record_id=meta["record_id"])
        period = {"from_date": signed_on} if signed_on else {}
        connect(org_id, contract["id"], period, label="Исполнитель", source=meta["name"], record_id=meta["record_id"], as_of=meta["as_of"])
        agency_id = contract.get("customer_agency_id")
        if agency_id:
            graph.add_node(agency_id, label=contract.get("customer_name", "Заказчик контракта"), kind="agency", source=meta["name"], record_id=meta["record_id"])
            connect(agency_id, contract["id"], period, label="Заказчик", source=meta["name"], record_id=meta["record_id"], as_of=meta["as_of"])

    for item in regs.get("enforcement", []):
        pid = item.get("person_id")
        if pid not in people:
            continue
        meta = item["source"]
        graph.add_node(item["id"], label=f"Производство {item['id']}", kind="enforcement", source=meta["name"], record_id=meta["record_id"])
        connect(pid, item["id"], {}, label="Производство", source=meta["name"], record_id=meta["record_id"], as_of=meta["as_of"])
    return graph
