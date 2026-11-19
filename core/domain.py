"""Domain objects and strict, dependency-free validation of synthetic case files."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from hashlib import sha256
import json
import math
import re
from typing import Any

SCHEMA_VERSION = "1.0"
TYPES = ("property", "income", "organizations", "contracts", "enforcement")


class CaseValidationError(ValueError):
    pass


def canonical(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(obj: Any) -> str:
    return sha256(canonical(obj).encode("utf-8")).hexdigest()


def as_money(x: Any, key: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (float, int)) or x < 0 or x > 10**13 or not math.isfinite(x):
        raise CaseValidationError(f"{key}: ожидается неотрицательная сумма (число), не более 10 трлн")
    return float(x)


def _list(obj: dict, key: str, place: str) -> list:
    value = obj.get(key, [])
    if not isinstance(value, list):
        raise CaseValidationError(f"{place}.{key}: ожидается массив")
    if len(value) > 500:
        raise CaseValidationError(f"{place}.{key}: максимум 500 записей")
    if not all(isinstance(item, dict) for item in value):
        raise CaseValidationError(f"{place}.{key}: записи должны быть объектами")
    return value


def _parse_iso_date(value: Any, label: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise CaseValidationError(f"{label}: дата должна быть YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CaseValidationError(f"{label}: недопустимая календарная дата") from exc


def _validate_year_interval(record: dict, label: str) -> None:
    start, end = record.get("from_year"), record.get("to_year")
    for k, v in (("from_year", start), ("to_year", end)):
        if k in record and (type(v) is not int or not 2000 <= v <= 2100):
            raise CaseValidationError(f"{label}: {k} вне допустимого периода")
    if start is not None and end is not None and start > end:
        raise CaseValidationError(f"{label}: год начала не может быть позже года окончания")


def _references(record: dict, *fields: str) -> None:
    for key in fields:
        value = record.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise CaseValidationError(f"{key}: идентификатор должен быть непустой строкой")


def _required_fields(record: dict, location: str, fields: dict[str, type]) -> None:
    for key, expected in fields.items():
        if key not in record:
            raise CaseValidationError(f"{location}: отсутствует обязательное поле {key}")
        value = record[key]
        valid = isinstance(value, expected)
        if expected is int:
            valid = type(value) is int
        if expected is str:
            valid = valid and bool(value.strip())
        if not valid:
            names = {str: "непустая строка", int: "целое число", bool: "логическое значение", dict: "объект"}
            raise CaseValidationError(f"{location}: поле {key} — требуется {names[expected]}")


def _validate_relation_period(record: dict, label: str) -> None:
    _validate_year_interval(record, label)
    dates = {}
    for key, year_key in (("from_date", "from_year"), ("to_date", "to_year")):
        if key in record:
            dates[key] = _parse_iso_date(record[key], f"{label}.{key}")
            if year_key in record and record[year_key] != dates[key].year:
                raise CaseValidationError(f"{label}: дата не согласуется с годом")
    first = dates.get("from_date", date(record.get("from_year", 1), 1, 1))
    last = dates.get("to_date", date(record.get("to_year", 9999), 12, 31))
    if first > last:
        raise CaseValidationError(f"{label}: дата начала позже окончания")


def member_active_in_year(member: dict, year: int) -> bool:
    start = member.get("from_year", int(member["from_date"][:4]) if "from_date" in member else 9999)
    end = member.get("to_year", int(member["to_date"][:4]) if "to_date" in member else 2100)
    return int(start) <= year <= int(end)


def member_at_contract_date(member: dict, contract_date: date) -> bool:
    """Avoid asserting a connection at signing when only ambiguous annual data exists."""
    if not member_active_in_year(member, contract_date.year):
        return False
    if "from_date" in member:
        if _parse_iso_date(member["from_date"], "members.from_date") > contract_date:
            return False
    elif member.get("from_year") == contract_date.year:
        return False  # Joined sometime in the year; date of joining is unknown.
    if "to_date" in member:
        if _parse_iso_date(member["to_date"], "members.to_date") < contract_date:
            return False
    elif member.get("to_year") == contract_date.year:
        return False  # Could have left before signature.
    return True


def strict_json_loads(text: str) -> dict:
    """Reject duplicate JSON keys and non-finite literals before validation."""
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise CaseValidationError(f"Повторяющееся поле JSON: {key}")
            result[key] = value
        return result

    def reject_constant(value):
        raise CaseValidationError(f"Недопустимое числовое значение JSON: {value}")

    try:
        return json.loads(text, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
    except (ValueError, RecursionError) as exc:
        raise CaseValidationError(f"Некорректный JSON: {exc}") from exc


def validate_case(case: Any, *, strict_required: bool = True) -> dict:
    """Check schema, unique record IDs and a few semantic constraints; return normalized copy."""
    if not isinstance(case, dict):
        raise CaseValidationError("Корень JSON должен быть объектом")
    try:
        case = json.loads(canonical(case).encode("utf-8"))
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise CaseValidationError("Входные данные содержат недопустимые значения JSON (NaN, Infinity или объект)") from exc
    for key in ("id", "title", "description", "declaration", "registries"):
        if key not in case:
            raise CaseValidationError(f"Не заполнено обязательное поле {key}")
    for key in ("id", "title", "description"):
        if not isinstance(case[key], str) or not case[key].strip() or len(case[key]) > 400:
            raise CaseValidationError(f"{key}: ожидается непустая строка длиной до 400")
    dec, regs = case["declaration"], case["registries"]
    if not isinstance(dec, dict) or not isinstance(regs, dict):
        raise CaseValidationError("declaration и registries должны быть объектами")
    declarant = dec.get("declarant", {})
    if not isinstance(declarant, dict) or not declarant.get("id") or not declarant.get("name"):
        raise CaseValidationError("У декларанта нужны id и name")
    family = _list(dec, "family", "declaration")
    _references(declarant, "agency_id")
    for person in family:
        _validate_relation_period(person, "Семейная связь")
    persons = [declarant, *family]
    person_ids = [person.get("id") for person in persons]
    if any(not isinstance(pid, str) or not pid.strip() for pid in person_ids) or len(set(person_ids)) != len(person_ids):
        raise CaseValidationError("У людей должны быть уникальные непустые id")
    for person in persons:
        if not isinstance(person.get("name"), str) or not person["name"].strip():
            raise CaseValidationError("У каждого человека требуется имя")
    income_pairs = set()
    declared_ids = set()
    for key in ("assets", "income", "organizations", "obligations"):
        records = _list(dec, key, "declaration")
        for index, item in enumerate(records, 1):
            location = f"declaration.{key}, запись № {index}"
            required = {"person_id": str}
            if key == "income":
                required.update({"year": int})
            else:
                required[{"assets": "registry_id", "organizations": "org_id", "obligations": "enforcement_id"}[key]] = str
            if strict_required:
                _required_fields(item, location, required)
            if key == "income" and "amount" not in item:
                raise CaseValidationError(f"{location}: отсутствует обязательное поле amount")
            _references(item, "person_id", "registry_id", "org_id", "enforcement_id")
            if "id" in item:
                item_id = item["id"]
                if not isinstance(item_id, str) or not item_id or item_id in declared_ids:
                    raise CaseValidationError("Идентификаторы записей декларации должны быть уникальными")
                declared_ids.add(item_id)
            if key == "income":
                as_money(item.get("amount"), f"{location}, поле amount")
                if isinstance(item.get("year"), bool) or not isinstance(item.get("year"), int) or not (2000 <= item["year"] <= 2100):
                    raise CaseValidationError(f"{location}: поле year должно быть от 2000 до 2100")
                pair = (item.get("person_id"), item["year"])
                if pair in income_pairs:
                    raise CaseValidationError("Дублируются доходы одного человека за один год")
                income_pairs.add(pair)
            if item.get("person_id") is not None and item.get("person_id") not in person_ids:
                raise CaseValidationError(f"{location}: неизвестный person_id")
    for key in TYPES:
        records = _list(regs, key, "registries")
        for index, item in enumerate(records if strict_required else [], 1):
            location = f"registries.{key}, запись № {index}"
            required = {"id": str, "source": dict}
            required.update({
                "property": {"owner_id": str},
                "income": {"person_id": str, "year": int},
                "organizations": {"name": str},
                "contracts": {"contractor_org_id": str, "government": bool},
                "enforcement": {"person_id": str, "status": str},
            }[key])
            _required_fields(item, location, required)
            _required_fields(item["source"], f"{location}, source", {"name": str, "record_id": str, "as_of": str})
            if key in ("income", "contracts", "enforcement"):
                if "amount" not in item:
                    raise CaseValidationError(f"{location}: отсутствует обязательное поле amount")
                as_money(item["amount"], f"{location}, поле amount")
            if key == "organizations":
                for member_index, member in enumerate(_list(item, "members", location), 1):
                    _required_fields(member, f"{location}, members, запись № {member_index}", {"person_id": str})
        ids = [item.get("id") for item in records]
        if any(not isinstance(value, str) or not value.strip() for value in ids) or len(set(ids)) != len(ids):
            raise CaseValidationError(f"registries.{key}: идентификаторы id должны быть уникальными")
        for item in records:
            _references(item, "person_id", "owner_id", "contractor_org_id", "customer_agency_id")
            if not isinstance(item.get("source"), dict):
                raise CaseValidationError(f"Запись {item['id']} должна содержать объект source")
            source = item["source"]
            if not all(isinstance(source.get(k), str) and source[k].strip() for k in ("name", "record_id", "as_of")):
                raise CaseValidationError(f"Источник {item['id']} требует name, record_id и as_of")
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", source["as_of"]):
                    raise ValueError("Некорректный формат")
                date.fromisoformat(source["as_of"])
            except ValueError as exc:
                raise CaseValidationError(f"Источник {item['id']}: дата as_of в формате YYYY-MM-DD") from exc
            if key in ("income", "enforcement"):
                as_money(item.get("amount"), f"registries.{key}.amount")
            if key == "income":
                if not isinstance(item.get("year"), int) or isinstance(item.get("year"), bool) or not (2000 <= item["year"] <= 2100):
                    raise CaseValidationError("Год внешней записи о доходах должен быть от 2000 до 2100")
            if key == "property":
                for date_key in ("from_year", "to_year"):
                    if date_key in item and (isinstance(item[date_key], bool) or not isinstance(item[date_key], int)):
                        raise CaseValidationError(f"Недвижимость {item['id']}: {date_key} должен быть целым годом")
                if not isinstance(item.get("country", "RU"), str) or not re.fullmatch(r"[A-Za-z]{2}", item.get("country", "RU")):
                    raise CaseValidationError("Код страны должен состоять из двух латинских букв")
                _validate_year_interval(item, f"Недвижимость {item['id']}")
            if key == "organizations":
                if not isinstance(item.get("name"), str) or not item["name"].strip():
                    raise CaseValidationError("Организации требуется название")
                for member in _list(item, "members", f"registries.organizations.{item['id']}"):
                    _references(member, "person_id")
                    _validate_relation_period(member, f"Участник организации {item['id']}")
            if key == "contracts":
                as_money(item.get("amount"), "registries.contracts.amount")
                if not isinstance(item.get("government"), bool):
                    raise CaseValidationError("Флаг government должен быть логическим")
                if "signed_on" in item:
                    _parse_iso_date(item["signed_on"], "contracts.signed_on")
                    if item["signed_on"] > source["as_of"]:
                        raise CaseValidationError("Источник не может подтверждать контракт, который ещё не подписан на дату записи")
    case.setdefault("year", 2025)
    if isinstance(case["year"], bool) or not isinstance(case["year"], int) or not (2000 <= case["year"] <= 2100):
        raise CaseValidationError("year должен быть целым годом")
    all_ids = list(person_ids)
    for key in TYPES:
        all_ids += [record["id"] for record in regs.get(key, [])]
    if len(set(all_ids)) != len(all_ids):
        raise CaseValidationError("Идентификаторы лиц и записей различных источников не должны совпадать")
    # An agency is a separate graph node; an ID collision would silently replace
    # a person, organization, or record in NetworkX.
    for contract in regs.get("contracts", []):
        agency_id = contract.get("customer_agency_id")
        if agency_id is not None and (not isinstance(agency_id, str) or not agency_id.strip() or agency_id in all_ids):
            raise CaseValidationError("ID заказчика должен быть непустым и не совпадать с ID других объектов")
    case.setdefault("expected_rules", [])
    if not isinstance(case["expected_rules"], list):
        raise CaseValidationError("expected_rules должен быть массивом")
    case["schema_version"] = SCHEMA_VERSION
    return case


@dataclass(frozen=True)
class Evidence:
    source: str
    record_id: str
    as_of: str
    fact: str
    path: str


@dataclass(frozen=True)
class Signal:
    id: str
    rule: str
    title: str
    severity: str
    summary: str
    reasoning: str
    next_step: str
    entities: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    path: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


def evidence(record: dict, fact: str, path: str) -> Evidence:
    src = record["source"]
    return Evidence(src["name"], src["record_id"], src["as_of"], fact, path)


def new_signal(case_id: str, rule: str, anchor: str, title: str, severity: str,
               summary: str, reasoning: str, next_step: str, entities: list[str],
               records: list[Evidence], path: list[str] | None = None) -> Signal:
    signal_id = f"SIG-{sha256(f'{case_id}|{rule}|{anchor}'.encode()).hexdigest()[:10].upper()}"
    return Signal(signal_id, rule, title, severity, summary, reasoning, next_step,
                  tuple(entities), tuple(records), tuple(path or []))
