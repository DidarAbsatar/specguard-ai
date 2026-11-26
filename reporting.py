"""Human-readable and machine-readable views of the same run."""
import json
import re
from decimal import Decimal
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
             f"Блокирующих: {sum(f['severity']=='BLOCKER' for f in findings)}", ""]
    decision = run.get("decision", {})
    if decision:
        lines += [f"**Разработка** — {decision['development']}", "",
                  f"**Тестирование и приёмка** — {decision['testing']}", ""]
    else:
        lines += [{"REVIEW":"Перед передачей в разработку проверить открытые вопросы и полноту анализа.",
              "BLOCKED":"До разработки согласовать несовместимые условия, перечисленные первыми.",
              "READY":"В пределах выполненных проверок препятствий к разработке и тестированию не обнаружено."}[run["gate"]],
             ""]
    if "pending_requirements" in run:
        lines += [f"На ручную сверку формулировок — **{len(run['pending_requirements'])}**. "
                  f"Строк вне карты — **{len(run['unclassified_refs'])}**. "
                  f"Открытых оценок модели по требованиям — **{len(run.get('open_assessments', []))}**. "
                  f"До объединения было {run['candidate_count']} замечаний, "
                  f"после объединения — {len(findings)}.", ""]
    if run.get("review_controls") or run.get("document_gaps"):
        controls = run["review_controls"]
        unmarked = sum(c["state"] == "UNMARKED" for c in controls)
        lines += [f"Проверок готовности документа — **{len(controls)}**, из них без заполненных "
                  f"или однозначно выбранных отметок — **{unmarked}**. "
                  f"Открытых вопросов по реквизитам — **{len(run['document_gaps'])}**.", ""]
    by_id = {f["id"]: f for f in findings}
    ordered = ([by_id[i] for i in decision["order"]] if decision else
               sorted(findings, key=lambda f: (["BLOCKER","HIGH","MEDIUM","LOW"].index(f["severity"]),
                      f["status"] != "CONFIRMED", -len(f.get("detectors", [])), f["id"])))
    if ordered:
        top = ordered[0]
        lines += [f"**Первое решение · {top['id']}** — {display(top['recommended_fix'])}", "",
                  f"Последствие для реализации или приёмки — {display(top['impact'])}", ""]
        if decision:
            first = decision["first"]
            lines += [f"Кому адресовать — {first['owner']}. {first['reason']}", "",
                      "Основания — " + ", ".join(first["refs"]) + ".", ""]
            if first["scenario"]:
                lines += ["Сценарий для согласования с QA — " + display(first["scenario"]), ""]
    elif decision.get("next_step"):
        lines += [decision["next_step"], "", ", ".join(decision["pending_refs"]), ""]
    lines += ["## Паспорт прогона", ""]
    lines.extend(f"- **{k}** — {display(v) if v is not None else 'не подтверждён'}" for k,v in run["manifest"].items())
    for call in run.get("llm_calls", []):
        stage = {"analysis": "анализ", "verification": "сверка"}[call["stage"]]
        tokens = call.get("usage", {}).get("totalTokenCount", "нет данных")
        status = "получен JSON" if call["status"] == "received_json" else display(call.get("error", "ошибка"))
        provider = call.get("provider", "gemini")
        lines.append(f"- Запрос {display(provider)} · {stage} · {status} · {call['elapsed_ms']} мс · токены по данным провайдера — {tokens}.")
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
            lines += ["Повторные обнаружения объединены. Источники: " + ", ".join(f["detectors"]) + ".", ""]
        lines.extend("> " + display(s["anchor"]) + " · " + display(s["quote"]) + "\n" for s in f["source_refs"])
        for k in f.get("context_refs", []):
            lines += [f"Контекст раздела · {display(k)} · {display(run['sources'][k])}", ""]
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
                  "MODEL_ASSESSED означает оценку модели по цитате. В JSON у каждого требования доступны все девять свойств, статус и основания.", ""]
    if run.get("review_controls"):
        lines += ["## Карта проверок готовности документа", "",
                  "В таблице сохранены условия проверки и отметки из исходника. Выбранное «Да» означает заявление автора. "
                  "Для подтверждения результата нужны доказательства выполнения.", "",
                  "| ID | Источник | Критерий | Поля исходника | Итог по отметкам | Примечания и условия |",
                  "|---|---|---|---|---|---|"]
        labels = {"UNMARKED": "Отметка не выбрана", "NEGATIVE": "Указано «Нет»", "DECLARED": "Отметка автора",
                  "NOT_APPLICABLE": "Указана неприменимость", "REVIEW": "Нужна интерпретация"}
        for c in run["review_controls"]:
            marks = " · ".join(display(v["column"]) + " — " + (display(v["text"]) or "пусто") for v in c["marks"])
            notes = " · ".join(display(v["column"]) + " — " + display(v["text"]) for v in c["notes"])
            lines.append(f"| {c['id']} | {c['ref']} | {display(c['criterion'])} | {marks} | {labels[c['state']]} | {notes or '—'} |")
    if run.get("document_gaps"):
        lines += ["", "## Открытые вопросы по реквизитам", ""]
        for ref, question in run["document_gaps"].items():
            lines += [f"- {ref} · {display(run['sources'][ref])} — {display(question)}"]
    pending = run.get("unclassified_refs", [])
    if pending:
        lines += ["", "## Строки вне карты требований", "",
                  f"Проверьте {len(pending)} строк: среди них могут быть контекст, заголовки таблиц и пропущенные обязательства.", ""]
        lines.extend(f"- {ref} · {display(run['sources'][ref])}" for ref in pending)
    return render_markdown("\n".join(lines), suffix, "Результат ревью")


