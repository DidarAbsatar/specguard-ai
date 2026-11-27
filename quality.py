"""Evidence-linked review of normative statements and their acceptance examples."""
import re
from calendar import monthrange
from collections import defaultdict
from decimal import Decimal, localcontext
from itertools import combinations
from typing import NamedTuple
from review_tables import document_roles

IDENT = re.compile(r"^(?:[-*\s]|\*\*)*([A-ZА-ЯЁ]{1,12}-\d+)\b[.:]?\**\s*", re.I)
BOUND = re.compile(r"^(.+?)\s+(?:долж(?:ен|на|но|ны)\s+(?:быть|составлять)\s+)?(не менее|не более|минимум|максимум)\s+([+-]?\d{1,128}(?:[.,]\d{1,128})?)\s+([а-яёa-z%₸]+)[.!]?$", re.I)
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
DEFERRED = re.compile(r"(?:заполняется|заполняются|будет заполнен[ао]?|будут заполнены)\s+"
                      r"(?:позже|позднее|отдельно|аналитик(?:ом|ами)|тестировщик(?:ом|ами)|"
                      r"разработчик(?:ом|ами)|владельц(?:ем|ами))[.]?", re.I)
PENDING = "Смысл и полнота требуют ревью."
MONTHS = ("январ", "феврал", "март", "апрел", "ма[йяе]", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр")


class Bound(NamedTuple):
    subject: str
    unit: str
    minimum: bool
    value: Decimal


def json_number(value):
    """Keep exact decimal witnesses even for consumers without decimal JSON support."""
    return int(value) if value == value.to_integral_value() else format(value, "f")


def parse_bound(raw):
    match = BOUND.fullmatch(IDENT.sub("", raw).strip())
    if not match:
        return None
    subject, op, value, unit = match.groups()
    unit = unit.casefold()
    scale = TIME_SCALE.get(unit)
    if scale:
        unit = "секунд"
    elif re.fullmatch(r"байт(?:а|ов|ы)?", unit):
        unit = "байт"
    with localcontext() as ctx:
        ctx.prec = len(value) + 6
        converted = Decimal(value.replace(",", ".")) * (scale or 1)
    return Bound(subject.casefold(), unit, op.casefold() in {"не менее", "минимум"}, converted)


def calendar_checks(blocks, paths):
    def month(word):
        return next((n for n, pattern in enumerate(MONTHS, 1) if re.match(pattern, word)), None)

    def date_month(cell):
        match = re.search(r"\b(\d{1,2})\s+([а-яё]+)", cell)
        if match:
            number = month(match[2])
            if number and 1 <= int(match[1]) <= monthrange(2000, number)[1]:
                return number
        return None

    rules = defaultdict(list)
    for ref, path in paths.items():
        match = re.search(r"месяц (?:определяется|рассчитывается) по дате (?:совершения )?([а-яё]{4,})", blocks[ref], re.I)
        if match:
            rules[path[:1]].append((ref, re.sub(r"[ыияа]$", "", match[1].casefold())))
    checks = []
    for ref, path in paths.items():
        candidates = rules.get(path[:1], [])
        if len(candidates) != 1 or not blocks[ref].startswith("|"):
            continue
        rule, stem = candidates[0]
        cells = [v.strip().casefold() for v in blocks[ref].strip("|").split("|")]
        if len(cells) != 3 or not re.search(r"\b" + stem, cells[0]):
            continue
        if not re.search("вырос|увелич", cells[2]) or re.search(r"\bне\b", cells[2]):
            continue
        event, posting, expected = date_month(cells[0]), date_month(cells[1]), month(cells[2])
        if event and posting and expected and event != posting:
            checks.append(dict(rule=rule, example=ref, event_month=event, posting_month=posting, expected_month=expected))
    return checks


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


def inventory(blocks, paths=None, model_refs=(), excluded=()):
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
                if not (CONTRACT_FIELD.match(text) or ref in model_refs or NORM.search(text)):
                    continue
        else:
            table = False
        if ref in excluded:
            continue
        normative = re.search("требования|правила|логика работы|параметры запроса|query-параметры|ответ|статусы|приемки", section, re.I)
        if not (ident or normative or CONTRACT_FIELD.match(text) or NORM.search(text) or DEFERRED.fullmatch(text)
                or BOUND.match(text) or ref in model_refs):
            continue
        if text.startswith(("```", "{")) or text.lower() in ("или", "да / нет"):
            continue
        clean = text[ident.end():] if ident else re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", text)
        sentences = [clean] if text.startswith("|") else re.split(r"(?<=[.!?;])\s+(?=[А-ЯЁA-Zа-яёa-z])", clean)
        for sentence in sentences:
            if not sentence.strip() or re.fullmatch(r"\d+[.)]", sentence):
                continue
            reqs.append(dict(source_id=ident[1] if ident else "—", refs=[ref], summary=sentence,
                             section=section, action=PENDING))
    return reqs


def reconcile(blocks, paths, rows, excluded=()):
    """Keep each source clause until model excerpts account for its text."""
    by_ref = defaultdict(list)
    for row in rows:
        if row["kind"] == "requirement" and len(row["refs"]) == 1:
            by_ref[row["refs"][0]].append(row)
    reqs = inventory(blocks, paths, by_ref, excluded)
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
        # Require operators, signs, units and decimal separators as well as words.
        req["coverage"] = "reviewed" if covered and all(
            i in covered for i, ch in enumerate(clause.rstrip(" .;")) if not ch.isspace()) else "pending"
        if req["coverage"] == "reviewed" and actions:
            req["action"] = " ".join(dict.fromkeys(actions))
        req["model_assessments"] = assessments
    return reqs


def analyze(blocks, rows, complete, *, header_refs=()):
    paths = section_paths(blocks)
    controls, document_gaps, headers = document_roles(blocks, paths, header_refs)
    supporting = controls.keys() | document_gaps.keys() | headers
    product_paths = {ref: path for ref, path in paths.items() if ref not in supporting}
    reqs = reconcile(blocks, paths, rows, supporting)
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
    for ref in product_paths:
        raw = blocks[ref]
        text = IDENT.sub("", raw).strip()
        section = paths[ref][-1][1] if paths[ref] else ""
        if re.search(r"\b(TBD|TBS|TBR)\b", text):
            add("placeholder", "MEDIUM", [ref], "Присутствует маркер открытого решения.",
                "Ожидаемый результат требует уточнения.", "Заполнить значение или объяснить маркер.")
        elif section and DEFERRED.fullmatch(text):
            add("placeholder", "MEDIUM", [ref], f"В разделе «{section}» указано лишь будущее заполнение.",
                f"Содержание раздела «{section}» нельзя использовать при согласовании текущей версии.",
                f"Что должно появиться в разделе «{section}» до передачи документа? Если раздел неприменим, укажите основание.")
        elif CONTRACT_FIELD.match(raw):
            missing = re.findall(r"(?<!\w)([\w-]+):\s*[—–-](?=\s*(?:[|.;]|$))", raw)
            if missing:
                labels = ", ".join(missing)
                add("placeholder", "MEDIUM", [ref], f"В параметре контракта отсутствует значение для «{labels}».",
                    f"Для «{labels}» исполнитель не может проверить конфигурацию по документу.",
                    f"Какое значение применимо для «{labels}» или где находится его согласованный источник?")
        bound = parse_bound(raw)
        if bound:
            bounds.setdefault((paths[ref], bound.subject, bound.unit), []).append((bound.minimum, bound.value, ref))
    for (_, subject, unit), entries in bounds.items():
        for a, b in combinations(entries, 2):
            lower, upper = sorted((a,b), reverse=True)
            if lower[0] and not upper[0] and lower[1] > upper[1]:
                finding = add("bounds", "BLOCKER", [lower[2], upper[2]], "В одном разделе заданы несовместимые границы.",
                    "Нельзя выбрать значение, удовлетворяющее обоим условиям.", "Согласовать область действия и диапазон.",
                    f"{subject} = {upper[1]} {unit} нарушает минимум {lower[1]}. Любое большее значение нарушает максимум.", True)
                finding["proof"] = dict(kind="empty_interval", subject=subject, unit=unit,
                                        minimum=json_number(lower[1]), maximum=json_number(upper[1]))
    # A contract can have multiple endpoints. Limit matching to the same API section.
    method = None
    for ref, raw in blocks.items():
        if ref not in product_paths:
            continue
        path = paths[ref]
        if method:
            method_ref, scope = method
            if path[:len(scope)] != scope or (not scope and path != paths[method_ref]):
                method = None
        cells = [c.strip(" *`").casefold() for c in raw.strip("|").split("|")]
        if len(cells) == 2 and cells[0] in {"метод", "rest type", "http method", "метод http"}:
            scope = path
            if path and re.fullmatch("общие параметры|метаданные|metadata", path[-1][1], re.I):
                scope = path[:-1]
            method = (ref, scope) if cells[1] == "get" else None
        if method and re.match(r"^(?:\d+[.)]\s*)?(?:заменить|удалить|сохранить|обновить)\s", raw, re.I):
            add("http", "HIGH", [method[0], ref], "Контракт GET содержит операцию изменения состояния.",
                "Клиент может повторить запрос как безопасное чтение.", "Согласовать метод и эффект повторного запроса.",
                "Клиент повторяет тот же GET. Должно ли измениться сохранённое состояние?")
    from contract_rules import contract_findings
    for severity, refs, reason, impact, fix, scenario in contract_findings(blocks):
        add("http", severity, refs, reason, impact, fix, scenario)
    from contract_rules import unit_findings
    for severity, refs, reason, impact, fix, scenario in unit_findings(blocks):
        add("bounds", severity, refs, reason, impact, fix, scenario)
    calendar = calendar_checks(blocks, product_paths)
    for check in calendar:
        if check["expected_month"] != check["event_month"]:
            add("calendar", "HIGH", [check["rule"], check["example"]],
                "Ожидаемый месяц счётчика в примере расходится с месяцем события, указанного в правиле.",
                "QA и разработчик получат разные ожидаемые суммы за один период.",
                "Какую дату должен использовать расчёт на границе периодов? Зафиксировать ответ в правиле и примере приёмки.",
                " → ".join(c.strip() for c in blocks[check["example"]].strip("|").split("|")))
    # Join a periodic upper bound to an independent trigger for the same effect.
    caps = []
    triggers = []
    for ref in product_paths:
        raw = blocks[ref]
        limit = re.search(r"(?:максимум|не более)\s+(?:один|одна|одно|1)\s+(?:тако[йея]\s+)?([\w-]+)\s+(?:за|в)\s+([^.;]+)", raw, re.I)
        trigger = re.search(r"(?:вызывает|инициирует)\s+([\w-]+)\s+независимо от\s+([^.;]+)", raw, re.I)
        if limit:
            caps.append((ref, limit[1].lower(), limit[2]))
        if trigger:
            triggers.append((ref, trigger[1].lower(), trigger[2]))
    for bound, effect, period in caps:
        for repeat, action, history in triggers:
            if effect == action and bound != repeat and paths[bound][:1] == paths[repeat][:1]:
                finding = add("state", "HIGH", [bound, repeat],
                    f"Для «{effect}» заданы предел за период и триггер независимо от {history}.",
                    "Две реализации могут выбрать разные результаты при повторном срабатывании.",
                    "Какое правило имеет приоритет при совпадении условий?",
                    f"Допущение: оба правила применимы к одному объекту. Период: {period}. "
                    f"Первое событие уже вызвало {effect}. До конца периода вновь выполняется условие триггера.")
                finding["effect"] = effect
    for r in reqs:
        if VAGUE.search(r["summary"]):
            add("verifiability", "MEDIUM", r["refs"], "Качественная характеристика требует критерия проверки.",
                "Приёмщики могут по-разному оценить результат.", "Указать метрику или ссылку на критерий.")
    model_rows = [r for r in rows if r["kind"] in {"issue", "question"}]
    candidate_count = len(findings) + len(model_rows)
    for r in model_rows:
        category = r.get("category", "semantic")
        detector = r.get("provider", "gemini")
        # One mutation through GET is one defect even if the model cites extra context.
        # Distinct failure modes on the same lines must remain separate.
        claim = r["summary"].casefold()
        same_http_effect = (re.search(r"\bget\b", claim) and
                            re.search(r"изменени|сохран|запис|обнов|удал|мутаци|modif|mutat|writ|delet", claim))
        matches = [f for f in findings if f["category"] == "http" and "rule" in f["detectors"]
                   and set(f["core_refs"]) <= set(r["refs"])] if same_http_effect else []
        if r.get("rule_match"):
            signature = r["rule_match"]
            matches = [f for f in findings if "rule" in f["detectors"] and f["category"] == category
                       and all(signature.get(k) == f[k] for k in ("category", "core_refs", "reason"))
                       and set(f["core_refs"]) <= set(r["refs"])]
        if not matches and category in {"calendar", "state"}:
            signal = (claim + " " + r["action"]).casefold()
            for f in findings:
                if (f["category"] != category or "rule" not in f["detectors"]
                        or not set(f["core_refs"]) <= set(r["refs"])):
                    continue
                if category == "calendar":
                    equivalent = (re.search(r"месяц|период", signal)
                                  and re.search(r"расход[ия]|противореч|расхожд|несовмест|не совпад|вместо|"
                                                r"(?:разн|друг)\w*\s+(?:месяц|период)", signal)
                                  and re.search(r"пример|критери|при[её]мк|сценари", signal))
                else:
                    equivalent = (f["effect"] in signal and re.search(r"повтор|втор|снов|уже", signal)
                                  and re.search(r"максим|огранич|лимит|один|одн[ауо]|не более", signal))
                if equivalent:
                    matches.append(f)
        if not matches:
            matches = [f for f in findings if f["category"] == category
                       and set(f["core_refs"]) == set(r["refs"]) and f["reason"].casefold() == claim
                       and f["impact"] == r["impact"] and f["recommended_fix"] == r["action"]
                       and f["counterexample"] == r["scenario"]]
        if len(matches) == 1:
            f = matches[0]
            f.setdefault("corroboration", []).append(dict(r))
            if detector not in f["detectors"]:
                f["detectors"].append(detector)
            known = {s["anchor"] for s in f["source_refs"]}
            f["source_refs"].extend({"anchor": k, "quote": blocks[k]} for k in dict.fromkeys(r["refs"]) if k not in known)
            f["observed_text"] = " / ".join(s["quote"] for s in f["source_refs"])
            f["context_refs"] = list(dict.fromkeys(f.get("context_refs", []) + r.get("context_refs", [])))
            continue
        severity = r.get("severity", "HIGH" if r["kind"] == "issue" else "MEDIUM")
        f = add(category, severity, r["refs"], r["summary"], r["impact"], r["action"], r["scenario"])
        f.update(detectors=[detector], criterion=r.get("criterion"), context_refs=r.get("context_refs", []))
        if re.fullmatch(r"(?:критическ|высок|низк|средн|значительн)\w*[.!]?", r["impact"].strip(), re.I):
            f["impact"] = "Последствие по приведённым источникам не установлено. Требуется оценка владельца."
            f["impact_status"] = "UNKNOWN"
    for n, r in enumerate(reqs, 1):
        r["id"] = f"R-{n:03}"
        r["findings"] = [f["id"] for f in findings if set(f["core_refs"]).intersection(r["refs"])]
        if r["findings"]:
            r["action"] = "Разобрать связанные замечания " + ", ".join(r["findings"]) + "."
        elif r["coverage"] == "pending":
            code = re.match(r"^\**([1-5]\d{2})[.\s*]+", r["summary"])
            if code:
                r["action"] = f"Для HTTP {code[1]} сверить условие возврата и пример тела ответа."
            else:
                r["action"] = f"Смысловая оценка не подтверждена. Какой наблюдаемый результат подтвердит условие {r['refs'][0]}?"
    blockers = [f for f in findings if f["severity"] == "BLOCKER"]
    mapped = {ref for r in reqs for ref in r["refs"]}
    # Unclassified prose may contain an implicit obligation. Leave it visible to reviewers.
    unclassified = [ref for ref in paths if ref not in mapped and ref not in supporting]
    open_controls = [ref for ref, item in controls.items() if item["state"] not in {"DECLARED", "NOT_APPLICABLE"}]
    evidence_needed = open_controls + list(document_gaps)
    pending = [r for r in reqs if r["coverage"] == "pending"]
    open_assessments = [r["id"] for r in reqs if any(a["assessment"] != "grounded" for a in r["model_assessments"])]
    gate = "BLOCKED" if blockers else "REVIEW" if findings or not complete or not reqs or unclassified or pending or open_assessments or evidence_needed else "READY"
    links = [{"from":r["id"], "to":k, "relation":"source"} for r in reqs for k in r["refs"]]
    links.extend({"from":r["id"], "to":f, "relation":"finding"} for r in reqs for f in r["findings"])
    from assessment import assess, acceptance_links, disposition
    links.extend(acceptance_links(reqs, blocks, paths))
    criteria = assess(reqs, findings, unclassified + evidence_needed + [r["refs"][0] for r in pending])
    outstanding = unclassified + evidence_needed + [r["refs"][0] for r in reqs if r["coverage"] == "pending" or r["id"] in open_assessments]
    return dict(requirements=reqs, findings=findings, gate=gate, links=links, calendar_checks=calendar,
                decision=disposition(gate, findings, outstanding),
                candidate_count=candidate_count, pending_requirements=[r["id"] for r in pending],
                open_assessments=open_assessments,
                set_criteria=criteria, criteria_profile="29148:2018 / SpecGuard 1",
                review_controls=list(controls.values()), document_gaps=document_gaps,
                table_headers=[ref for ref in paths if ref in headers], unclassified_refs=unclassified)
