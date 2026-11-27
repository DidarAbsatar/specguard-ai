"""Deterministic checks of an HTTP contract description.

Each check reads only the structure of the document (headings, status lines, parameter
tables, example bodies). Nothing here knows the business domain of a particular case.
Every result names the exact lines that disagree.
"""
import re

HEADING = re.compile(r"^(#{1,6})\s+(.+)$")
STATUS_HEADING = re.compile(r"^#{1,6}\s+\**\s*([1-5]\d\d)\b")
STATUS_LINE = re.compile(r"^[-*\s]*\**\s*([1-5]\d\d)[.:)]\**\s+\S")
CODE = re.compile(r"(?<![\d.,])([1-5]\d\d)(?!\d|[.,]\d|\s*(?:бит|bit|мс|ms|₸|тенге|руб|%))")
STATUS_CONTEXT = re.compile(r"возвращ|результат|статус|код|ответ|status|return|respon", re.I)
RETURNS = re.compile(r"возвращает(?:ся|е)?\s+(?:код\s+|статус\s+)?([1-5]\d\d)\b|returns?\s+([1-5]\d\d)\b", re.I)
CONTENT_TYPE = re.compile(r"content-type", re.I)
NO_BODY = re.compile(r"(?:тело|body)\W{0,3}(?:\w+\W+){0,3}(?:не используется|не передаётся|не передается|отсутствует|"
                     r"не требуется|not used|is empty|none)", re.I)
ERROR_BODY = re.compile(r"\b(?:error|fail(?:ed|ure)?|ошибка)\b", re.I)
BAD_PARAMS = re.compile(r"параметр|неверн|некоррект|invalid|validation|валидац", re.I)
REASONS = {
    "ok": "200", "created": "201", "accepted": "202", "no content": "204",
    "bad request": "400", "unauthorized": "401", "forbidden": "403", "not found": "404",
    "conflict": "409", "unprocessable": "422", "too many requests": "429",
    "internal server error": "500", "service unavailable": "503",
}


def _cells(raw):
    return [c.strip(" *`") for c in raw.strip().strip("|").split("|")]


def _is_separator(raw):
    return bool(re.fullmatch(r"[|:\s-]+", raw))


