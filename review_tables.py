"""Read document review checklists without treating template choices as approvals."""
import re


CRITERION = {"проверка", "критерий", "контроль", "пункт проверки", "check", "criterion", "control"}
STATUS = {"создано или доступно", "проверено", "статус", "отметка", "выполнено", "результат проверки",
          "status", "reviewed", "available", "checked"}
FIELD = {"поле", "параметр", "field", "property"}
VALUE = {"значение", "value"}
MISSING = {"", "—", "–", "-", "не указано", "не указан", "не заполнено", "tbd", "tbs"}
CONTRIBUTOR = re.compile(r"(?:(?:business|product|document|technical)\s+)?owner|author|editor|developer|"
                         r"analyst|reviewer|автор|аналитик|редактор|составитель|разработчик|"
                         r"владелец(?:\s+(?:документа|продукта|процесса))?", re.I)


def cells(line):
    return [s.strip() for s in re.split(r"(?<!\\)\|", line.removeprefix("|").removesuffix("|"))]


def label(text):
    return text.strip("*\x60 ").casefold()


def mark(text):
    value = label(text)
    if value in MISSING or re.fullmatch(r"(?:да|нет|не требуется|не применимо|yes|no|n/a)"
                                        r"(?:\s*/\s*(?:да|нет|не требуется|не применимо|yes|no|n/a))+", value):
        return "UNMARKED"
    if value in {"нет", "no"}:
        return "NEGATIVE"
    if value in {"да", "yes"}:
        return "DECLARED"
    if value in {"не требуется", "не применимо", "n/a"}:
        return "NOT_APPLICABLE"
    return "REVIEW"


def document_roles(blocks, paths, header_refs, *, contributors=None):
    controls, gaps, headers = {}, {}, set()
    layout, title, last_ref, last_coord = [], None, None, None
    for ref, raw in blocks.items():
        if ref not in paths or not raw.startswith("|"):
            layout, title, last_coord = [], None, None
            if ref in paths and re.search(r"документ|паспорт|спецификац", raw, re.I) and re.search(
                    r"\b(?:верси[ияю]|дат[ауые]?)\b", raw, re.I) and re.search(
                    r"\bне заполнен[а-яё]*\b|\bне указан[а-яё]*\b", raw, re.I):
                # Conditional behavior in case of a missing value is itself a potential product requirement.
                if not re.search(r"\b(?:если|когда|при|долж\w*|обязан\w*|запрещ\w*|необходимо|требуется|must|shall)\b", raw, re.I):
                    gaps[ref] = "В тексте явно отмечено отсутствие реквизитов документа. Уточнить заполнение и версию для согласования."
            continue
        fields = cells(raw)
        names = [label(v) for v in fields]
        coord = re.fullmatch(r"P(\d+)L(\d+)", ref)
        current = tuple(map(int, coord.groups())) if coord else None
        if last_coord and current and (current[0] != last_coord[0] or
                current[1] - last_coord[1] > (2 if title == last_ref else 1)):
            layout, title = [], None
        last_coord, last_ref = current, ref
        is_check = len(set(names) & CRITERION) == 1 and bool(set(names) & STATUS)
        if ref in header_refs or is_check or (len(names) == 2 and names[0] in FIELD and names[1] in VALUE):
            headers.add(ref)
            layout, title = fields, ref
            continue
        if len(fields) != len(layout):
            continue
        keys = [label(v) for v in layout]
        statuses = [{"column": k, "text": v, "state": mark(v)} for k, v in zip(layout, fields) if label(k) in STATUS]
        criteria = [v for k, v in zip(keys, fields) if k in CRITERION]
        if len(criteria) == 1 and criteria[0] and statuses:
            states = {s["state"] for s in statuses}
            state = next((s for s in ("NEGATIVE", "REVIEW", "UNMARKED") if s in states),
                         "NOT_APPLICABLE" if states == {"NOT_APPLICABLE"} else "DECLARED")
            controls[ref] = dict(id=f"C-{len(controls)+1:03}", ref=ref, header_ref=title, criterion=criteria[0],
                                 marks=statuses, state=state,
                                 notes=[{"column": k, "text": v} for k, v in zip(layout, fields)
                                        if label(k) not in CRITERION | STATUS and v])
        elif len(keys) == 2 and keys[0] in FIELD and keys[1] in VALUE and fields[0] and names[1] in MISSING:
            name = fields[0].strip("*\x60 ")
            gaps[ref] = f"У поля «{name}» нет значения. Уточнить применимость и при необходимости указать источник."
        elif contributors is not None and len(keys) == 2 and keys[0] in FIELD and keys[1] in VALUE:
            roles = re.split(r"\s*[/,;]\s*", names[0])
            if all(CONTRIBUTOR.fullmatch(role) for role in roles):
                contributors[ref] = fields[1]
    return controls, gaps, headers
