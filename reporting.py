"""Human-readable and machine-readable views of the same run."""
import json
from markdown_it import MarkdownIt


def display(value):
    import html
    return html.escape(str(value)).replace("|", "&#124;").replace("\n", " ")


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
             "", "## Паспорт прогона", ""]
    lines.extend(f"- **{k}** — {display(v)}" for k,v in run["manifest"].items())
    if run.get("verification"):
        rejected = sum(r["kind"] == "rejected" for r in run["verification"])
        lines += [f"- Повторная сверка с цитатами — проверено {len(run['verification'])}, отклонено {rejected}."]
    lines += ["", "## Проверка набора и очередь решений", ""]
    ordered = sorted(findings, key=lambda f: ["BLOCKER","HIGH","MEDIUM","LOW"].index(f["severity"]))
    for f in ordered:
        lines += [f"### {f['id']} · {f['severity']} · {f['status']}", "", display(f["reason"]), "",
                  f"Последствие — {display(f['impact'])}", "", f"Решение аналитика — {display(f['recommended_fix'])}", ""]
        if f["counterexample"]:
            lines += ["Сценарий — " + display(f["counterexample"]), ""]
        lines.extend("> " + s["anchor"] + " · " + display(s["quote"]) + "\n" for s in f["source_refs"])
    lines += ["", "## Карта и проверка каждого требования", "",
              "| ID | ID источника | Цитата и координаты | Формулировка | Оценка | Замечания |",
              "|---|---|---|---|---|---|"]
    for r in reqs:
        quotes = " / ".join(k+" "+display(run["sources"][k]) for k in r["refs"])
        lines.append(f"| {r['id']} | {display(r['source_id'])} | {quotes} | {display(r['summary'])} | {display(r['action'])} | {', '.join(r['findings']) or '—'} |")
    pending = run.get("unclassified_refs", [])
    if pending:
        lines += ["", "## Строки вне карты требований", "",
                  f"Проверьте {len(pending)} строк: среди них могут быть контекст, заголовки таблиц и пропущенные обязательства.", ""]
        lines.extend(f"- {ref} · {display(run['sources'][ref])}" for ref in pending)
    md = "\n".join(lines)
    if suffix == ".md":
        return md
    body = MarkdownIt("commonmark", {"html": False}).enable("table").render(md)
    return ('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>SpecGuard AI · Результат ревью</title><style>body{font:16px/1.5 system-ui;color:#162e36;max-width:1080px;margin:auto;padding:3vw}h1,h2{color:#075c54}blockquote{border-left:3px solid #47a594;padding-left:1em;margin-left:0}table{border-collapse:collapse}td,th{vertical-align:top;padding:.5em;border:1px solid #ccd9d5}h3{border-top:1px solid #ccd9d5;padding-top:.7em}li{overflow-wrap:anywhere}</style><main>'+body+'</main></html>')
