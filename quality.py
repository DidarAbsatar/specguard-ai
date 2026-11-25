"""Evidence-linked review of normative statements and their acceptance examples."""
import re
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


def inventory(blocks, paths=None):
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
        if not (ident or normative or CONTRACT_FIELD.match(text) or NORM.search(text) or BOUND.match(text)):
            continue
        if text.startswith(("```", "{")) or text.lower() in ("или", "да / нет"):
            continue
        clean = text[ident.end():] if ident else re.sub(r"^\d+[.)]\s+", "", text)
        for sentence in re.split(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z])", clean):
            if not sentence.strip() or re.fullmatch(r"\d+[.)]", sentence):
                continue
            reqs.append(dict(source_id=ident[1] if ident else "—", refs=[ref], summary=sentence,
                             section=section, action="Смысл и полнота требуют ревью."))
    return reqs


def analyze(blocks, rows, complete):
    paths = section_paths(blocks)
    reqs = inventory(blocks, paths)
    semantic = [r for r in rows if r["kind"] == "requirement"]
    covered = {k for r in semantic for k in r["refs"]}
    reqs = [r for r in reqs if r["refs"][0] not in covered]
    for r in semantic:
        ident = IDENT.match(blocks[r["refs"][0]])
        reqs.append(dict(r, source_id=ident[1] if ident else "—", section=""))
    findings = []

    def add(category, severity, refs, reason, impact, fix, scenario=None, confirmed=False):
        evidence = [dict(anchor=k, quote=blocks[k]) for k in dict.fromkeys(refs)]
        findings.append(dict(id=f"F-{len(findings)+1:03}", category=category, severity=severity,
            source_refs=evidence, observed_text=" / ".join(v["quote"] for v in evidence),
            reason=reason, impact=impact, recommended_fix=fix, counterexample=scenario,
            confidence="высокая" if confirmed else "требует проверки", needs_human_decision=True,
            status="CONFIRMED" if confirmed else "REVIEW"))

    bounds = {}
    for ref, raw in blocks.items():
        text = IDENT.sub("", raw).strip()
        if re.search(r"\b(TBD|TBS|TBR)\b", text):
            add("placeholder", "MEDIUM", [ref], "Присутствует маркер открытого решения.",
                "Ожидаемый результат требует уточнения.", "Заполнить значение или объяснить маркер.")
        match = BOUND.fullmatch(text) if ref in paths else None
        if match:
            subject, op, value, unit = match.groups()
            unit = unit.casefold()
            scale = TIME_SCALE.get(unit)
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
        cells = [c.strip(" *`").casefold() for c in raw.strip("|").split("|")]
        if len(cells) == 2 and cells[0] in {"метод", "rest type", "http method", "метод http"}:
            method = ref if cells[1] == "get" else None
        if method and re.match(r"^(?:\d+[.)]\s*)?(?:заменить|удалить|сохранить|обновить)\s", raw, re.I):
            add("http", "HIGH", [method, ref], "Контракт GET содержит операцию изменения состояния.",
                "Клиент может повторить запрос как безопасное чтение.", "Согласовать метод и эффект повторного запроса.",
                "Клиент повторяет тот же GET. Должно ли измениться сохранённое состояние?")
    for r in rows:
        if r["kind"] != "requirement":
            add("semantic", "HIGH" if r["kind"] == "issue" else "MEDIUM", r["refs"], r["summary"],
                r["impact"], r["action"], r["scenario"])
    months = ("январ","феврал","март","апрел","ма[йяе]","июн","июл","август","сентябр","октябр","ноябр","декабр")
    calendar = []
    for ref, raw in blocks.items():
        rule = re.search(r"месяц (?:определяется|рассчитывается) по дате (?:совершения )?([а-яё]{4,})", raw, re.I)
        if rule:
            stem = re.sub(r"[ыияа]$", "", rule[1].casefold())
            calendar.append((ref, stem))
    # A unique allocation rule and a three-column example with explicit dates.
    if len(calendar) == 1:
        for k,line in blocks.items():
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
    for ref, raw in blocks.items():
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
    for n,r in enumerate(reqs,1):
        r["id"] = f"R-{n:03}"
        r["findings"] = [f["id"] for f in findings if any(s["anchor"] in r["refs"] for s in f["source_refs"])]
        if r["action"] == "Смысл и полнота требуют ревью.":
            if r["findings"]:
                r["action"] = "Требуется решение по связанным замечаниям."
            elif re.search(r"\b(?:быстро|удобно|своевременно|оперативно)\b", r["summary"], re.I):
                r["action"] = "Проверяемость требует уточнения измеримого критерия."
                add("verifiability", "MEDIUM", r["refs"], "Качественная характеристика требует критерия проверки.",
                    "Приёмщики могут по-разному оценить результат.", "Указать метрику или ссылку на критерий.")
                r["findings"].append(findings[-1]["id"])
            elif re.search(r"\d", IDENT.sub("", r["summary"])):
                r["action"] = "Есть числовой ориентир. Проверить единицы, границы и условия применения."
            else:
                r["action"] = "Автопроверки явных нарушений не выявили. Полнота и бизнес-корректность требуют подтверждения."
    blockers = [f for f in findings if f["severity"] == "BLOCKER"]
    mapped = {ref for r in reqs for ref in r["refs"]}
    # Unclassified prose may contain an implicit obligation. Leave it visible to reviewers.
    unclassified = [ref for ref in paths if ref not in mapped]
    gate = "BLOCKED" if blockers else "REVIEW" if findings or not complete or not reqs or unclassified else "READY"
    links = [{"from":r["id"], "to":k, "relation":"source"} for r in reqs for k in r["refs"]]
    links.extend({"from":r["id"], "to":f, "relation":"finding"} for r in reqs for f in r["findings"])
    return dict(requirements=reqs, findings=findings, gate=gate, links=links,
                unclassified_refs=unclassified)
