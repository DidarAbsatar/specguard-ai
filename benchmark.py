"""Reproducible small regression corpus. Units are (category, source lines)."""
import argparse
import json
import time
from pathlib import Path
from quality import analyze

CASES = [
    (["R-1. Размер не менее 18 байт.", "R-2. Размер не более 12 байт."], [("bounds", (1,2))]),
    (["Срок не менее 3 дней.", "Срок не более 3 дней."], []),
    (["# Онлайн", "Срок не менее 4 дней.", "# Офлайн", "Срок не более 2 дней."], []),
    (["Срок не менее 5 дней.", "Срок не более 1 часа."], [("bounds", (1,2))]),
    (["Система должна быстро вернуть ответ."], [("verifiability", (1,))]),
    (["Уровень доступа: TBD"], [("placeholder", (1,))]),
    (["| HTTP method | GET |", "1. Удалить запись."], [("http", (1,2))]),
    (["| HTTP method | PUT |", "1. Обновить запись."], []),
    (["Клиент должен получить квитанцию."], []),
]


def run(cloud=False, hybrid=False):
    tp = fp = fn = 0
    failures = 0
    started = time.monotonic()
    for lines, expected in CASES:
        src = {f"P1L{i}": v for i,v in enumerate(lines,1)}
        if cloud:
            from specguard import semantic, verify_candidates
            try:
                rows = semantic(src)
                if hybrid:
                    rows = [r for r in verify_candidates(rows, src) if r["kind"] != "rejected"]
            except (ValueError, OSError, KeyError):
                failures += 1
                rows = []
            actual = {tuple(sorted(int(k[3:]) for k in r["refs"])) for r in rows if r["kind"] != "requirement"}
            if hybrid:
                actual = {tuple(sorted(int(s["anchor"][3:]) for s in f["source_refs"]))
                          for f in analyze(src, rows, True)["findings"]}
            gold = {anchors for category, anchors in expected}
        else:
            findings = analyze(src, [], False)["findings"]
            actual = {(f["category"], tuple(sorted(int(s["anchor"][3:]) for s in f["source_refs"]))) for f in findings}
            gold = set(expected)
        tp += len(actual & gold)
        fp += len(actual - gold)
        fn += len(gold - actual)
    return dict(documents=len(CASES), failures=failures, elapsed_s=round(time.monotonic()-started,2),
                matching="anchors only" if cloud else "category and anchors",
                true_positive=tp, false_positive=fp, false_negative=fn,
                precision=tp/(tp+fp) if tp+fp else None, recall=tp/(tp+fn) if tp+fn else None)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-cloud", action="store_true", help="Отправить тестовые документы в Gemini")
    parser.add_argument("--hybrid", action="store_true", help="Добавить правила и сверку замечаний в Gemini")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.hybrid and not args.allow_cloud:
        parser.error("--hybrid требует --allow-cloud")
    metrics = run(args.allow_cloud, args.hybrid)
    result = json.dumps(metrics, indent=2)
    if args.output:
        args.output.parent.mkdir(exist_ok=True, parents=True)
        args.output.write_text(result, encoding="utf8")
    print(result)
    raise SystemExit(2 if metrics["failures"] else 0)
