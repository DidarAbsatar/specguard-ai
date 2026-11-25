"""Evidence-linked review of normative statements and their acceptance examples."""
import re
from collections import defaultdict
from itertools import combinations

IDENT = re.compile(r"^(?:[-*\s]|\*\*)*([A-ZА-ЯЁ]{1,12}-\d+)\b[.:]?\**\s*", re.I)
BOUND = re.compile(r"^(.+?)\s+(?:долж(?:ен|на|но|ны)\s+(?:быть|составлять)\s+)?(не менее|не более|минимум|максимум)\s+(\d+)\s+([а-яёa-z%₸]+)[.!]?$", re.I)
NORM = re.compile(r"долж|обязан|запрещ|необходим|разреш|требуется|shall|must", re.I)
TIME_SCALE = {word: seconds for seconds, forms in (
    (1, "с секунд секунда секунды секунду"),
    (60, "мин минут минута минуты минуту"),
    (3600, "ч часов час часа"),
    (86400, "суток сутки дня дней день"),
) for word in forms.split()}
HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
CONTRACT_FIELD = re.compile(r"^\|\s*[*`]*(?:authorization|авторизация|http method|rest type|content-type|request url)[*`]*\s*\|", re.I)
VAGUE = re.compile(r"\b(?:быстро|удобно|своевременно|оперативно)\b", re.I)
PENDING = "Смысл и полнота требуют ревью."


def section_paths(blocks):
    """Keep the entire heading ancestry; code examples have no normative scope."""
    path, result, fence = [], {}, None
    for ref, text in blocks.items():
        marker = re.match(r"^(`{3,}|~{3,})", text)
        if marker and fence is None:
            fence = marker[1]
            continue
        if fence:
            if text.startswith(fence) and not text.strip(fence[0]).strip():
                fence = None
            continue
        heading = HEADING.match(text)
        if heading:
            level = len(heading[1])
            path = [entry for entry in path if entry[0] < level]
            path.append((level, heading[2], ref))
            continue
        result[ref] = tuple(path)
    return result


def inventory(blocks, paths=None, model_refs=()):
    paths = section_paths(blocks) if paths is None else paths
    table, reqs = False, []
    for ref, text in blocks.items():
        if ref not in paths:
            table = False
            continue
        section = paths[ref][-1][1] if paths[ref] else ""
        ident = IDENT.match(text)
        if text.startswith("|"):
            if not table:
                table = True
                if not CONTRACT_FIELD.match(text):
                    continue
        else:
            table = False
        if re.search("ревью требований|согласующих|общие сведения", section, re.I):
            continue
        normative = re.search("требования|правила|логика работы|параметры запроса|query-параметры|ответ|статусы|приемки", section, re.I)
        if not (ident or normative or CONTRACT_FIELD.match(text) or NORM.search(text)
                or BOUND.match(text) or ref in model_refs):
            continue
        if text.startswith(("```", "{")) or text.lower() in ("или", "да / нет"):
            continue
        clean = text[ident.end():] if ident else re.sub(r"^\d+[.)]\s+", "", text)
        sentences = [clean] if text.startswith("|") else re.split(r"(?<=[.!?;])\s+(?=[А-ЯЁA-Zа-яёa-z])", clean)
        for sentence in sentences:
            if not sentence.strip() or re.fullmatch(r"\d+[.)]", sentence):
                continue
            reqs.append(dict(source_id=ident[1] if ident else "—", refs=[ref], summary=sentence,
                             section=section, action=PENDING))
    return reqs


def reconcile(blocks, paths, rows):
    """Keep each source clause until model excerpts account for its text."""
    by_ref = defaultdict(list)
    for row in rows:
        if row["kind"] == "requirement" and len(row["refs"]) == 1:
            by_ref[row["refs"][0]].append(row)
    reqs = inventory(blocks, paths, by_ref)
    for req in reqs:
        ref, = req["refs"]
        clause = req["summary"]
        covered = set()
        actions = []
        assessments = []
        for row in by_ref[ref]:
            excerpt = row["summary"].strip().strip(" .;")
            if not excerpt or clause.count(excerpt) != 1:
                continue
            start = clause.index(excerpt)
            covered.update(range(start, start + len(excerpt)))
            if row["action"].strip():
                actions.append(row["action"].strip())
            if row.get("assessment"):
                assessments.append({k: row[k] for k in ("summary", "criterion", "assessment", "action")})
        # Punctuation and Markdown syntax do not constitute a separate obligation.
        req["coverage"] = "reviewed" if covered and all(
            i in covered for i, ch in enumerate(clause) if ch.isalnum()) else "pending"
        if req["coverage"] == "reviewed" and actions:
            req["action"] = " ".join(dict.fromkeys(actions))
        req["model_assessments"] = assessments
    return reqs


