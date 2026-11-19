"""Generate synthetic datasets. No real person, registry or contractor was consulted."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent

def src(name, rid, as_of="2026-10-30"):
    return {"name": "ДЕМО · " + name, "record_id": rid, "as_of": as_of}

def ppty(id, owner, name, country="RU", from_year=2020):
    return dict(id=id, owner_id=owner, name=name, kind="real_estate", country=country, from_year=from_year,
                source=src("модель реестра недвижимости", "PROP/" + id))

def inc(id, pid, amount, year=2025):
    return dict(id=id, person_id=pid, amount=amount, year=year,
                source=src("модель сведений о доходах", "INC/"+id))

def org(id, name, members):
    return dict(id=id, name=name, members=members,
                source=src("модель реестра юридических лиц", "ORG/"+id))

def contract(id, org_id, agency, subject, amount, government=True):
    return dict(id=id, contractor_org_id=org_id, customer_agency_id=agency,
                customer_name="Демонстрационное ведомство", subject=subject, amount=amount,
                government=government, signed_on="2025-06-18", source=src("модель реестра контрактов", "CN/"+id))

def enforcement(id, pid, amount, status="active"):
    return dict(id=id, person_id=pid, amount=amount, status=status,
                source=src("модель исполнительных производств", "ENF/"+id))

cases=[]
cases.append({
 "id":"case_1", "year":2025,
 "title":"Чистая декларация", "description":"Сведения о доходах и недвижимости совпадают с модельными источниками. Проверяет отсутствие ложных сигналов.",
 "declaration":{"declarant":{"id":"P101","name":"Елена Савельева","position":"Специалист государственного учреждения","agency_id":"AG101"},
    "family":[{"id":"P102","name":"Игорь Савельев","relation":"spouse"}],
    "assets":[{"registry_id":"RE101","person_id":"P101","name":"Квартира на Липовой улице"}],
    "income":[{"id":"DI101","person_id":"P101","year":2025,"amount":1190000},
             {"id":"DI102","person_id":"P102","year":2025,"amount":850000}],
    "organizations":[],"obligations":[]},
 "registries":{"property":[ppty("RE101","P101","Квартира на Липовой улице")],
               "income":[inc("I101","P101",1190000),inc("I102","P102",850000)],
               "organizations":[], "contracts":[],"enforcement":[]},
 "expected_rules":[]})
cases.append({
 "id":"case_2", "year":2025,
 "title":"Неотражённая недвижимость супруга", "description":"В отдельной записи модели реестра найден объект супруга, который отсутствует в представленных сведениях.",
 "declaration":{"declarant":{"id":"P201","name":"Дмитрий Ветров","position":"Начальник технического отдела","agency_id":"AG201"},
    "family":[{"id":"P202","name":"Ольга Ветрова","relation":"spouse"}],
    "assets":[{"registry_id":"RE201","person_id":"P201","name":"Квартира на Вишнёвой улице"}],
    "income":[{"id":"DI201","person_id":"P201","year":2025,"amount":1680000},
             {"id":"DI202","person_id":"P202","year":2025,"amount":640000}],
    "organizations":[],"obligations":[]},
 "registries":{"property":[ppty("RE201","P201","Квартира на Вишнёвой улице"),
                            ppty("RE202","P202","Дом в посёлке Тихие Горы",from_year=2024)],
               "income":[inc("I201","P201",1680000),inc("I202","P202",640000)],
               "organizations":[],"contracts":[],"enforcement":[]},
 "expected_rules":["R01_PROPERTY"]})
cases.append({
 "id":"case_3", "year":2025,
 "title":"Семейная цепочка и госконтракт", "description":"Супруг участвует в юридическом лице — исполнителе контракта. Участие лица в решениях заказчика не заявлено.",
 "declaration":{"declarant":{"id":"P301","name":"Артём Крылов","position":"Советник учреждения","agency_id":"AG301", "procurement_decision_role":False},
    "family":[{"id":"P302","name":"Наталья Крылова","relation":"spouse"}],
    "assets":[{"registry_id":"RE301","person_id":"P301","name":"Квартира на Полевой улице"}],
    "income":[{"id":"DI301","person_id":"P301","year":2025,"amount":1240000},
             {"id":"DI302","person_id":"P302","year":2025,"amount":40000}],
    "organizations":[],"obligations":[]},
 "registries":{"property":[ppty("RE301","P301","Квартира на Полевой улице")],
               "income":[inc("I301","P301",1240000),inc("I302","P302",40000)],
               "organizations":[org("ORG301","ООО «Вектор-Сервис»",[{"person_id":"P302","role":"участник, доля 100%","share":100,"from_year":2023}])],
               "contracts":[contract("ГК-2025-114","ORG301","AG999","Ремонт административного здания",18500000)],
               "enforcement":[]},
 "expected_rules":["R03_BUSINESS","R04_CONTRACT"]})
cases.append({
 "id":"case_4", "year":2025,
 "title":"Комплексная многоисточниковая проверка", "description":"Несколько разнородных расхождений, зарубежная недвижимость, контракт, доходы и исполнительное производство.",
 "declaration":{"declarant":{"id":"P401","name":"Марина Орлова","position":"Член демонстрационной закупочной комиссии","agency_id":"AG401", "procurement_decision_role":True},
    "family":[{"id":"P402","name":"Алексей Орлов","relation":"spouse"}],
    "assets":[{"registry_id":"RE401","person_id":"P401","name":"Квартира на Центральной улице"}],
    "income":[{"id":"DI401","person_id":"P401","year":2025,"amount":1550000},
             {"id":"DI402","person_id":"P402","year":2025,"amount":520000}],
    "organizations":[],"obligations":[]},
 "registries":{"property":[ppty("RE401","P401","Квартира на Центральной улице"),
                            ppty("RE402","P402","Апартаменты на Береговой улице"),
                            ppty("RE403","P402","Квартира в вымышленном зарубежном регионе",country="XX",from_year=2022)],
               "income":[inc("I401","P401",1990000),inc("I402","P402",520000)],
               "organizations":[org("ORG401","ООО «Техноконтур»",[{"person_id":"P402","role":"участник 50%","share":50,"from_year":2022}])],
               "contracts":[contract("ГК-2025-401","ORG401","AG401","Поставка оборудования",27000000)],
               "enforcement":[enforcement("EN401","P401",180000)]},
 "expected_rules":["R01_PROPERTY","R02_INCOME","R03_BUSINESS","R04_CONTRACT","R05_FOREIGN","R06_ENFORCEMENT"]})

for case in cases:
    (BASE/f"{case['id']}.json").write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
print('Created',len(cases),'demo cases')
