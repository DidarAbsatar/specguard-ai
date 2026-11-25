"""Reproducible small regression corpus. Units are (category, source lines)."""
import argparse
from collections import Counter
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

TRANSFER_CASES = [
    (["R-1. Буфер минимум 32 байта.", "R-2. Буфер максимум 7 байтов."], [("bounds", (1, 2))]),
    (["# Требования", "Сервис должен выдать талон.", "```text", "Лимит TBD", "```"], []),
    (["Задержка минимум 2 минуты.", "Задержка максимум 120 секунд."], []),
    (["# Архив", "Объём минимум 27 байтов.", "# Экспорт", "Объём максимум 3 байта."], []),
    (["Месяц определяется по дате доставки.",
      "| Доставка 30 ноября | Учесть 1 декабря | Декабрьский счётчик увеличен |"], [("calendar", (1, 2))]),
    (["Месяц определяется по дате доставки.",
      "| Доставка 30 ноября | Учесть 1 декабря | Ноябрьский счётчик увеличен |"], []),
    (["Сервис выдаёт максимум один талон за неделю.",
      "Повторная регистрация вызывает талон независимо от истории пациента."], [("state", (1, 2))]),
    (["| HTTP method | GET |", "1. Прочитать квитанцию."], []),
]


def run(cloud=False, hybrid=False, suite="core"):
    cases = {"core": CASES, "transfer": TRANSFER_CASES, "all": CASES + TRANSFER_CASES}[suite]
    tp = fp = fn = 0
    failures = 0
    started = time.monotonic()
    details = []
    for index, (lines, expected) in enumerate(cases, 1):
        src = {f"P1L{i}": v for i,v in enumerate(lines,1)}
        if cloud:
            from specguard import semantic, verify_candidates
            try:
                rows = semantic(src)
                if hybrid:
                    rows = [r for r in verify_candidates(rows, src) if r["kind"] != "rejected"]
            except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
                failures += 1
                details.append(dict(document=index, error=type(exc).__name__))
                continue
            if not hybrid:
                actual = [(r["category"], tuple(sorted({int(k[3:]) for k in r["refs"]})))
                          for r in rows if r["kind"] != "requirement"]
        else:
            rows = []
        if not cloud or hybrid:
            findings = analyze(src, rows, cloud)["findings"]
            actual = [(f["category"], tuple(sorted(int(k[3:]) for k in f["core_refs"]))) for f in findings]
        gold, predicted = Counter(expected), Counter(actual)
        hits, extra, missed = (gold & predicted).total(), (predicted - gold).total(), (gold - predicted).total()
        tp += hits
        fp += extra
        fn += missed
        details.append(dict(document=index, expected=expected, predicted=actual, tp=hits, fp=extra, fn=missed))
    return dict(documents=len(cases), completed=len(cases)-failures, suite=suite, failures=failures,
                status="INCOMPLETE" if failures else "COMPLETE", cases=details,
                elapsed_s=round(time.monotonic()-started,2), matching="category and core anchors, counting duplicates",
                true_positive=tp, false_positive=fp, false_negative=fn,
                precision=tp/(tp+fp) if tp+fp and not failures else None,
                recall=tp/(tp+fn) if tp+fn and not failures else None)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-cloud", action="store_true", help="Отправить тестовые документы в Gemini")
    parser.add_argument("--hybrid", action="store_true", help="Добавить правила и сверку замечаний в Gemini")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--suite", choices=("core", "transfer", "all"), default="all")
    args = parser.parse_args()
    if args.hybrid and not args.allow_cloud:
        parser.error("--hybrid требует --allow-cloud")
    metrics = run(args.allow_cloud, args.hybrid, args.suite)
    result = json.dumps(metrics, indent=2)
    if args.output:
        args.output.parent.mkdir(exist_ok=True, parents=True)
        args.output.write_text(result, encoding="utf8")
    print(result)
    raise SystemExit(2 if metrics["failures"] else 0)
