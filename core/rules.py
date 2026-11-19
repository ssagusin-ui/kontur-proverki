"""Explainable rule evaluation. All conclusions are *review signals*, not violations."""
from __future__ import annotations
from datetime import date

from core.domain import Evidence, Signal, evidence, new_signal, validate_case, member_active_in_year, member_at_contract_date

RULEBOOK = [
    ("R01_PROPERTY", "Объект недвижимости не сопоставлен с декларацией", "Внешняя запись о владении за отчётный период отсутствует в перечне заявленных объектов."),
    ("R02_INCOME", "Расхождение годовых сумм дохода", "Сравниваются суммы одного человека за один год; расхождение свыше 5% и не менее 10 000 ₽."),
    ("R03_BUSINESS", "Участие в организации требует сверки", "Участие лица в юридическом лице найдено в демонстрационном источнике, но отсутствует в заявленных сведениях."),
    ("R04_CONTRACT", "Цепочка связанных лиц и государственного контракта", "Родство → участие в организации → подтверждённая связь юридического лица с контрактом."),
    ("R05_FOREIGN", "Недвижимость за пределами РФ требует сверки", "Запись о зарубежном объекте за отчётный период не найдена в заявленных сведениях."),
    ("R06_ENFORCEMENT", "Исполнительное производство требует проверки", "Запись о действующем исполнительном производстве сопоставляется с задекларированными обязательствами; не означает недостоверность."),
]


