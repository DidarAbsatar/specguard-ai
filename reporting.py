"""Human-readable and machine-readable views of the same run."""
import json
import re
from markdown_it import MarkdownIt
from assessment import INDIVIDUAL, SET


def display(value):
    import html
    escaped = html.escape(str(value)).replace("|", "&#124;").replace("\n", " ")
    return re.sub(r"([\\`*_{}\[\]()#!~])", r"\\\1", escaped)


def format_report(run, suffix):
    if suffix == ".json":
        return json.dumps(run, ensure_ascii=False, indent=2)
    reqs, findings = run["requirements"], run["findings"]
    lines = ["# SpecGuard AI · Ревью требований", "", "## Решение", "",
             f"**{run['gate']}** · Требований: {len(reqs)} · Замечаний: {len(findings)} · "
             f"Блокирующих: {sum(f['severity']=='BLOCKER' for f in findings)}", "",
             {"REVIEW":"Перед передачей в разработку проверить открытые вопросы и полноту анализа.",
              "BLOCKED":"До разработки согласовать несовместимые условия, перечисленные первыми.",
              "READY":"В пределах выполненных проверок препятствий к разработке и тестированию не обнаружено."}[run["gate"]],
             ""]
    if "pending_requirements" in run:
        lines += [f"На ручную сверку формулировок — **{len(run['pending_requirements'])}**. "
                  f"Строк вне карты — **{len(run['unclassified_refs'])}**. "
                  f"Открытых оценок модели по требованиям — **{len(run.get('open_assessments', []))}**. "
                  f"После сверки с цитатами поступило {run['candidate_count']} замечаний, "
                  f"после объединения — {len(findings)}.", ""]
    ordered = sorted(findings, key=lambda f: (["BLOCKER","HIGH","MEDIUM","LOW"].index(f["severity"]),
                     f["status"] != "CONFIRMED", -len(f.get("detectors", [])), f["id"]))
    if ordered:
        top = ordered[0]
        lines += [f"**Первое решение · {top['id']}** — {display(top['recommended_fix'])}", "",
                  f"Последствие для реализации или приёмки — {display(top['impact'])}", ""]
    lines += ["## Паспорт прогона", ""]
    lines.extend(f"- **{k}** — {display(v)}" for k,v in run["manifest"].items())
    if run.get("verification"):
        rejected = sum(r["kind"] == "rejected" for r in run["verification"])
        lines += [f"- Повторная сверка с цитатами — проверено {len(run['verification'])}, отклонено {rejected}."]
    lines += ["", "## Проверка набора и очередь решений", ""]
    for f in ordered:
        lines += [f"### {f['id']} · {f['severity']} · {f['status']}", "", display(f["reason"]), "",
                  f"Последствие — {display(f['impact'])}", "", f"Решение аналитика — {display(f['recommended_fix'])}", ""]
        if f["counterexample"]:
            lines += ["Сценарий — " + display(f["counterexample"]), ""]
        if f.get("corroboration"):
            lines += ["Правило и Gemini указали на одно изменение состояния. Основания объединены в этой карточке.", ""]
        lines.extend("> " + display(s["anchor"]) + " · " + display(s["quote"]) + "\n" for s in f["source_refs"])
    if "set_criteria" in run:
        lines += ["## Критерии качества набора", "",
                  f"Профиль {display(run['criteria_profile'])}. FAIL — воспроизведённый дефект, "
                  "REVIEW — требуется решение, UNKNOWN — недостаточно данных.", "",
                  "| Критерий | Статус | Основания |", "|---|---|---|"]
        for key, result in run["set_criteria"].items():
            evidence = result["findings"] + result.get("pending_refs", [])
            lines.append(f"| {SET[key]} | {result['status']} | {', '.join(evidence) or 'Нет подтверждённого основания'} |")
        traces = [e for e in run["links"] if e["relation"] == "acceptance_reference"]
        if traces:
            lines += ["", "**Явные ссылки из критериев приёмки**", ""]
            lines.extend(f"- {e['from']} → {e['to']} · {display(run['sources'][e['to']])}" for e in traces)
    lines += ["", "## Карта и проверка каждого требования", "",
              "| ID | ID источника | Цитата и координаты | Формулировка | Оценка | Замечания |",
              "|---|---|---|---|---|---|"]
    for r in reqs:
        quotes = " / ".join(k+" "+display(run["sources"][k]) for k in r["refs"])
        issues = [INDIVIDUAL[k] + " " + item["status"] for k, item in r.get("criteria", {}).items()
                  if item["status"] != "UNKNOWN"]
        assessment = " ".join([display(r["action"]), *issues])
        lines.append(f"| {r['id']} | {display(r['source_id'])} | {quotes} | {display(r['summary'])} | {assessment} | {', '.join(r['findings']) or '—'} |")
    if "set_criteria" in run:
        lines += ["", "Индивидуальные свойства без доказательства имеют статус UNKNOWN. "
                  "MODEL_ASSESSED означает оценку Gemini по цитате. В JSON у каждого требования доступны все девять свойств, статус и основания.", ""]
    pending = run.get("unclassified_refs", [])
    if pending:
        lines += ["", "## Строки вне карты требований", "",
                  f"Проверьте {len(pending)} строк: среди них могут быть контекст, заголовки таблиц и пропущенные обязательства.", ""]
        lines.extend(f"- {ref} · {display(run['sources'][ref])}" for ref in pending)
    md = "\n".join(lines)
    if suffix == ".md":
        return md
    body = MarkdownIt("commonmark", {"html": False}).enable("table").render(md)
    sections = []
    for section in body.split("<h2>"):
        if not sections:
            sections.append(section)
            continue
        title, content = section.split("</h2>", 1)
        if title.startswith(("Паспорт", "Строки вне", "Карта и", "Критерии качества")):
            sections.append(f"<details><summary>{title}</summary>{content}</details>")
        else:
            sections.append(f"<section><h2>{title}</h2>{content}</section>")
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width, initial-scale=1"><title>SpecGuard AI · Результат ревью</title>'
            '<style>body{font:16px/1.55 "Source Sans 3","Segoe UI",sans-serif;color:#173440;background:#f4f7f8;'
            'max-width:1020px;margin:auto;padding:clamp(12px,3vw,40px)}main{background:white;padding:clamp(16px,4vw,54px);'
            'border-top:6px solid #106854}h1{line-height:1.15}h2,summary{color:#0a5848}summary{cursor:pointer;'
            'font-weight:650;padding:.8rem 0}details{border-block-start:1px solid #ccd9d5;overflow-x:auto}'
            'section:first-of-type{background:#edf6f3;padding:.1rem 1.25rem}blockquote{border-left:3px solid #78b5a6;'
            'padding-left:1em;margin-left:0}table{border-collapse:collapse;font-size:.93em}td,th{vertical-align:top;'
            'text-align:left;padding:.5em;border:1px solid #ccd9d5}th{background:#edf3f2}h3{border-top:1px solid #ccd9d5;'
            'padding-top:.9em}p,li,td{overflow-wrap:anywhere}summary:focus-visible{outline:2px solid #075c54}'
            '@media print{body,main{padding:0;background:white}h2,h3,summary{break-after:avoid}details::details-content'
            '{display:block;content-visibility:visible}}</style></head><body><main>' + "".join(sections) + '</main></body></html>')
