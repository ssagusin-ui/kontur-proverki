"""Local SQLite case snapshots, human reviews and tamper-evident append-only audit chain.

Not a qualified e-signature, WORM storage or an external trusted timestamp service.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import json
import sqlite3

from core.domain import canonical, digest, validate_case
from core.rules import evaluate

STATUS_LABELS = {
    "new": "Новый",
    "in_review": "В работе",
    "need_docs": "Запрошены документы",
    "not_confirmed": "Не подтвердился",
    "data_confirmed": "Расхождение подтверждено данными",
}


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.path, timeout=15)
        try:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("PRAGMA busy_timeout=15000")
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _init(self):
        with self._connect() as db:
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, case_id TEXT NOT NULL, title TEXT NOT NULL,
                    origin TEXT NOT NULL, created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
                    signals_json TEXT NOT NULL, signals_hash TEXT NOT NULL DEFAULT '',
                    last_event_hash TEXT NOT NULL DEFAULT '', event_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    signal_id TEXT NOT NULL, status TEXT NOT NULL,
                    note TEXT NOT NULL, reviewer TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, signal_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id),
                    happened_at TEXT NOT NULL, actor TEXT NOT NULL,
                    event_type TEXT NOT NULL, target TEXT NOT NULL,
                    payload_json TEXT NOT NULL, prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_events_run ON events(run_id, seq);
                CREATE INDEX IF NOT EXISTS ix_runs_created ON runs(created_at DESC);
            """)
            # Additive migration: never replace or delete a pre-existing SQLite database.
            columns = {row["name"] for row in db.execute("PRAGMA table_info(runs)")}
            additions = {"signals_hash": "TEXT NOT NULL DEFAULT ''",
                         "last_event_hash": "TEXT NOT NULL DEFAULT ''",
                         "event_count": "INTEGER NOT NULL DEFAULT 0"}
            legacy = any(col not in columns for col in ("event_count", "last_event_hash"))
            for column, spec in additions.items():
                if column not in columns:
                    db.execute(f"ALTER TABLE runs ADD COLUMN {column} {spec}")
            if legacy:
                for run in db.execute("SELECT id FROM runs").fetchall():
                    events = db.execute("SELECT event_hash FROM events WHERE run_id=? ORDER BY seq", (run["id"],)).fetchall()
                    db.execute("UPDATE runs SET event_count=?,last_event_hash=? WHERE id=?",
                               (len(events), events[-1]["event_hash"] if events else "", run["id"]))

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _append(self, db, rid: str, actor: str, event_type: str, target: str, payload: dict):
        row = db.execute("SELECT event_hash FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 1", (rid,)).fetchone()
        prev = row["event_hash"] if row else "GENESIS"
        body = {"run_id": rid, "happened_at": self._now(), "actor": actor, "event_type": event_type,
                "target": target, "payload": payload, "prev_hash": prev}
        event_hash = digest(body)
        db.execute("INSERT INTO events(run_id,happened_at,actor,event_type,target,payload_json,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?,?)",
                   (rid, body["happened_at"], actor, event_type, target, canonical(payload), prev, event_hash))
        db.execute("UPDATE runs SET last_event_hash=?,event_count=event_count+1 WHERE id=?", (event_hash, rid))

    def create_run(self, case: dict, origin: str = "demo", actor: str = "Система") -> str:
        case = validate_case(case)
        signals = [s.to_dict() for s in evaluate(case)]
        rid = "CHK-" + uuid4().hex[:12].upper()
        now = self._now()
        with self._connect() as db:
            db.execute("INSERT INTO runs(id, case_id, title, origin, created_at, payload_json, payload_hash, signals_json, signals_hash) VALUES (?,?,?,?,?,?,?,?,?)",
                       (rid, case["id"], case["title"], origin, now, canonical(case), digest(case), canonical(signals), digest(signals)))
            for signal in signals:
                db.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?)", (rid, signal["id"], "new", "", "Система", now))
            self._append(db, rid, actor, "RUN_CREATED", rid, {"case_id": case["id"], "dataset_sha256": digest(case), "signal_ids": [s["id"] for s in signals], "signals_sha256": digest(signals), "origin": origin})
        return rid

    def list_runs(self, limit=100):
        with self._connect() as db:
            rows = db.execute("SELECT r.id,r.case_id,r.title,r.origin,r.created_at,r.payload_hash,(SELECT count(*) FROM reviews v WHERE v.run_id=r.id) AS signal_count,(SELECT count(*) FROM reviews v WHERE v.run_id=r.id AND v.status NOT IN ('not_confirmed', 'data_confirmed')) AS pending_count FROM runs r ORDER BY r.created_at DESC, r.rowid DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def summary(self) -> dict:
        """Whole-database dashboard totals; list_runs() intentionally only paginates."""
        with self._connect() as db:
            row = db.execute("""SELECT
                (SELECT COUNT(*) FROM runs) AS runs,
                (SELECT COUNT(*) FROM reviews) AS signals,
                (SELECT COUNT(*) FROM reviews WHERE status NOT IN ('not_confirmed','data_confirmed')) AS pending""").fetchone()
            return dict(row)

    def get_run(self, rid):
        with self._connect() as db:
            db.execute("BEGIN")
            row = db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
            if not row:
                raise KeyError(f"Проверка {rid} не найдена")
            data = dict(row)
            data["dataset"] = json.loads(data.pop("payload_json"))
            data["signals"] = json.loads(data.pop("signals_json"))
            reviews = db.execute("SELECT * FROM reviews WHERE run_id=?", (rid,)).fetchall()
            data["reviews"] = {r["signal_id"]: dict(r) for r in reviews}
            return data

    def update_review(self, rid: str, signal_id: str, status: str, note: str, reviewer: str = "Аналитик") -> None:
        if status not in STATUS_LABELS:
            raise ValueError("Неизвестный статус")
        note, reviewer = note.strip(), reviewer.strip()
        if len(note) > 3000 or not reviewer or len(reviewer) > 80:
            raise ValueError("Комментарий до 3000 символов, имя проверяющего от 1 до 80")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT status,note,reviewer FROM reviews WHERE run_id=? AND signal_id=?", (rid, signal_id)).fetchone()
            if not old:
                raise KeyError("Сигнал не найден в этой проверке")
            if old["status"] == status and old["note"] == note and old["reviewer"] == reviewer:
                return
            db.execute("UPDATE reviews SET status=?,note=?,reviewer=?,updated_at=? WHERE run_id=? AND signal_id=?",
                       (status, note, reviewer, self._now(), rid, signal_id))
            self._append(db, rid, reviewer, "REVIEW_UPDATED", signal_id,
                         {"before": {"status": old["status"], "note": old["note"], "reviewer": old["reviewer"]},
                          "after": {"status": status, "note": note, "reviewer": reviewer}})

    def events(self, rid: str):
        with self._connect() as db:
            return [dict(x) for x in db.execute("SELECT * FROM events WHERE run_id=? ORDER BY seq", (rid,)).fetchall()]

    def audit_integrity(self, rid: str) -> tuple[bool, str]:
        """Check snapshots, event chain, event count and review state for consistency.

        Legacy databases without saved signal hashes remain readable, but their
        report warns that the historical signals snapshot cannot be proven.
        All checks use hashes stored in the same SQLite file; not a trust anchor.
        """
        try:
            run = self.get_run(rid)
            if digest(run["dataset"]) != run["payload_hash"]:
                return False, "Контрольная сумма исходного набора данных не совпадает"
            if run.get("signals_hash") and digest(run["signals"]) != run["signals_hash"]:
                return False, "Контрольная сумма сохранённых сигналов не совпадает"
            signal_ids = [item["id"] for item in run["signals"]]
            if len(set(signal_ids)) != len(signal_ids):
                return False, "Найдены повторяющиеся идентификаторы сигналов"
            if set(signal_ids) != set(run["reviews"]):
                return False, "Набор записей решений не соответствует списку сигналов"
            events = self.events(rid)
            if not events or events[0]["event_type"] != "RUN_CREATED":
                return False, "Отсутствует исходное событие проверки"
            if run.get("event_count") != len(events):
                return False, "Количество событий не совпадает с контрольным значением"
            if run.get("last_event_hash") != events[-1]["event_hash"]:
                return False, "Контрольная сумма последнего события не совпадает"
            prev = "GENESIS"
            expected_reviews = {sid: {"status": "new", "note": "", "reviewer": "Система"} for sid in signal_ids}
            for position, event in enumerate(events):
                if event["run_id"] != rid:
                    return False, "Журнал содержит событие другой проверки"
                if event["prev_hash"] != prev:
                    return False, f"Нарушена последовательность на событии {event['seq']}"
                payload = json.loads(event["payload_json"])
                body = {"run_id": event["run_id"], "happened_at": event["happened_at"],
                        "actor": event["actor"], "event_type": event["event_type"],
                        "target": event["target"], "payload": payload, "prev_hash": prev}
                if digest(body) != event["event_hash"]:
                    return False, f"Контрольная сумма события {event['seq']} не совпадает"
                if position == 0:
                    if event["target"] != rid or payload.get("dataset_sha256") != run["payload_hash"]:
                        return False, "Исходное событие не соответствует снимку данных"
                    if payload.get("signal_ids") != signal_ids:
                        return False, "Исходное событие не соответствует списку сигналов"
                    if payload.get("signals_sha256") and payload["signals_sha256"] != digest(run["signals"]):
                        return False, "Сохранённые сигналы не соответствуют исходному событию"
                elif event["event_type"] == "REVIEW_UPDATED":
                    sid = event["target"]
                    if sid not in expected_reviews:
                        return False, "Событие относится к отсутствующему сигналу"
                    old = payload.get("before", {})
                    after = payload.get("after", {})
                    for field in ("status", "note"):
                        if old.get(field) != expected_reviews[sid][field]:
                            return False, "Нарушена последовательность решений специалиста"
                    if "reviewer" in old and old["reviewer"] != expected_reviews[sid]["reviewer"]:
                        return False, "Нарушена последовательность авторов решений"
                    if after.get("status") not in STATUS_LABELS or not isinstance(after.get("note"), str):
                        return False, "Недопустимые данные в событии решения"
                    expected_reviews[sid] = {"status": after["status"], "note": after["note"],
                                              "reviewer": after.get("reviewer", event["actor"])}
                else:
                    return False, "Неизвестное или повторное событие создания проверки"
                prev = event["event_hash"]
            for sid, expected in expected_reviews.items():
                review = run["reviews"][sid]
                for field, value in expected.items():
                    if review[field] != value:
                        return False, f"Состояние решения {sid} не соответствует истории событий"
            if not run.get("signals_hash"):
                return True, "Журнал согласован; для старой проверки нет независимого хеша списка сигналов"
            return True, "Цепочка событий, сигналы и состояния решений согласованы"
        except (ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError) as exc:
            return False, f"Повреждённые данные или структура журнала: {type(exc).__name__}"