def evaluate(case: dict) -> list[Signal]:
    case = validate_case(case)
    cid, dec, regs, year = case["id"], case["declaration"], case["registries"], case["year"]
    people = {p["id"]: p for p in [dec["declarant"], *dec.get("family", [])]}
    asset_ids = {(x.get("registry_id"), x.get("person_id")) for x in dec.get("assets", [])}
    org_declared = {(x.get("person_id"), x.get("org_id")) for x in dec.get("organizations", [])}
    obligations = {(x.get("enforcement_id"), x.get("person_id")) for x in dec.get("obligations", [])}
    signals: list[Signal] = []

    # Records must be dated, refer to an identified member and overlap the relevant year.
    for record in regs.get("property", []):
        pid = record.get("owner_id")
        if pid not in people or (record["id"], pid) in asset_ids:
            continue
        first = record.get("from_year")
        last = int(record.get("to_year", 2100))
        if first is None or not first <= year <= min(last, int(record["source"]["as_of"][:4])):
            continue
        person = people[pid]["name"]
        foreign = record.get("country", "RU").upper() != "RU"
        rule = "R05_FOREIGN" if foreign else "R01_PROPERTY"
        country = record.get("country", "RU")
        sig_evidence = [evidence(record, f"Собственник: {person}; объект: {record.get('name')}; страна: {country}; владение в {year} г.", "registries.property")]
        signals.append(new_signal(cid, rule, record["id"],
            "Зарубежная недвижимость требует проверки" if foreign else "Недвижимость не сопоставлена с декларацией",
            "medium", f"Объект «{record.get('name', 'Недвижимость')}» зарегистрирован за {person}, но его идентификатора нет в представленной декларации.",
            "Сопоставлены идентификатор владельца, идентификатор объекта и год владения. Не исключены ограничения доступности источника и особые требования раскрытия.",
            "Проверить период собственности, корректность идентификаторов и обязательность отражения в соответствующем разделе декларации.",
            [pid, record["id"]], sig_evidence, [pid, record["id"]]))

    # No name-based matching: a uniquely defined person_id and same year are required.
    declared_incomes = {(x.get("person_id"), x.get("year")): x for x in dec.get("income", [])}
    for record in regs.get("income", []):
        pid, rec_year = record.get("person_id"), record.get("year")
        declaration = declared_incomes.get((pid, rec_year))
        if pid not in people or not declaration:
            continue
        if rec_year != year:
            continue
        actual, claimed = float(record["amount"]), float(declaration["amount"])
        diff = abs(actual - claimed)
        if diff < 10000 or diff <= 0.05 * max(actual, claimed):
            continue
        pretty = lambda x: f"{x:,.0f}".replace(",", " ") + " ₽"
        signals.append(new_signal(cid, "R02_INCOME", record["id"], "Суммы дохода не совпадают", "medium",
            f"{people[pid]['name']}: за {rec_year} г. заявлено {pretty(claimed)}, во внешнем источнике — {pretty(actual)} (разница {pretty(diff)}).",
            "Сравнены записи одного человека за один год. Источники могут учитывать разные виды доходов.",
            "Уточнить полноту внешнего источника, состав доходов, исправления и дату актуальности записи.",
            [pid], [Evidence("Представленная декларация", declaration.get("id", "DECL-INCOME"), str(year) + "-12-31", f"Указано: {pretty(claimed)}", "declaration.income"),
                    evidence(record, f"Из источника: {pretty(actual)}", "registries.income")], [pid]))

    # Involvement: organization must explicitly identify the family member or declarant.
    for org in regs.get("organizations", []):
        matched = set()
        for member in org.get("members", []):
            pid = member.get("person_id")
            if not member_active_in_year(member, year):
                continue  # membership outside reporting period or missing dating information
            if pid not in people or pid in matched or (pid, org["id"]) in org_declared:
                continue
            matched.add(pid)
            signals.append(new_signal(cid, "R03_BUSINESS", f"{pid}-{org['id']}", "Не отражена связь с организацией", "medium",
                f"{people[pid]['name']} указан(а) в {org['name']} как {member.get('role','участник')}; в предоставленных сведениях участие не найдено.",
                "Сопоставлены идентификаторы лица и организации. Правовой объём обязанностей по раскрытию требует отдельной оценки.",
                "Уточнить роль, долю, период участия и наличие обязательства отражать такие сведения.",
                [pid, org["id"]], [evidence(org, f"{people[pid]['name']}: {member.get('role','участник')}", "registries.organizations")],
                [pid, org["id"]]))

    # Family relation is grounded in declaration, organization membership and contractor identity.
    spouse_ids = {p["id"] for p in dec.get("family", []) if p.get("relation") in ("spouse", "супруг", "супруга")}
    org_by_id = {o["id"]: o for o in regs.get("organizations", [])}
    for contract in regs.get("contracts", []):
        if contract.get("government") is not True:
            continue
        signed_on = contract.get("signed_on")
        if not signed_on or date.fromisoformat(signed_on).year != year:
            continue
        org = org_by_id.get(contract.get("contractor_org_id"))
        if not org:
            continue
        if org["source"]["as_of"] < signed_on:
            continue
        matched = set()
        for participant in org.get("members", []):
            pid = participant.get("person_id")
            if not member_at_contract_date(participant, date.fromisoformat(signed_on)):
                continue
            if pid not in spouse_ids or pid in matched:
                continue
            relative = people[pid]
            has_period = any(key in relative for key in ("from_year", "from_date", "to_year", "to_date"))
            if has_period and not member_at_contract_date(
                {"from_year": 2000, **relative} if not {"from_year", "from_date"} & relative.keys() else relative,
                date.fromisoformat(signed_on),
            ):
                continue
            matched.add(pid)
            d = dec["declarant"]
            procurement_match = (
                d.get("procurement_decision_role") is True
                and bool(d.get("agency_id"))
                and d["agency_id"] == contract.get("customer_agency_id")
            )
            priority = "high" if procurement_match else "medium"
            chain = [d["id"], pid, org["id"], contract["id"]]
            signals.append(new_signal(cid, "R04_CONTRACT", f"{pid}-{org['id']}-{contract['id']}",
                "Обнаружена цепочка к государственному контракту", priority,
                f"{people[pid]['name']} ({participant.get('role','участник')}) связан(а) с {org['name']}, исполнителем контракта {contract['id']} ({contract.get('subject','без предмета')}).",
                "Связь подтверждается идентификаторами участника, компании и контракта и датированными сведениями о периоде участия. " +
                ("Период семейной связи в декларации отсутствует и требует уточнения на дату подписания. " if not has_period else "") + (
                    "Дополнительно в демоданных обозначено участие декларанта в решениях этого заказчика — необходима приоритетная проверка." if procurement_match else
                    "Связь сама по себе не означает конфликта интересов; участие декларанта в принятии решений не подтверждено."),
                "Установить фактическое участие декларанта в закупке, полномочия, даты возникновения интереса и наличие мер урегулирования.",
                chain, [Evidence("Представленная декларация", pid, f"{year}-12-31", f"Семейная связь: {d['name']} — {people[pid]['name']}", "declaration.family"),
                        evidence(org, f"Участие {people[pid]['name']}: {participant.get('role','участник')}", "registries.organizations"),
                        evidence(contract, f"Исполнитель: {org['name']}; предмет: {contract.get('subject','—')}", "registries.contracts")], chain))

    # Enforcement documents never automatically prove a disclosure offence.
    for proceeding in regs.get("enforcement", []):
        if proceeding.get("person_id") not in people or proceeding.get("status") != "active":
            continue
        if (proceeding["id"], proceeding.get("person_id")) in obligations:
            continue
        pid = proceeding["person_id"]
        signals.append(new_signal(cid, "R06_ENFORCEMENT", proceeding["id"], "Не сопоставлено исполнительное производство", "low",
            f"В демонстрационном реестре есть действующее производство {proceeding['id']} в отношении {people[pid]['name']}.",
            "Исполнительное производство и декларируемое финансовое обязательство не тождественны.",
            "Проверить вид взыскания, отчётный период, документальное подтверждение и необходимость отражения.",
            [pid, proceeding["id"]], [evidence(proceeding, f"Размер требования: {proceeding['amount']:,.0f} ₽", "registries.enforcement")],
            [pid, proceeding["id"]]))

    return sorted(signals, key=lambda s: ({"high": 0, "medium": 1, "low": 2}[s.severity], s.rule, s.id))


def coverage(case: dict) -> list[dict]:
    case = validate_case(case, strict_required=False)
    regs = case["registries"]
    names = {"property": "Недвижимость", "income": "Доходы", "organizations": "Юрлица", "contracts": "Контракты", "enforcement": "Исполнительные производства"}
    return [{"Источник": names[key], "Записей": len(regs.get(key, [])), "Статус": "Данные есть" if regs.get(key) else "Нет записей"} for key in names]