def analyze(blocks, rows, complete):
    paths = section_paths(blocks)
    reqs = reconcile(blocks, paths, rows)
    findings = []

    def add(category, severity, refs, reason, impact, fix, scenario=None, confirmed=False):
        evidence = [dict(anchor=k, quote=blocks[k]) for k in dict.fromkeys(refs)]
        findings.append(dict(id=f"F-{len(findings)+1:03}", category=category, severity=severity,
            source_refs=evidence, observed_text=" / ".join(v["quote"] for v in evidence),
            reason=reason, impact=impact, recommended_fix=fix, counterexample=scenario,
            confidence="высокая" if confirmed else "требует проверки", needs_human_decision=True,
            status="CONFIRMED" if confirmed else "REVIEW", detectors=["rule"], core_refs=list(dict.fromkeys(refs))))
        return findings[-1]

    bounds = {}
    for ref in paths:
        raw = blocks[ref]
        text = IDENT.sub("", raw).strip()
        if re.search(r"\b(TBD|TBS|TBR)\b", text):
            add("placeholder", "MEDIUM", [ref], "Присутствует маркер открытого решения.",
                "Ожидаемый результат требует уточнения.", "Заполнить значение или объяснить маркер.")
        match = BOUND.fullmatch(text) if ref in paths else None
        if match:
            subject, op, value, unit = match.groups()
            unit = unit.casefold()
            scale = TIME_SCALE.get(unit)
            if re.fullmatch(r"байт(?:а|ов|ы)?", unit):
                unit = "байт"
            bounds.setdefault((paths[ref], subject.casefold(), "секунд" if scale else unit), []).append(
                (op.lower() in {"не менее", "минимум"}, int(value) * (scale or 1), ref))
    for (_, subject, unit), entries in bounds.items():
        for a, b in combinations(entries, 2):
            lower, upper = sorted((a,b), reverse=True)
            if lower[0] and not upper[0] and lower[1] > upper[1]:
                add("bounds", "BLOCKER", [lower[2], upper[2]], "В одном разделе заданы несовместимые границы.",
                    "Нельзя выбрать значение, удовлетворяющее обоим условиям.", "Согласовать область действия и диапазон.",
                    f"{subject} = {upper[1]} {unit} нарушает минимум {lower[1]}. Любое большее значение нарушает максимум.", True)
    # A contract can have multiple endpoints. Limit matching to the same API section.
    method = None
    for ref, raw in blocks.items():
        if raw.startswith("# ") or raw.startswith("## "):
            method = None
        if ref not in paths:
            continue
        cells = [c.strip(" *`").casefold() for c in raw.strip("|").split("|")]
        if len(cells) == 2 and cells[0] in {"метод", "rest type", "http method", "метод http"}:
            method = ref if cells[1] == "get" else None
        if method and re.match(r"^(?:\d+[.)]\s*)?(?:заменить|удалить|сохранить|обновить)\s", raw, re.I):
            add("http", "HIGH", [method, ref], "Контракт GET содержит операцию изменения состояния.",
                "Клиент может повторить запрос как безопасное чтение.", "Согласовать метод и эффект повторного запроса.",
                "Клиент повторяет тот же GET. Должно ли измениться сохранённое состояние?")
    months = ("январ","феврал","март","апрел","ма[йяе]","июн","июл","август","сентябр","октябр","ноябр","декабр")
    calendar = []
    for ref in paths:
        raw = blocks[ref]
        rule = re.search(r"месяц (?:определяется|рассчитывается) по дате (?:совершения )?([а-яё]{4,})", raw, re.I)
        if rule:
            stem = re.sub(r"[ыияа]$", "", rule[1].casefold())
            calendar.append((ref, stem))
    # A unique allocation rule and a three-column example with explicit dates.
    if len(calendar) == 1:
        for k in paths:
            line = blocks[k]
            cells = [c.strip().lower() for c in line.strip("|").split("|")]
            if len(cells) != 3 or not re.search(r"\b" + calendar[0][1], cells[0]):
                continue
            purchase = re.search(r"\b\d{1,2}\s+([а-яё]+)", cells[0])
            posted = re.search(r"\b\d{1,2}\s+([а-яё]+)", cells[1])
            if not purchase or not posted:
                continue
            for month in months:
                if (re.match(month, posted[1]) and not re.match(month, purchase[1])
                        and re.match(month, cells[2]) and re.search("вырос|увелич", cells[2])):
                    add("calendar", "HIGH", [calendar[0][0], k],
                        "Пример относит изменение счётчика к месяцу второго события. Правило указывает на первое.",
                        "QA и разработчик получат разные ожидаемые суммы за один период.",
                        "Согласовать дату учёта и исправить правило или критерий приёмки.",
                        " → ".join(c.strip() for c in line.strip("|").split("|")))
    # Join a periodic upper bound to an independent trigger for the same effect.
    caps = []
    triggers = []
    for ref in paths:
        raw = blocks[ref]
        limit = re.search(r"(?:максимум|не более)\s+(?:один|одна|одно|1)\s+(?:тако[йея]\s+)?([\w-]+)\s+(?:за|в)\s+([^.;]+)", raw, re.I)
        trigger = re.search(r"(?:вызывает|инициирует)\s+([\w-]+)\s+независимо от\s+([^.;]+)", raw, re.I)
        if limit:
            caps.append((ref, limit[1].lower(), limit[2]))
        if trigger:
            triggers.append((ref, trigger[1].lower(), trigger[2]))
    for bound, effect, period in caps:
        for repeat, action, history in triggers:
            if effect == action and bound != repeat:
                add("state", "HIGH", [bound, repeat],
                    f"Для «{effect}» заданы предел за период и триггер независимо от {history}.",
                    "Две реализации могут выбрать разные результаты при повторном срабатывании.",
                    "Какое правило имеет приоритет при совпадении условий?",
                    f"Допущение: оба правила применимы к одному объекту. Период: {period}. "
                    f"Первое событие уже вызвало {effect}. До конца периода вновь выполняется условие триггера.")
    for r in reqs:
        if VAGUE.search(r["summary"]):
            add("verifiability", "MEDIUM", r["refs"], "Качественная характеристика требует критерия проверки.",
                "Приёмщики могут по-разному оценить результат.", "Указать метрику или ссылку на критерий.")
    model_rows = [r for r in rows if r["kind"] in {"issue", "question"}]
    candidate_count = len(findings) + len(model_rows)
    for r in model_rows:
        category = r.get("category", "semantic")
        # One mutation through GET is one defect even if the model cites extra context.
        # Distinct failure modes on the same lines must remain separate.
        claim = r["summary"].casefold()
        same_http_effect = (re.search(r"\bget\b", claim) and
                            re.search(r"изменени|сохран|запис|обнов|удал|мутаци|modif|mutat|writ|delet", claim))
        matches = [f for f in findings if f["category"] == "http" and "rule" in f["detectors"]
                   and set(f["core_refs"]) <= set(r["refs"])] if same_http_effect else []
        if len(matches) == 1:
            f = matches[0]
            f.setdefault("corroboration", []).append(dict(r))
            if "gemini" not in f["detectors"]:
                f["detectors"].append("gemini")
            known = {s["anchor"] for s in f["source_refs"]}
            f["source_refs"].extend({"anchor": k, "quote": blocks[k]} for k in dict.fromkeys(r["refs"]) if k not in known)
            f["observed_text"] = " / ".join(s["quote"] for s in f["source_refs"])
            continue
        severity = r.get("severity", "HIGH" if r["kind"] == "issue" else "MEDIUM")
        f = add(category, severity, r["refs"], r["summary"], r["impact"], r["action"], r["scenario"])
        f.update(detectors=["gemini"], criterion=r.get("criterion"))
    for n, r in enumerate(reqs, 1):
        r["id"] = f"R-{n:03}"
        r["findings"] = [f["id"] for f in findings if set(f["core_refs"]).intersection(r["refs"])]
        if r["findings"]:
            r["action"] = "Разобрать связанные замечания " + ", ".join(r["findings"]) + "."
        elif r["coverage"] == "pending":
            r["action"] = "Сверить полную формулировку с владельцем: смысловая проверка фрагмента не подтверждена."
    blockers = [f for f in findings if f["severity"] == "BLOCKER"]
    mapped = {ref for r in reqs for ref in r["refs"]}
    # Unclassified prose may contain an implicit obligation. Leave it visible to reviewers.
    unclassified = [ref for ref in paths if ref not in mapped]
    pending = [r for r in reqs if r["coverage"] == "pending"]
    open_assessments = [r["id"] for r in reqs if any(a["assessment"] != "grounded" for a in r["model_assessments"])]
    gate = "BLOCKED" if blockers else "REVIEW" if findings or not complete or not reqs or unclassified or pending or open_assessments else "READY"
    links = [{"from":r["id"], "to":k, "relation":"source"} for r in reqs for k in r["refs"]]
    links.extend({"from":r["id"], "to":f, "relation":"finding"} for r in reqs for f in r["findings"])
    from assessment import assess, acceptance_links
    links.extend(acceptance_links(reqs, blocks, paths))
    criteria = assess(reqs, findings, unclassified + [r["refs"][0] for r in pending])
    return dict(requirements=reqs, findings=findings, gate=gate, links=links,
                candidate_count=candidate_count, pending_requirements=[r["id"] for r in pending],
                open_assessments=open_assessments,
                set_criteria=criteria, criteria_profile="29148:2018 / SpecGuard 1",
                unclassified_refs=unclassified)
