"""Compare two revisions with the same deterministic checks and source evidence."""
from collections import defaultdict

from quality import IDENT, analyze, json_number, parse_bound, section_paths


class Revision:
    def __init__(self, blocks):
        self.blocks = blocks
        self.review = analyze(blocks, [], False)
        self.keys = {}
        self.index = defaultdict(list)
        self.table_inputs = defaultdict(list)
        self.paths = section_paths(blocks)
        for ref, path in self.paths.items():
            text = blocks[ref]
            ident = IDENT.match(text)
            scope = tuple((level, title) for level, title, _ in path)
            key = (scope, "id", ident[1]) if ident else (scope, "quote", text)
            self.keys[ref] = key
            self.index[key].append(ref)
            cells = [v.strip() for v in text.strip("|").split("|")]
            if text.startswith("|") and len(cells) == 3:
                self.table_inputs[(scope, cells[0], cells[1])].append(ref)
        self.calendars = {(c["rule"], c["example"]): c for c in self.review["calendar_checks"]}

    def counterparts(self, refs, other):
        result = []
        for ref in refs:
            key = self.keys.get(ref)
            here, there = self.index.get(key, []), other.index.get(key, [])
            if len(here) != 1 or len(there) != 1:
                return []
            result.append(there[0])
        return result

    def citations(self, refs):
        return [{"anchor": ref, "quote": self.blocks[ref]} for ref in refs]

    def calendar_fix(self, refs, other):
        rule, example = refs
        mapped_rule = self.counterparts([rule], other)
        if not mapped_rule or self.blocks[rule] != other.blocks[mapped_rule[0]]:
            return None
        first, second, result = (v.strip() for v in self.blocks[example].strip("|").split("|"))
        key = (self.keys[example][0], first, second)
        examples = other.table_inputs.get(key, [])
        if len(self.table_inputs[key]) != 1 or len(examples) != 1:
            return None
        targets = (mapped_rule[0], examples[0])
        current = other.calendars.get(targets)
        if not current or current["expected_month"] != current["event_month"]:
            return None
        new_result = other.blocks[examples[0]].strip("|").split("|")[2].strip()
        if result.split(maxsplit=1)[1:] != new_result.split(maxsplit=1)[1:]:
            return None
        old = self.calendars[(rule, example)]
        return targets, dict(kind="calendar_alignment", event_month=current["event_month"],
                             before_expected=old["expected_month"], after_expected=current["expected_month"])


def compare(before_blocks, after_blocks):
    before, after = Revision(before_blocks), Revision(after_blocks)
    old = before.review["findings"]
    current = after.review["findings"]
    by_evidence = defaultdict(list)
    for finding in current:
        by_evidence[(finding["category"], tuple(finding["core_refs"]))].append(finding)
    changes = []
    matched = set()
    for f in old:
        refs = f["core_refs"]
        targets = before.counterparts(refs, after)
        entry = {"status": "CHECK", "category": f["category"], "previous_id": f["id"],
                 "current_id": None, "reason": f["reason"], "impact": f["impact"],
                 "action": f["recommended_fix"], "before": before.citations(refs),
                 "after": after.citations(targets)}
        candidates = by_evidence.get((f["category"], tuple(targets)), [])
        same_text = bool(targets) and all(before_blocks[a] == after_blocks[b] for a, b in zip(refs, targets))
        compatible_identity = same_text
        if targets and f.get("proof", {}).get("kind") == "empty_interval":
            lower, upper = (parse_bound(after_blocks[k]) for k in targets)
            proof = f["proof"]
            compatible_identity = bool(lower and upper and lower.minimum and not upper.minimum
                                       and after.paths[targets[0]] == after.paths[targets[1]]
                                       and lower.subject == upper.subject == proof["subject"]
                                       and lower.unit == upper.unit == proof["unit"])
            if compatible_identity and lower.value <= upper.value:
                entry.update(status="FIX_CONFIRMED", proof={
                    "kind": "feasible_interval", "subject": lower.subject, "unit": lower.unit,
                    "before_min": proof["minimum"], "before_max": proof["maximum"],
                    "after_min": json_number(lower.value), "after_max": json_number(upper.value),
                    "witness": json_number(lower.value),
                })
                entry["action"] = "Использовать значение из допустимого интервала при проверке этой пары требований."
        if f["category"] == "calendar":
            fix = before.calendar_fix(refs, after)
            if fix:
                calendar_targets, proof = fix
                entry.update(status="FIX_CONFIRMED", after=after.citations(calendar_targets), proof=proof,
                             action="Взять обновлённый пример как граничный сценарий для проверки месяца начисления.")
        if compatible_identity and len(candidates) == 1 and candidates[0]["id"] not in matched:
            other = candidates[0]
            entry.update(status="PERSISTS", current_id=other["id"], action=other["recommended_fix"])
            matched.add(other["id"])
        if entry["status"] == "CHECK":
            entry["action"] = "Сверить изменение с владельцем: автоматическая проверка не подтвердила устранение."
        changes.append(entry)
    for f in current:
        if f["id"] not in matched:
            changes.append(dict(status="NEW_OBSERVATION", category=f["category"], previous_id=None,
                                current_id=f["id"], reason=f["reason"], impact=f["impact"],
                                action=f["recommended_fix"], before=[], after=after.citations(f["core_refs"])))
    return {"mode": "deterministic", "before_count": len(old), "after_count": len(current), "changes": changes,
            "counts": {status: sum(e["status"] == status for e in changes)
                       for status in ("FIX_CONFIRMED", "PERSISTS", "CHECK", "NEW_OBSERVATION")}}
