import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from comparison import compare
from provenance import revision
from quality import analyze
from reporting import format_comparison, format_report
from specguard import verify_candidates


class ReleaseReviewTests(unittest.TestCase):
    def test_exact_fractional_conflict_and_compatible_revision(self):
        src = {"a": "Q-1. Задержка минимум 0,100000000000000001 секунд.",
               "b": "Q-2. Задержка максимум 0.1 секунд."}
        result = analyze(src, [], False)
        self.assertEqual(result["gate"], "BLOCKED")
        self.assertEqual(result["findings"][0]["proof"]["minimum"], "0.100000000000000001")
        fixed = dict(src, a="Q-1. Задержка минимум 0,1 секунд.")
        diff = compare(src, fixed)
        self.assertEqual(diff["changes"][0]["proof"]["witness"], "0.1")
        diff.update(before={"name": "a", "sha256": "a"}, after={"name": "b", "sha256": "b"},
                    version="test", build="test")
        self.assertIn("0.1", format_comparison(diff, ".html"))
        self.assertEqual(json.loads(format_comparison(diff, ".json"))["counts"]["FIX_CONFIRMED"], 1)
        duration = {"a": "Срок минимум 1,5 часа.", "b": "Срок максимум 90 минут."}
        self.assertFalse(analyze(duration, [], False)["findings"])

    def test_first_decision_exposes_period_boundary_to_owner_and_qa(self):
        src = {"a": "| HTTP method | GET |", "b": "1. Удалить запись.",
               "c": "Месяц определяется по дате доставки.",
               "d": "| Доставка 30 ноября | Учесть 1 декабря | Декабрьский счётчик увеличен |"}
        run = analyze(src, [], False)
        first = run["decision"]["first"]
        self.assertEqual(first["refs"], ["c", "d"])
        self.assertIn("30 ноября", first["scenario"])
        html = format_report(dict(run, sources=src, manifest={}), ".html")
        for value in ["Разработка", "Тестирование и приёмка", first["owner"], "30 ноября"]:
            self.assertIn(value, html)

    def test_placeholder_and_http_context_have_distinct_actions(self):
        src = {"a": "# Спецификация", "b": "заполняется аналитиком",
               "c": "| Request URL | Test: /read. Live: — |", "d": "Данные заполняются автоматически.",
               "e": "## Ответы", "f": "**409.** Возврат при совпадении номера."}
        run = analyze(src, [], False)
        self.assertEqual([f["core_refs"] for f in run["findings"]], [["b"], ["c"]])
        rows = {r["refs"][0]: r for r in run["requirements"]}
        self.assertIn("HTTP 409", rows["f"]["action"])
        self.assertIn("Live", run["findings"][1]["recommended_fix"])

    def test_example_heading_reaches_verifier_without_becoming_a_behavior_claim(self):
        src = {"a": "### Порядок возврата", "b": "#### 409. Конфликт",
               "c": "```text", "d": "# пример", "e": "повторная запись", "f": "```"}
        claim = dict(kind="issue", refs=["e"], summary="Сценарий ошибки", scenario="Повтор регистрации.",
                     impact="Среднее", action="Какой результат должен увидеть клиент?")
        with patch("specguard.gemini_json", return_value=[dict(id=0, keep=True, reason="По цитате.")]) as remote:
            rows = verify_candidates([claim], src)
        self.assertEqual(remote.call_args.args[1][0]["section_headings"], {"b": src["b"]})
        f, = analyze(src, rows, True)["findings"]
        self.assertEqual(f["core_refs"], ["e"])
        self.assertEqual(f["context_refs"], ["b"])
        self.assertEqual(f["impact_status"], "UNKNOWN")

    def test_packaged_revision_requires_matching_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "_specguard_release.py").write_text("# " + "f"*40 + " " + "1"*16, encoding="ascii")
            self.assertEqual(revision(root, "1"*16), "f"*40)
            self.assertIsNone(revision(root, "2"*16))
