"""Portable printable HTML report, escaping all user-provided data."""
from __future__ import annotations
from html import escape as esc
from datetime import datetime, timezone
from core.graph import build_graph
from core.storage import STATUS_LABELS


def _e(x):
    return esc(str(x), quote=True)


def create_html_report(run: dict, events: list[dict], integrity: tuple[bool, str]) -> bytes:
    s = run["signals"]
    reviews = run["reviews"]
    sections = []
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    graph = build_graph(run["dataset"])
    registry_names = {"property": "Недвижимость", "income": "Доходы", "organizations": "Юридические лица",
                      "contracts": "Контракты", "enforcement": "Исполнительные производства"}
    sources = run["dataset"]["registries"]
    source_rows = "".join(f"<tr><td>{_e(label)}</td><td>{len(sources.get(key, []))}</td></tr>"
                          for key, label in registry_names.items())
    for sig in s:
        rev = reviews[sig["id"]]
        evidence_rows = "".join(f"<tr><td>{_e(x['source'])}</td><td>{_e(x['record_id'])}</td><td>{_e(x['as_of'])}</td><td>{_e(x['fact'])}</td></tr>" for x in sig["evidence"])
        path = sig.get("path") or sig.get("entities", [])
        nodes = " → ".join(_e(graph.nodes[n]["label"] if n in graph else n) for n in path)
        priority = {"high": "Высокий", "medium": "Средний", "low": "Низкий"}.get(sig["severity"], sig["severity"])
        sections.append(f"""
        <section class='signal'><div class='small'>{_e(sig['rule'])} · {_e(priority)} приоритет</div>
        <h2>{_e(sig['title'])}</h2><p>{_e(sig['summary'])}</p>
        <p><b>Связанные объекты:</b> {nodes}</p>
        <p><b>Основание:</b> {_e(sig['reasoning'])}</p><p><b>Рекомендация:</b> {_e(sig['next_step'])}</p>
        <p><b>Статус:</b> {_e(STATUS_LABELS.get(rev['status'], rev['status']))}</p>
        <p><b>Проверяющий:</b> {_e(rev['reviewer'])} · <b>Решение обновлено:</b> {_e(rev['updated_at'])} UTC</p>
        <p><b>Комментарий:</b> {_e(rev['note'] or 'Не указан')}</p>
        <table><thead><tr><th>Источник</th><th>ID записи</th><th>По состоянию на</th><th>Факт</th></tr></thead><tbody>{evidence_rows}</tbody></table></section>""")
    event_names = {"RUN_CREATED": "Создана проверка", "REVIEW_UPDATED": "Сохранено решение"}
    event_rows = "".join(f"<tr><td>{_e(x['happened_at'])}</td><td>{_e(x['actor'])}</td><td>{_e(event_names.get(x['event_type'], x['event_type']))}</td><td>{_e(x['target'])}</td><td><code>{_e(x['event_hash'][:16])}…</code></td></tr>" for x in events)
    pending = sum(review["status"] not in ("data_confirmed", "not_confirmed") for review in reviews.values())
    html = f"""<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Контур проверки · {_e(run['id'])}</title>
<style>body{{font:14px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;color:#14283e;max-width:980px;margin:45px auto;padding:0 30px}}header{{border-bottom:3px solid #177b84;padding-bottom:24px;margin-bottom:24px}}h1{{font-size:32px;margin:0}}h2{{font-size:19px}}.small{{color:#5e7187;font-size:11px;letter-spacing:1.3px;font-weight:700}}.signal{{border:1px solid #d6e1e8;border-radius:10px;padding:20px;margin:18px 0;page-break-inside:avoid}}table{{width:100%;border-collapse:collapse;margin:14px 0;font-size:12px}}td,th{{text-align:left;border-bottom:1px solid #dbe3e9;padding:9px;vertical-align:top;word-break:break-word}}th{{background:#f0f5f8}}code{{overflow-wrap:anywhere;word-break:break-word}}.signal{{min-width:0}}
@media(max-width:620px){{body{{padding:0 14px;margin:18px auto}}header{{padding-bottom:14px}}h1{{font-size:25px}}.signal{{padding:13px}}table{{display:block;max-width:100%;overflow-x:auto;white-space:normal}}td,th{{font-size:11px;overflow-wrap:anywhere;word-break:break-word}}}}
.notice{{border-left:4px solid #177b84;background:#eff7f8;padding:14px}}@media print{{body{{margin:0}}.signal{{break-inside:avoid}}}}</style>
</head><body><header><div class='small'>КОНТУР ПРОВЕРКИ / АНАЛИТИЧЕСКИЙ ОТЧЁТ</div><h1>Результаты аналитической проверки</h1>
<p><b>ID:</b> {_e(run['id'])} · <b>Создано (UTC):</b> {_e(run['created_at'])}<br><b>Отчёт сформирован (UTC):</b> {_e(generated_at)}<br><b>Сценарий:</b> {_e(run['title'])} · <b>Сигналов:</b> {len(s)}</p>
<p><b>SHA-256 исходных данных:</b><br><code>{_e(run['payload_hash'])}</code></p></header>
<p class='notice'><b>Ограничение.</b> Все встроенные примеры синтетические. Система не подключена к реальным государственным реестрам и не выносит заключения о правонарушениях. Отчёт не является процессуальным документом.</p>
<h2>Источники и охват</h2><table><thead><tr><th>Источник</th><th>Записей</th></tr></thead><tbody>{source_rows}</tbody></table>
<p>Наличие записей не означает полноту реального источника. Данные представлены в составе загруженного набора.</p>
<h2>Аналитические сигналы</h2>{''.join(sections) if sections else '<p>По включённым правилам сигналы не обнаружены. Это не гарантия достоверности.</p>'}
<h2>Итог рассмотрения</h2><p>Всего сигналов: {len(s)}. Завершено рассмотрение: {len(s) - pending}. Требуют рассмотрения: {pending}.</p>
<h2>История рассмотрения</h2><table><thead><tr><th>Дата и время (UTC)</th><th>Субъект</th><th>Событие</th><th>Объект</th><th>SHA-256 события</th></tr></thead><tbody>{event_rows}</tbody></table>
<p><b>Проверка целостности журнала:</b> {_e(integrity[1])}. <b>Результат:</b> {'OK' if integrity[0] else 'ОШИБКА'}.</p>
<p class='small'>Журнал защищён контрольными суммами только внутри локальной базы данных. Это не квалифицированная электронная подпись и не независимое доверенное хранение.</p></body></html>"""
    return html.encode("utf-8")
