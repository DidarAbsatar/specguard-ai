import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from comparison import compare
from chatgpt_provider import strict_schema
from provenance import revision
from quality import analyze
from reporting import format_comparison, format_report
from specguard import semantic, verify_candidates


class ReleaseReviewTests(unittest.TestCase):
    def test_cross_detector_corroboration_preserves_distinct_questions(self):
        src = {"r": "Месяц определяется по дате доставки.",
               "e": "| Доставка 30 ноября | Учесть 1 декабря | Декабрьский счётчик увеличен |",
               "c": "Сервис выдаёт максимум один талон за неделю.",
               "t": "Регистрация вызывает талон независимо от истории клиента."}
        def issue(category, refs, summary):
            return dict(kind="issue", category=category, provider="codex", refs=refs, summary=summary,
                        impact="У приёмщиков расходятся ожидания.", action="Какое правило действует?",
                        scenario="Повторить при тех же условиях.")
        rows = [issue("calendar", ["r", "e"], "Правило и критерий относят событие к разным месяцам."),
                issue("state", ["c", "t"], "Недельный максимум и повторная регистрация допускают второй талон."),
                issue("calendar", ["r", "e"], "В примере отсутствует часовой пояс даты доставки.")]
        run = analyze(src, rows, True)
        self.assertEqual(len(run["findings"]), 3)
        self.assertEqual(run["candidate_count"], 5)
        self.assertEqual([f["detectors"] for f in run["findings"]], [["rule", "codex"], ["rule", "codex"], ["codex"]])

    def test_list_marker_does_not_hide_complete_coverage(self):
        src = {"h": "# Правила", "a": "* Сервис должен выдать чек."}
        row = dict(kind="requirement", refs=["a"], summary="Сервис должен выдать чек.", action="Назван результат.")
        req, = analyze(src, [row], True)["requirements"]
        self.assertEqual(req["coverage"], "reviewed")

    def test_verified_rule_match_requires_the_same_evidence_and_defect_signature(self):
        src = {"r": "Месяц определяется по дате доставки.",
               "e": "| Доставка 30 ноября | Учесть 1 декабря | Декабрьский счётчик увеличен |"}
        claim = dict(kind="issue", refs=["r", "e"], category="calendar", summary="Две разные даты учёта.",
                     impact="Итог за ноябрь отличается.", action="Как учитывать доставку?", scenario="Смена периода.")
        with patch("specguard.gemini_json", return_value=[dict(id=0, keep=True, reason="Совпадает выбор периода.",
                                                                same_rule="F-001")]) as call:
            rows = verify_candidates([claim], src)
            self.assertIn("F-001", call.call_args.args[1][0]["related_rule_findings"])
        self.assertEqual(len(analyze(src, rows, True)["findings"]), 1)
        rows[0]["rule_match"]["reason"] = "Другое наблюдение"
        self.assertEqual(len(analyze(src, rows, True)["findings"]), 2)

    @patch.dict("os.environ", {"SPECGUARD_PROVIDER": "codex", "SPECGUARD_CODEX_MODEL": "test-model"})
    @patch("chatgpt_provider.generate")
    def test_codex_uses_shared_contract_and_records_actual_detector(self, remote):
        question = dict(kind="question", refs=["a"], summary="Не определено условие возврата.",
                        impact="QA не может выбрать ответ.", action="Какое условие применимо?",
                        scenario="Получена вторая заявка.", category="semantic", severity="MEDIUM",
                        criterion="complete")
        remote.return_value = {"requirements": [], "findings": [question]}
        rows = semantic({"a": "Сервис должен вернуть ответ."})
        self.assertEqual(remote.call_args.args[3:5], ("test-model", "analysis"))
        schema = strict_schema(remote.call_args.args[2])
        self.assertFalse(schema["properties"]["requirements"]["items"]["additionalProperties"])
        run = analyze({"a": "Сервис должен вернуть ответ."}, rows, True)
        self.assertEqual(run["findings"], [])
        self.assertEqual(run["questions"][0]["detectors"], ["codex"])

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
