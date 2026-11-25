"""Evidence attached to quality criteria and explicit acceptance references."""
import re
from collections import defaultdict


INDIVIDUAL = {
    "necessary": "Необходимость", "appropriate": "Уместность уровня детализации",
    "unambiguous": "Однозначность", "complete": "Полнота", "singular": "Атомарность",
    "feasible": "Реализуемость", "verifiable": "Проверяемость", "correct": "Корректность",
    "conforming": "Соответствие правилам оформления",
}
SET = {
    "set_complete": "Полнота набора", "consistent": "Согласованность",
    "set_feasible": "Совместная реализуемость", "comprehensible": "Понятность",
    "validatable": "Возможность валидации",
}
RULE_CRITERIA = {
    "bounds": ("feasible", "consistent", "set_feasible"),
    "calendar": ("unambiguous", "consistent", "validatable"),
    "state": ("unambiguous", "consistent"),
    "http": ("unambiguous", "consistent"),
    "placeholder": ("complete", "set_complete"),
    "verifiability": ("verifiable", "validatable"),
}


def assess(requirements, findings, pending_refs):
    """Record what was demonstrated. Missing business context has no default PASS."""
    affected = defaultdict(list)
    for f in findings:
        for criterion in {*RULE_CRITERIA.get(f["category"], ()), f.get("criterion")} - {None}:
            affected[criterion].append(f)

    def matrix(criteria, ids):
        result = {}
        for criterion in criteria:
            hits = [f for f in affected[criterion] if ids is None or f["id"] in ids]
            result[criterion] = {
                "status": ("FAIL" if any(f["status"] == "CONFIRMED" for f in hits)
                           else "REVIEW" if hits else "UNKNOWN"),
                "findings": [f["id"] for f in hits],
            }
        return result

    for r in requirements:
        r["criteria"] = matrix(INDIVIDUAL, set(r["findings"]))
        for a in r["model_assessments"]:
            item = r["criteria"][a["criterion"]]
            item.setdefault("model_evidence", []).append(a["action"])
            if item["status"] == "UNKNOWN" and a["assessment"] == "grounded" and r["coverage"] == "reviewed":
                item["status"] = "MODEL_ASSESSED"
            if a["assessment"] == "review" and item["status"] != "FAIL":
                item["status"] = "REVIEW"
    result = matrix(SET, None)
    if pending_refs:
        result["set_complete"].update(status="REVIEW", pending_refs=list(dict.fromkeys(pending_refs)))
    return result


def acceptance_links(requirements, blocks, paths):
    """Only an explicit reference to a unique definition supports a trace."""
    definitions = defaultdict(list)
    for r in requirements:
        if r["source_id"] != "—":
            definitions[r["source_id"].casefold()].append(r)
    edges = []
    for ref, sections in paths.items():
        if not any(re.search(r"при[её]мк|acceptance", title, re.I) for _, title, _ in sections):
            continue
        identifiers = re.findall(r"(?<![\w-])[A-ZА-ЯЁ]{1,12}-\d+(?![\w-])", blocks[ref], re.I)
        for ident in dict.fromkeys(v.casefold() for v in identifiers):
            targets = definitions.get(ident, [])
            if len(targets) == 1 and ref not in targets[0]["refs"]:
                edges.append({"from": targets[0]["id"], "to": ref, "relation": "acceptance_reference"})
    return edges
