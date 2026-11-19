"""Контур проверки — a standalone explainable declaration-review demonstration.

Start: python -m streamlit run app.py
No external systems, model APIs, or real registry integrations.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
import json
import logging
import os
import sqlite3
from pathlib import Path

import networkx as nx
import plotly.graph_objects as go
import streamlit as st

from core.domain import CaseValidationError, validate_case, strict_json_loads
from core.graph import build_graph, NODE_LABELS
from core.report import create_html_report
from core.rules import RULEBOOK, coverage, evaluate
from core.storage import Store, STATUS_LABELS

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("KONTUR_DB", ROOT / "storage" / "kontur.db"))
LOGGER = logging.getLogger(__name__)
DEMO_FILES = sorted((ROOT / "demo").glob("case_*.json"))
SEVERITY = {"high": ("Высокий", "#d05e40"), "medium": ("Средний", "#bf861f"), "low": ("Низкий", "#43849a")}
COLORS = {"declarant": "#184d69", "family": "#319c99", "organization": "#9b79c6",
          "contract": "#e5a15f", "private_contract": "#8c7043",
          "property": "#69a1da", "agency": "#81919a", "enforcement": "#db7c7c"}
TEMPORAL_LABELS = {"active": "Действует на дату", "historical": "Завершилась до даты",
                   "future": "Началась после даты", "unknown": "Период требует уточнения"}

st.set_page_config(page_title="Контур проверки", layout="wide",
                   initial_sidebar_state="expanded", menu_items={"About": "Контур проверки — аналитическая платформа."})

st.markdown("""
<style>
:root {
  --ink:#122F40; --soft:#526A78; --teal:#08747C;
  --teal-hover:#075C64; --line:#DCE7EA;
}
html, body, [data-testid="stAppViewContainer"], .stApp {
  background:#F6F9FA; color:var(--ink);
}
/* Sidebar: consistent high-contrast navigation, no white-on-white buttons. */
[data-testid="stSidebar"] {
  background:#102B3E !important;
  border-right:1px solid #254557;
}
[data-testid="stSidebar"] .brand {color:#FFFFFF !important;}
[data-testid="stSidebar"] .brand small {color:#B9D2DE !important;}
[data-testid="stSidebar"] [data-testid="stButton"] button {
  background:#203F52 !important;
  border:1px solid #3E6072 !important;
  border-radius:11px !important;
  color:#F7FAFC !important;
  font-weight:650 !important;
  min-height:43px;
  opacity:1 !important;
  box-shadow:none !important;
  transition:background .16s ease,border-color .16s ease;
}
[data-testid="stSidebar"] [data-testid="stButton"] button *,
[data-testid="stSidebar"] [data-testid="stButton"] button p,
[data-testid="stSidebar"] [data-testid="stButton"] button span {
  color:inherit !important;
  opacity:1 !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"] {
  background:#08747C !important;
  border-color:#35B7B2 !important;
  color:#FFFFFF !important;
  box-shadow:inset 3px 0 0 #A2F0E2 !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] button[kind="secondary"]:hover {
  background:#2B5266 !important;
  border-color:#78B1B6 !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"]:hover {
  background:#09666C !important;
}
[data-testid="stSidebar"] hr {border-color:#315060 !important;}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] * {color:#C6D8DE !important;}
[data-testid="stSidebar"] [data-baseweb="select"] > div {background:#23465B !important;}

/* Main actions: ink-filled primary buttons; clear, dark secondary labels. */
[data-testid="stMain"] [data-testid="stButton"] button[kind="primary"],
[data-testid="stMain"] [data-testid="stFormSubmitButton"] button[kind="primary"],
[data-testid="stMain"] [data-testid="stDownloadButton"] button[kind="primary"] {
  background:var(--teal) !important;
  border:1px solid var(--teal) !important;
  color:#FFFFFF !important;
  font-weight:650;
  border-radius:10px;
}
[data-testid="stMain"] button[kind="primary"] *,
[data-testid="stMain"] button[kind="primary"] p {color:#FFFFFF !important;}
[data-testid="stMain"] button[kind="primary"]:hover {
  background:var(--teal-hover) !important;
  border-color:var(--teal-hover) !important;
}
[data-testid="stMain"] button[kind="secondary"] {
  background:#FFFFFF !important;
  border:1px solid #C6D5DB !important;
  border-radius:10px !important;
  color:#163B50 !important;
  font-weight:600;
}
[data-testid="stMain"] button[kind="secondary"] *,
[data-testid="stMain"] button[kind="secondary"] p {color:#163B50 !important;}
[data-testid="stMain"] button[kind="secondary"]:hover {
  background:#EAF4F5 !important;
  border-color:#08747C !important;
}
button:focus-visible {outline:3px solid #51B6B7 !important; outline-offset:2px !important;}
button:disabled {cursor:not-allowed !important;}
.block-container {max-width:1450px; padding-top:2rem; padding-bottom:5rem;}
h1,h2,h3 {color:#17354A !important; font-family:'Segoe UI','Inter',sans-serif; letter-spacing:-.035em;}
h1{font-weight:760 !important} h2{font-weight:720 !important}
p,label,span,.stMarkdown {line-height:1.5;}
div[data-testid="stVerticalBlockBorderWrapper"] > div {border-color:#DCE7EA !important;border-radius:15px !important;}
[data-testid="stMetric"] {background:#FFFFFF;border:1px solid #DFE9EB;border-radius:16px;padding:18px 20px;box-shadow:0 5px 22px rgba(18,48,65,.03);}
[data-testid="stMetricLabel"] {color:#526A78;} [data-testid="stMetricValue"] {font-size:1.8rem;color:#18394B;}
[data-testid="stTabs"] button {font-weight:650;}
[data-testid="stAlert"] {border-radius:12px;}
[data-testid="stDataFrame"] {border:1px solid #DCE6E9;border-radius:12px;overflow:hidden;}
.hero {background:linear-gradient(118deg,#112C3B 12%,#17474D 76%,#236D63 100%);color:white;padding:clamp(22px,4vw,52px);border-radius:18px;margin-bottom:15px;position:relative;overflow:hidden;}
.hero:after{content:'';position:absolute;right:-40px;top:-90px;width:310px;height:310px;border:1px solid rgba(255,255,255,.14);border-radius:50%;box-shadow:0 0 0 38px rgba(255,255,255,.025),0 0 0 82px rgba(255,255,255,.018);}
.hero h1{color:#FFFFFF !important;margin:0 0 12px;font-size:clamp(32px,5vw,58px);line-height:1.1;}
.hero p{color:#E0F1F1;max-width:770px;margin:0;font-size:15px;}
.brand{font-size:23px;font-weight:780;letter-spacing:-1px;margin:6px 0 3px;}
.brand small{display:block;font-size:11px;letter-spacing:1.7px;font-weight:550;text-transform:uppercase;}
.kicker{color:#08747C;letter-spacing:1.65px;font-size:11px;font-weight:800;text-transform:uppercase;margin-top:16px;}
.subhead{color:#526A78;max-width:940px;font-size:14px;margin:-4px 0 18px;}
.small-label{font-weight:700;font-size:11px;color:#778D98;letter-spacing:1.1px;text-transform:uppercase;}
.signal-header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;}
.rule-tag{font-size:12px;color:#67818D;margin:4px 0;}
.signal-title{font-weight:740;font-size:19px;color:#19374B;margin:5px 0 9px;}
.signal-note{font-size:12px;color:#6F8590;line-height:1.5;}
.source-row{background:#F2F7F8;border-radius:8px;padding:8px 12px;margin:5px 0;font-size:12px;}
[data-testid="stMain"] [data-testid="stCaptionContainer"],
[data-testid="stMain"] [data-testid="stCaptionContainer"] p {color:#48606e !important;}
/* Hide development toolbar in the presented application. */
[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stHeaderActionElements"],
[data-testid="stMainMenu"],[data-testid="stStatusWidget"] {display:none !important;}
footer,#MainMenu {visibility:hidden;}
[data-testid="stHeader"] {background:transparent;}
@media(max-width:700px) {
  .block-container {padding:3.5rem 1.1rem 3rem;}
  .hero:after {display:none;}
  .signal-header {flex-wrap:wrap;}
}
</style>
""", unsafe_allow_html=True)


@st.cache_resource(show_spinner=False)
def get_store() -> Store:
    return Store(DB_PATH)


@st.cache_data(show_spinner=False)
def load_demo(path: str) -> dict:
    return validate_case(strict_json_loads(Path(path).read_text(encoding="utf-8")))


store = get_store()
DEMOS = {Path(p).stem: load_demo(str(p)) for p in DEMO_FILES}

if "page" not in st.session_state:
    st.session_state.page = "Обзор"
if "active_run" not in st.session_state:
    st.session_state.active_run = None


def open_run(rid: str):
    st.session_state.active_run = rid
    st.session_state.run_redirect = "Сигналы"
    st.session_state.page = "Проверка"
    st.rerun()


def fmt_money(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ") + " ₽"


def title(kicker: str, heading: str, desc: str | None = None):
    st.markdown(f"<div class='kicker'>{escape(kicker)}</div>", unsafe_allow_html=True)
    st.title(heading)
    if desc:
        st.markdown(f"<div class='subhead'>{escape(desc)}</div>", unsafe_allow_html=True)


def record_labels(case: dict) -> list[dict]:
    d = case["declaration"]
    r = [{"Тип": "Декларант", "Лицо": d["declarant"]["name"], "ID": d["declarant"]["id"]}]
    r += [{"Тип": "Член семьи", "Лицо": p["name"], "ID": p["id"]} for p in d.get("family", [])]
    return r


def dataset_details(case):
    d = case["declaration"]
    st.dataframe(record_labels(case), use_container_width=True, hide_index=True)
    left, right = st.columns(2)
    with left:
        st.markdown("**Имущество, указанное в декларации**")
        if d.get("assets"):
            st.dataframe([{"Объект": r.get("name", "—"), "ID источника": r.get("registry_id", "—"), "Лицо": r.get("person_id", "—")} for r in d["assets"]], hide_index=True, use_container_width=True)
        else:
            st.caption("Не представлено")
    with right:
        st.markdown("**Заявленные доходы**")
        if d.get("income"):
            st.dataframe([{"Лицо": r.get("person_id") or "Не указано", "Год": r["year"], "Сумма": fmt_money(r["amount"])} for r in d["income"]], hide_index=True, width="stretch")
        else:
            st.caption("Не представлены")


def graph_plot(graph: nx.DiGraph, chosen: str | None, path: list[str] | None = None):
    fig = go.Figure()
    if not graph:
        return fig
    # Stable layout for reproducibility, the same given dataset always yields the same coordinates.
    path = path or []
    positions = nx.spring_layout(graph, seed=17, iterations=45)
    if len(path) > 1 and all(node in graph for node in path):
        positions = {node: (float(x), float(y) * 0.45 + 0.82) for node, (x, y) in positions.items()}
        positions.update({node: (2 * i / (len(path) - 1) - 1, 0) for i, node in enumerate(path)})
    selected_edges = set(zip(path[:-1], path[1:]))
    for u, v, meta in graph.edges(data=True):
        xa, ya = positions[u]
        xb, yb = positions[v]
        selected = (u, v) in selected_edges or (v, u) in selected_edges
        temporal_status = meta.get("temporal_status", "unknown")
        hover = "<br>".join(escape(str(value)) for value in (
            meta["label"], meta.get("source", "—"), meta.get("record_id", "—"),
            meta.get("period", "Период не указан"), TEMPORAL_LABELS.get(temporal_status, ""),
        ))
        fig.add_trace(go.Scatter(
            x=[xa, (xa + xb) / 2, xb], y=[ya, (ya + yb) / 2, yb],
            mode="lines", showlegend=False, text=[hover] * 3, hovertemplate="%{text}<extra></extra>",
            line={"color": "#0e847e" if selected else "#829ba6", "width": 4 if selected else 2,
                  "dash": "dash" if temporal_status in {"historical", "future"} else
                          "dot" if temporal_status == "unknown" else "solid"},
        ))
    kinds = sorted(set(nx.get_node_attributes(graph, "kind").values()))
    for kind in kinds:
        ids = [n for n, meta in graph.nodes(data=True) if meta["kind"] == kind]
        texts = [str(graph.nodes[n]["label"]) for n in ids]
        display_labels = [escape(t if len(t) < 33 else t[:30] + "…") for t in texts]
        hover_rows = []
        for node in ids:
            meta = graph.nodes[node]
            hover_rows.append([escape(str(value)) for value in (
                node, meta.get("source", "—"), meta.get("record_id", "—"), meta["label"],
            )])
        fig.add_trace(go.Scatter(
            x=[positions[n][0] for n in ids], y=[positions[n][1] for n in ids],
            mode="markers+text", name=NODE_LABELS.get(kind, kind), text=display_labels,
            textposition="bottom center", textfont={"size": 12, "color": "#234356"},
            marker={"size": [37 if n == chosen else 30 if n in path else 22 for n in ids],
                    "color": COLORS.get(kind, "#748b9a"), "line": {"width": [4 if n == chosen else 2 for n in ids], "color": "#ffffff"}},
            customdata=hover_rows,
            hovertemplate="<b>%{customdata[3]}</b><br>ID: %{customdata[0]}<br>Источник: %{customdata[1]}<br>Запись: %{customdata[2]}<extra></extra>"
        ))
    fig.update_layout(height=420, hovermode="closest", showlegend=True,
                      legend={"orientation": "h", "y": -0.1, "x": 0, "font": {"size": 11}},
                      margin=dict(l=34, r=34, t=32, b=74),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      xaxis={"visible": False}, yaxis={"visible": False, "scaleanchor": "x", "scaleratio": 1})
    return fig


def section_signal(sig: dict, review: dict, run_id: str):
    sev_label, color = SEVERITY.get(sig["severity"], ("Сигнал", "#657b82"))
    with st.container(border=True):
        st.markdown(f"""<div class='signal-header'><div><div class='small-label'>{escape(sig['rule'])} · {escape(sig['id'])}</div><div class='signal-title'>{escape(sig['title'])}</div></div>
            <div style='color:{color};font-weight:750;font-size:12px;border:1px solid {color};padding:6px 9px;border-radius:20px'>{escape(sev_label)} приоритет</div></div>""", unsafe_allow_html=True)
        st.write(sig["summary"])
        st.caption("Текущий статус: " + STATUS_LABELS.get(review["status"], review["status"]))
        with st.expander("Почему сработало правило и что проверить", expanded=True):
            st.markdown("**Логика сопоставления**")
            st.write(sig["reasoning"])
            st.markdown("**Рекомендованное действие**")
            st.write(sig["next_step"])
            if len(sig.get("path", [])) > 1:
                if st.button("Открыть связи на графе", key=f"focus_{run_id}_{sig['id']}"):
                    st.session_state.graph_focus = sig["id"]
                    st.session_state.run_redirect = "Граф связей"
                    st.rerun()
        with st.expander(f"Источники и доказательные записи · {len(sig['evidence'])}"):
            for ev in sig["evidence"]:
                st.write(ev["source"])
                st.caption(f"Запись: {ev['record_id']} · По состоянию на {ev['as_of']}")
                st.caption(ev["fact"])
        with st.form(f"review_{run_id}_{sig['id']}", clear_on_submit=False):
            st.markdown("**Решение проверяющего**")
            status_keys = list(STATUS_LABELS)
            selected = st.selectbox("Статус", status_keys, index=status_keys.index(review["status"]),
                                   format_func=lambda k: STATUS_LABELS[k])
            note = st.text_area("Обоснование / комментарий", value=review["note"], max_chars=3000,
                                placeholder="Какие документы изучены, какие уточнения требуются…", height=95)
            reviewer = st.text_input("Проверяющий", value=review["reviewer"] if review["reviewer"] != "Система" else "Аналитик", max_chars=80)
            saved = st.form_submit_button("Сохранить решение", type="primary")
            if saved:
                try:
                    store.update_review(run_id, sig["id"], selected, note, reviewer)
                    st.toast("Решение сохранено")
                    st.rerun()
                except (ValueError, KeyError) as exc:
                    st.error(str(exc))
                except sqlite3.Error:
                    LOGGER.exception("Review could not be saved")
                    st.error("Решение не сохранено. Повторите попытку.")


def view_overview():
    st.markdown("<div class='hero'><h1>Контур проверки</h1><p>Аналитическая система сопоставления деклараций и структурированных сведений об имуществе, организациях и контрактах. От обнаруженной связи — к источнику и обоснованному решению специалиста.</p></div>", unsafe_allow_html=True)
    rows = store.list_runs()
    totals = store.summary()
    runs_count = totals["runs"]
    signals_count = totals["signals"]
    pending = totals["pending"]
    a,b,c,d = st.columns(4)
    a.metric("Проверок в базе", runs_count)
    b.metric("Аналитических сигналов", signals_count)
    c.metric("На рассмотрении", pending)
    d.metric("Готовых сценариев", len(DEMOS))
    st.write("")
    left,right = st.columns([3,1],vertical_alignment="center")
    with left:
        st.subheader("Последние проверки")
    with right:
        if st.button("+ Новая проверка", type="primary", use_container_width=True):
            st.session_state.page = "Новая проверка"; st.rerun()
    if not rows:
        st.info("Проверок пока нет. Создайте новую проверку, чтобы увидеть результаты анализа.")
    else:
        st.dataframe([{"Проверка": r["id"], "Сценарий": r["title"], "Время (UTC)": r["created_at"].replace("T"," ")[:19],
                       "Сигналов": r["signal_count"], "Не завершено": r["pending_count"]} for r in rows[:12]],
                     use_container_width=True, hide_index=True)
        chosen = st.selectbox("Открыть проверку", [r["id"] for r in rows], format_func=lambda rid: rid + " · " + next((r["title"] for r in rows if r["id"] == rid), ""))
        if st.button("Перейти к результатам"):
            open_run(chosen)


def view_create():
    title("Новая проверка", "Загрузка и сопоставление", "Выберите сценарий или загрузите свой набор. Исходные сведения сохранятся вместе с результатами.")
    demo_choice = st.radio("Источник данных", ("Демонстрационный кейс", "Файл JSON"), horizontal=True)
    dataset = None
    if demo_choice == "Демонстрационный кейс":
        selected = st.selectbox("Сценарий", list(DEMOS), format_func=lambda x: f"{x.replace('case_', 'Кейс ')} · {DEMOS[x]['title']}")
        dataset = DEMOS[selected]
    else:
        st.caption("Загрузите структурированный JSON. Не загружайте реальные персональные данные.")
        upload = st.file_uploader("Загрузить структурированный JSON", type=["json"], help="До 2 МБ. Обязательны декларация, записи источников и идентификаторы.")
        st.download_button("Скачать пример JSON", data=Path(DEMO_FILES[2]).read_bytes(), file_name="primer_struktury.json", mime="application/json")
        if upload is not None:
            try:
                contents = upload.getvalue()
                if len(contents) > 2_000_000:
                    raise CaseValidationError("Максимальный размер файла — 2 МБ")
                dataset = validate_case(strict_json_loads(contents.decode("utf-8-sig")))
            except (UnicodeError, json.JSONDecodeError, CaseValidationError) as exc:
                st.error("Не удалось прочитать набор данных: " + str(exc))
                st.caption("Исправьте файл и выберите его снова в этом же поле.")
    if not dataset:
        return
    st.write("")
    with st.container(border=True):
        st.subheader(dataset["title"])
        st.write(dataset["description"])
        a,b,c = st.columns(3)
        a.metric("Лиц в декларации", 1 + len(dataset["declaration"].get("family", [])))
        b.metric("Всего записей источников", sum(len(v) for v in dataset["registries"].values() if isinstance(v, list)))
        c.metric("Отчётный год", dataset["year"])
        with st.expander("Предварительный просмотр исходных данных"):
            dataset_details(dataset)
        with st.expander("Покрытие модельных источников"):
            st.dataframe(coverage(dataset), use_container_width=True, hide_index=True)
        st.caption("Отсутствие записи в модельном источнике не подтверждает отсутствие имущества или дохода в реальном мире.")
        if st.button("Запустить аналитическую проверку", type="primary", use_container_width=True):
            try:
                with st.spinner("Сопоставляем сведения…"):
                    rid = store.create_run(dataset, origin="demo" if demo_choice == "Демонстрационный кейс" else "uploaded")
            except CaseValidationError as exc:
                st.error(str(exc))
            except sqlite3.Error:
                LOGGER.exception("Run could not be saved")
                st.error("Проверка не сохранена. Повторите попытку.")
            else:
                st.toast("Проверка сохранена")
                open_run(rid)


def edge_details(meta: dict) -> str:
    status = TEMPORAL_LABELS.get(meta.get("temporal_status"), "")
    return " · ".join(filter(None, (
        str(meta.get("relation_type", meta["label"])), meta["source"], meta["record_id"], f"Сведения на {meta['as_of']}",
        meta.get("period"), status,
    )))


def view_graph(case: dict, signals: list[dict], rid: str):
    st.subheader("Граф связей")
    signal_options = {s["id"]: s for s in signals if len(s.get("path", [])) > 1}
    focus = st.session_state.pop("graph_focus", None)
    focus_key = f"graph_signal_{rid}"
    if focus in signal_options:
        st.session_state[focus_key] = focus
    highlight = st.selectbox(
        "Показать путь сигнала", [None, *signal_options],
        format_func=lambda s: signal_options[s]["title"] if s else "Все связи", key=focus_key,
    )
    active_path = signal_options[highlight]["path"] if highlight else []
    contract_dates = {r["id"]: r["signed_on"] for r in case["registries"].get("contracts", []) if r.get("signed_on")}
    date_options = [None, *sorted(set(contract_dates.values()))]
    preferred_date = next((contract_dates[n] for n in active_path if n in contract_dates), None)
    as_of = st.selectbox(
        "Дата связей", date_options, index=date_options.index(preferred_date),
        format_func=lambda value: f"Дата подписания · {value}" if value else f"Конец отчётного года · {case['year']}",
        key=f"graph_date_{rid}_{highlight}",
    )
    include_historical = st.checkbox("Показать связи вне выбранной даты", key=f"graph_history_{rid}")
    graph = build_graph(case, as_of=as_of, include_historical=include_historical)
    if not graph:
        st.info("В текущем наборе нет сопоставленных объектов.")
        return

    node_ids = list(graph.nodes)
    def node_label(node):
        meta = graph.nodes[node]
        return f"{meta['label']} · {NODE_LABELS.get(meta['kind'], meta['kind'])}"

    with st.expander("Фильтры и поиск связи"):
        kinds = sorted({meta.get("relation_type", meta["label"]) for _, _, meta in graph.edges(data=True)})
        visible = st.multiselect("Типы связей", kinds, default=kinds)
        graph.remove_edges_from([(u, v) for u, v, meta in graph.edges(data=True)
                                 if meta.get("relation_type", meta["label"]) not in visible])
        selected = st.selectbox("Карточка узла", node_ids, format_func=node_label)
        target = st.selectbox("Найти путь до объекта", [None, *node_ids],
                              format_func=lambda n: node_label(n) if n is not None else "Выберите объект")

    route = []
    contract_date = contract_dates.get(target) or (contract_dates.get(selected) if target is not None else None)
    if target is not None:
        if contract_date and contract_date != graph.graph["as_of"]:
            st.info(f"Для поиска связи с контрактом выберите дату его подписания {contract_date}.")
        else:
            try:
                route = nx.shortest_path(graph.to_undirected(as_view=True), selected, target)
            except nx.NetworkXNoPath:
                st.info("К выбранному объекту нет пути при текущей дате и фильтрах.")
    elif active_path:
        if all(graph.has_edge(u, v) for u, v in zip(active_path, active_path[1:])):
            route = active_path
        else:
            st.info("Полная цепочка сигнала не видна при текущей дате и фильтрах.")

    if route:
        st.markdown("**Цепочка сигнала**" if target is None else "**Найденный путь**")
        st.write(" → ".join(str(graph.nodes[node]["label"]) for node in route))
    st.write(f"Срез графа на {graph.graph['as_of']}.")
    st.caption("Точки — период связи неизвестен. Штрихи — связь вне выбранной даты.")
    st.plotly_chart(graph_plot(graph, selected, route), width="stretch", config={"displaylogo": False})
    if len(route) > 1:
        with st.expander("Основания по звеньям", expanded=True):
            for left, right in zip(route, route[1:]):
                edge = graph.get_edge_data(left, right) or graph.get_edge_data(right, left)
                st.write(edge_details(edge))

    meta = graph.nodes[selected]
    with st.container(border=True):
        st.subheader(str(meta["label"]))
        st.caption(node_label(selected))
        st.caption(f"Запись {meta['record_id']} · {meta['source']}")
        adjacent = [(dst, edge) for _, dst, edge in graph.out_edges(selected, data=True)]
        adjacent.extend((src, edge) for src, _, edge in graph.in_edges(selected, data=True))
        for node, edge in adjacent:
            st.write(f"{graph.nodes[node]['label']} · {edge_details(edge)}")
        if not adjacent:
            st.caption("Для объекта нет связей при выбранной дате и фильтрах.")


def view_run():
    runs = store.list_runs()
    if not runs:
        st.info("Проверок пока нет. Создайте первую проверку.")
        if st.button("Создать проверку", type="primary"):
            st.session_state.page = "Новая проверка"; st.rerun()
        return
    rid_list = [r["id"] for r in runs]
    if st.session_state.active_run not in rid_list:
        st.session_state.active_run = rid_list[0]
    idx = rid_list.index(st.session_state.active_run)
    rid = st.selectbox("Выберите сохранённую проверку", rid_list, index=idx,
                       format_func=lambda x: x + " · " + next((r["title"] for r in runs if r["id"] == x), ""))
    st.session_state.active_run = rid
    run = store.get_run(rid)
    signals, reviews, case = run["signals"], run["reviews"], run["dataset"]
    title("Карточка проверки", run["title"], f"{rid}  ·  Снимок от {run['created_at']} UTC  ·  Источник: {'Демо' if run['origin'] == 'demo' else 'Загруженный JSON'}")
    a,b,c,d = st.columns(4)
    a.metric("Сигналов", len(signals))
    b.metric("Высокий приоритет", sum(s["severity"] == "high" for s in signals))
    c.metric("В работе", sum(reviews[s["id"]]["status"] in ("in_review", "need_docs") for s in signals))
    d.metric("Источников с данными", sum(bool(v) for v in case["registries"].values() if isinstance(v,list)))
    integrity = store.audit_integrity(rid)
    if not integrity[0]:
        st.error("Контроль целостности не пройден: " + integrity[1])
    redirect = st.session_state.pop("run_redirect", None)
    if redirect:
        st.session_state.run_section = redirect
    section = st.radio("Раздел проверки", ("Сигналы", "Граф связей", "Источники", "Журнал", "Отчёт"),
                       horizontal=True, label_visibility="collapsed", key="run_section")

    if section == "Сигналы":
        st.caption("Приоритет определяется правилами по доступным фактам; он не является вероятностью коррупции или квалификацией нарушения.")
        if not signals:
            st.success("По включённым правилам сигналы не выявлены. Для заключения о полноте проверки требуются реальные сведения и оценка специалиста.")
        else:
            labels = ["Все", "Высокий", "Средний", "Низкий"]
            level = st.selectbox("Фильтр по приоритету", labels)
            shown = [s for s in signals if level == "Все" or SEVERITY[s["severity"]][0] == level]
            st.caption(f"Показано {len(shown)} из {len(signals)} сигналов")
            for sig in shown:
                section_signal(sig, reviews[sig["id"]], rid)

    elif section == "Граф связей":
        view_graph(case, signals, rid)

    elif section == "Источники":
        st.subheader("Состав источников и первичные сведения")
        st.dataframe(coverage(case), use_container_width=True, hide_index=True)
        with st.expander("Декларация", expanded=True):
            dataset_details(case)
        for key, title_source in [("property","Недвижимость"),("income","Доходы"),("organizations","Юридические лица"),
                                  ("contracts","Контракты"),("enforcement","Исполнительные производства")]:
            records = case["registries"].get(key, [])
            with st.expander(f"{title_source} · {len(records)} записей"):
                if records:
                    for rec in records:
                        with st.container(border=True):
                            st.write(f"{rec['id']}  ·  {rec['source']['name']}")
                            st.caption(f"Реестровая запись {rec['source']['record_id']} · Актуальность: {rec['source']['as_of']}")
                            st.json({k:v for k,v in rec.items() if k!="source"}, expanded=False)
                else:
                    st.caption("Записей нет. Это не означает, что в реальном реестре отсутствуют сведения.")

    elif section == "Журнал":
        st.subheader("Журнал решений и проверки целостности")
        st.caption("Каждое сохранение решения добавляет событие с контрольной суммой SHA-256, связанной с предыдущей записью.")
        st.success(integrity[1]) if integrity[0] else st.error(integrity[1])
        with st.expander("Контрольная сумма снимка"):
            st.code(run["payload_hash"], language=None)
        evs = store.events(rid)
        event_names = {"RUN_CREATED": "Создана проверка", "REVIEW_UPDATED": "Сохранено решение"}
        st.dataframe([{"№": e["seq"], "Когда (UTC)": e["happened_at"], "Кто":e["actor"],
                       "Событие":event_names.get(e["event_type"], e["event_type"]), "Объект":e["target"], "Контрольная сумма":e["event_hash"][:15]+"…"} for e in evs],
                     use_container_width=True, hide_index=True)
        st.warning("Проверка хеш-цепочки не заменяет квалифицированную электронную подпись, независимое хранилище или юридически значимый журнал.")

    else:
        st.subheader("Отчёт для специалиста")
        st.write("Самодостаточный HTML-отчёт можно открыть в браузере, распечатать или сохранить как PDF. Он включает основания сигналов, первичные записи и историю решений.")
        report = create_html_report(run, store.events(rid), integrity)
        st.download_button("Скачать отчёт HTML", data=report,
                           file_name=f"{rid}_report.html", mime="text/html", type="primary")
        export = {"format_version": "1.0", "run_id": rid, "created_at": run["created_at"], "case": case, "signals": signals,
                  "reviews": reviews, "events": store.events(rid), "audit": {"valid": integrity[0], "message": integrity[1]}}
        st.download_button("Скачать проверку JSON", data=json.dumps(export, ensure_ascii=False, indent=2).encode("utf-8"),
                           file_name=f"{rid}_snapshot.json", mime="application/json")
        st.info("Файлы скачиваются на компьютер пользователя. Исходные сведения и заметки остаются в локальной SQLite-базе до её удаления владельцем.")


def view_method():
    title("Методология", "Как устроена проверка", "Одинаковые исходные сведения дают одинаковые результаты анализа.")
    st.subheader("Каталог шести правил")
    for code, name, logic in RULEBOOK:
        with st.expander(f"{code} · {name}"):
            st.write(logic)
    st.subheader("Ключевые ограничения")
    st.markdown("""
- **Нет реальных интеграций.** Росреестр, ФНС/ЕГРЮЛ, ФССП, банковские данные и контракты здесь моделируются синтетическими записями. Доступ к реальным данным требует законных оснований и отдельных интеграций.
- **Нет автоматической юридической квалификации.** Сигналы означают проверочную гипотезу, а не доказательство несоблюдения законодательства.
- **Совпадение по ID, а не по ФИО.** Это позволяет избежать ряда ложных совпадений. В реальной системе потребуются согласованная идентификация и работа с неоднозначностями.
- **Ограниченное покрытие.** Пустой реестр означает отсутствие записей в загруженном наборе, а не отсутствие активов в реальности.
- **Локальное хранение без разграничения доступа.** SQLite и SHA-256 цепочка позволяют демонстрировать прослеживаемость, но не заменяют защищённый государственный контур, управление ролями, ЭП и внешнее доверенное журналирование.
- **Входные данные.** Приложение принимает структурированный JSON.
""")
    st.subheader("Формат данных")
    st.write("Загрузите JSON со структурой `id`, `year`, `title`, `description`, `declaration`, `registries`. У каждой записи реестра требуется `source` с `name`, `record_id`, `as_of`. Данные сверяются по устойчивым ID.")
    st.download_button("Скачать образец входного файла", Path(DEMO_FILES[2]).read_bytes(), file_name="schema_example.json", mime="application/json")


with st.sidebar:
    st.markdown("<div class='brand'>Контур проверки<small>Рабочее место проверяющего</small></div>", unsafe_allow_html=True)
    st.markdown("---")
    navigation = ["Обзор", "Новая проверка", "Проверка", "Методология"]
    for item in navigation:
        if st.button(item, key=f"go_{item}", use_container_width=True, type="primary" if st.session_state.page == item else "secondary"):
            st.session_state.page = item
            st.rerun()

if st.session_state.page == "Обзор":
    view_overview()
elif st.session_state.page == "Новая проверка":
    view_create()
elif st.session_state.page == "Проверка":
    view_run()
else:
    view_method()