def contract_findings(blocks):
    """Return tuples (severity, refs, reason, impact, fix, scenario)."""
    refs = list(blocks)
    found = []
    headings = {}            # ref -> heading text
    status_scope = {}        # ref -> (code, heading ref) for lines under a status heading
    section_of = {}          # ref -> nearest heading ref
    fence = False
    code_lines = set()
    current_heading, current_status = None, None
    for ref in refs:
        raw = blocks[ref]
        if re.match(r"^(`{3,}|~{3,})", raw):
            fence = not fence
            continue
        heading = HEADING.match(raw)
        if heading and not fence:
            current_heading = ref
            headings[ref] = heading[2]
            status = STATUS_HEADING.match(raw)
            current_status = (status[1], ref) if status else None
            continue
        section_of[ref] = current_heading
        if current_status:
            status_scope[ref] = current_status
        if fence or raw.lstrip().startswith(("{", "[")):
            code_lines.add(ref)

    described = {}
    for ref in refs:
        raw = blocks[ref]
        match = STATUS_HEADING.match(raw) or (ref not in code_lines and STATUS_LINE.match(raw))
        if match:
            described.setdefault(match[1], ref)
    if not described:
        return found

    # 1. A status is used in prose but has no own condition or section.
    mentioned = {}
    for ref in refs:
        raw = blocks[ref]
        if ref in code_lines or ref in headings or raw.startswith("|") or STATUS_LINE.match(raw):
            continue
        if not STATUS_CONTEXT.search(raw):
            continue
        for code in CODE.findall(raw):
            mentioned.setdefault(code, ref)
    for code, ref in mentioned.items():
        if code not in described:
            found.append(("MEDIUM", [ref],
                f"HTTP {code} упомянут в тексте, но для него нет описания условия и примера ответа.",
                f"Клиент и сервер по-разному обработают ответ {code}.",
                f"Описать условие возврата {code} и тело ответа либо убрать упоминание.",
                None))

    # 2. Inside a section for one status the text says another status is returned.
    for ref, (code, heading_ref) in status_scope.items():
        match = RETURNS.search(blocks[ref])
        if match:
            other = match[1] or match[2]
            if other != code:
                found.append(("HIGH", [heading_ref, ref],
                    f"Раздел ответа {code} утверждает, что возвращается {other}.",
                    "Невозможно написать тест: неизвестно, какой статус ожидать в этом сценарии.",
                    f"Выбрать один статус для сценария и привести раздел {code} и пример к нему.",
                    f"Запрос из сценария раздела {code}: тест ожидает {code} или {other}?"))

    # 3. Reason phrase of a status heading belongs to a different code.
    for ref, text in headings.items():
        status = STATUS_HEADING.match(blocks[ref])
        if not status:
            continue
        lowered = text.casefold()
        for phrase, code in REASONS.items():
            if re.search(rf"\b{phrase}\b", lowered) and code != status[1] and code[0] == status[1][0]:
                found.append(("MEDIUM", [ref],
                    f"Заголовок статуса {status[1]} содержит формулировку «{phrase.title()}», которая соответствует {code}.",
                    f"Разработчик может вернуть {code} вместо {status[1]}, тест упадёт.",
                    f"Указать один код и соответствующую ему формулировку.", None))
                break

    # 4. An error body is shown under a success status while a client-error status exists.
    bad_param = next((ref for code, ref in described.items()
                      if code.startswith("4") and BAD_PARAMS.search(blocks[ref])), None)
    seen = set()
    for ref, (code, heading_ref) in status_scope.items():
        if code.startswith("2") and ref in code_lines and ERROR_BODY.search(blocks[ref]) and heading_ref not in seen:
            seen.add(heading_ref)
            evidence = [heading_ref, ref] + ([bad_param] if bad_param else [])
            found.append(("HIGH", evidence,
                f"Под успешным статусом {code} приведён пример ответа с ошибкой."
                + (" При этом для неверных параметров описан отдельный статус." if bad_param else ""),
                "Клиент может принять отказ за успешное сохранение; тест не знает, какой код ожидать.",
                "Определить один код для отклонённого запроса и убрать пример ошибки из успешного статуса.",
                "Запрос с недопустимым значением: ожидается 2xx с признаком ошибки или 4xx?"))

    # 5. A content type is declared for a body that is said not to exist.
    by_section = {}
    for ref, heading_ref in section_of.items():
        by_section.setdefault(heading_ref, []).append(ref)
    for heading_ref, members in by_section.items():
        ctype = next((r for r in members if CONTENT_TYPE.search(blocks[r])), None)
        nobody = next((r for r in members if NO_BODY.search(blocks[r])), None)
        if ctype and nobody:
            found.append(("MEDIUM", list(dict.fromkeys([ctype, nobody])),
                "Для тела запроса указан Content-Type, но в том же разделе сказано, что тела нет.",
                "Клиент может отправить тело, а сервер ждать параметры в строке запроса, или наоборот.",
                "Выбрать способ передачи параметров и удалить противоречащую строку.", None))

    # 6. The same field has different types in different parameter tables.
    tables, header, current = [], None, None
    for ref in refs:
        raw = blocks[ref]
        if not raw.startswith("|"):
            header = None
            continue
        if _is_separator(raw):
            continue
        cells = [c.casefold() for c in _cells(raw)]
        if header is None:
            name_col = next((i for i, c in enumerate(cells) if c in {"parameter", "параметр", "поле", "field", "name"}), None)
            type_col = next((i for i, c in enumerate(cells) if c in {"format", "формат", "type", "тип"}), None)
            header = (name_col, type_col) if name_col is not None and type_col is not None else (None, None)
            if header[0] is not None:
                current = dict(ref=ref, fields={})
                tables.append(current)
            continue
        if header[0] is None:
            continue
        values = _cells(raw)
        if max(header) < len(values) and values[header[0]]:
            current["fields"][values[header[0]]] = (values[header[1]].casefold(), ref)
    for i, a in enumerate(tables):
        for b in tables[i + 1:]:
            clash = [(name, a["fields"][name], b["fields"][name]) for name in a["fields"].keys() & b["fields"].keys()
                     if a["fields"][name][0] and b["fields"][name][0] and a["fields"][name][0] != b["fields"][name][0]]
            if clash:
                clash.sort(key=lambda c: refs.index(c[1][1]))
                names = ", ".join(f"{n} ({x[0]} / {y[0]})" for n, x, y in clash)
                evidence = [r for _, x, y in clash for r in (x[1], y[1])]
                found.append(("MEDIUM", evidence,
                    f"Одно и то же поле имеет разный тип в разных таблицах параметров: {names}.",
                    "Клиент и сервер по-разному сериализуют значения, проверка типов в тестах противоречива.",
                    "Зафиксировать один тип для каждого поля во всех таблицах.", None))
    return found