def format_comparison(run, suffix):
    if suffix == ".json":
        return json.dumps(run, ensure_ascii=False, indent=2)
    counts = run["counts"]
    labels = {"FIX_CONFIRMED": "Исправление доказано", "PERSISTS": "Замечание сохранилось",
              "CHECK": "Устранение требует сверки", "NEW_OBSERVATION": "Обнаружено без пары в прошлой редакции"}
    lines = ["# SpecGuard AI · Сравнение редакций", "", "## Итог проверки правил", "",
             f"Замечаний в исходной редакции — **{run['before_count']}**, в новой — **{run['after_count']}**.", "",
             f"Доказано исправлений — **{counts['FIX_CONFIRMED']}**. Сохранилось — **{counts['PERSISTS']}**. "
             f"На ручную сверку — **{counts['CHECK']}**. Без пары в прошлой редакции — **{counts['NEW_OBSERVATION']}**.", "",
             "Обе редакции проверены одним набором правил. Для полной смысловой оценки новой редакции предусмотрен отдельный прогон Gemini.", ""]
    for e in sorted(run["changes"], key=lambda entry: list(labels).index(entry["status"])):
        ids = " → ".join(i for i in (e["previous_id"], e["current_id"]) if i)
        lines += [f"### {labels[e['status']]} · {ids}", "", display(e["reason"]), "", display(e["impact"]), ""]
        for key, label in (("before", "Было"), ("after", "Стало")):
            for s in e[key]:
                lines += [f"> **{label} · {display(s['anchor'])}** {display(s['quote'])}", ""]
        if e.get("proof", {}).get("kind") == "feasible_interval":
            p = e["proof"]
            witness = Decimal(str(p["witness"]))
            sample = f"{witness:,f}".replace(",", " ") + " " + display(p["unit"])
            if p["unit"] == "секунд" and 0 < witness < 10**27 and witness % 3600 == 0:
                sample = f"{witness // 3600} ч ({sample})"
            lines += [f"**Проверочное значение для QA — {sample}.** "
                      f"Оно входит в новый интервал [{p['after_min']}, {p['after_max']}].", ""]
        if e.get("proof", {}).get("kind") == "calendar_alignment":
            p = e["proof"]
            months = ("", "январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август",
                      "сентябрь", "октябрь", "ноябрь", "декабрь")
            lines += [f"**Ожидаемый период для QA — {months[p['event_month']]}.** При тех же условиях "
                      f"прежний пример указывал {months[p['before_expected']]}. Новый пример совпадает с правилом учёта.", ""]
        lines += [display(e["action"]), ""]
    lines += ["## Паспорт сравнения", "", f"- Версия — {display(run['version'])} · сборка {display(run['build'])}."]
    for label, doc in (("Исходная редакция", run["before"]), ("Новая редакция", run["after"])):
        lines.append(f"- {label} — {display(doc['name'])} · SHA-256 `{doc['sha256']}`.")
    return render_markdown("\n".join(lines), suffix, "Сравнение редакций")


def render_markdown(md, suffix, title):
    if suffix == ".md":
        return md
    body = MarkdownIt("commonmark", {"html": False}).enable("table").render(md)
    sections = []
    for section in body.split("<h2>"):
        if not sections:
            sections.append(section)
            continue
        heading, content = section.split("</h2>", 1)
        if heading.startswith(("Паспорт", "Строки вне", "Карта и", "Критерии качества")):
            sections.append(f"<details><summary>{heading}</summary>{content}</details>")
        else:
            sections.append(f"<section><h2>{heading}</h2>{content}</section>")
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width, initial-scale=1"><title>SpecGuard AI · {title}</title>'
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
