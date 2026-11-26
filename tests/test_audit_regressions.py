import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from benchmark import run
from package_submission import build_package
from quality import analyze
from reporting import format_report
from specguard import PartialReview, main, semantic


def model_row(ref, text, **kwargs):
    row = dict(kind="requirement", refs=[ref], summary=text, action="Результат наблюдаем.",
               category="semantic", criterion="verifiable", assessment="grounded",
               impact="", scenario="", severity="LOW")
    return dict(row, **kwargs)


class AuditRegressions(unittest.TestCase):
    def test_partial_model_coverage_preserves_both_clauses_and_blocks_ready(self):
        src = {"a": "R-1. Сохранить заявку. Уведомить клиента."}
        row = model_row("a", "Сохранить заявку.")
        partial = analyze(src, [row], True)
        self.assertEqual([r["summary"] for r in partial["requirements"]], ["Сохранить заявку.", "Уведомить клиента."])
        self.assertEqual(partial["pending_requirements"], ["R-002"])
        self.assertEqual(partial["gate"], "REVIEW")
        complete = analyze(src, [row, model_row("a", "Уведомить клиента.")], True)
        self.assertEqual(complete["gate"], "READY")
        self.assertEqual(complete["requirements"][0]["criteria"]["correct"]["status"], "UNKNOWN")

    def test_omitted_qualifier_cannot_claim_full_coverage(self):
        src = {"a": "R-1. Хранить заявку до закрытия договора."}
        result = analyze(src, [model_row("a", "Хранить заявку")], True)
        self.assertEqual(result["gate"], "REVIEW")
        self.assertIn("до закрытия договора", result["requirements"][0]["summary"])

    def test_model_uncertainty_reaches_gate(self):
        src = {"a": "Сервис должен вернуть талон."}
        result = analyze(src, [model_row("a", src["a"], assessment="review")], True)
        self.assertEqual(result["gate"], "REVIEW")
        self.assertEqual(result["requirements"][0]["criteria"]["verifiable"]["status"], "REVIEW")

    def test_one_get_mutation_preserves_extra_evidence_and_separate_claim(self):
        src = {"m": "| HTTP method | GET |", "u": "1. Удалить запись.", "c": "Общий контекст."}
        effect = model_row("m", "GET используется для удаления записи", refs=["m", "u", "c"],
                           kind="issue", category="http", severity="HIGH")
        other = dict(effect, summary="Нет описания ошибки авторизации.")
        result = analyze(src, [effect, other], True)
        first, second = result["findings"]
        self.assertEqual(first["detectors"], ["rule", "gemini"])
        self.assertEqual(first["core_refs"], ["m", "u"])
        self.assertEqual([s["anchor"] for s in first["source_refs"]], ["m", "u", "c"])
        self.assertEqual(second["reason"], other["summary"])
        self.assertEqual(result["candidate_count"], 3)

    def test_example_stays_out_of_all_deterministic_rules(self):
        src = {"a": "R-1. Проверить остаток.", "b": "```text", "c": "TBD",
               "d": "| HTTP method | GET |", "e": "1. Удалить запись.", "f": "```"}
        self.assertEqual(analyze(src, [], False)["findings"], [])

    def test_explicit_acceptance_reference_requires_unique_definition(self):
        src = {"a": "# Правила", "b": "R-8. Выдать квитанцию.", "c": "## Критерии приёмки",
               "d": "При выполнении R-8 клиент видит номер."}
        def references():
            return [e for e in analyze(src, [], False)["links"] if e["relation"] == "acceptance_reference"]
        self.assertEqual(references(), [{"from": "R-001", "to": "d", "relation": "acceptance_reference"}])
        src["e"] = "R-8. Записать время."
        self.assertFalse(references())

    def test_pipeline_accepts_real_schema_and_escapes_document_markdown(self):
        src = {"a": "R-1. Отобразить ![пример](https://example.org/example.png)."}
        text = src["a"].removeprefix("R-1. ")
        extracted = dict(ref="a", summary=text, action="Приведён результат.", assessment="grounded", criterion="verifiable")
        with patch("specguard.gemini_json", return_value={"requirements": [extracted], "findings": []}):
            rows = semantic(src)
        report = dict(analyze(src, rows, True), sources=src, manifest={})
        html = format_report(report, ".html")
        self.assertIn("MODEL_ASSESSED", html)
        self.assertNotIn("<img", html)
        self.assertEqual(json.loads(format_report(report, ".json"))["gate"], "READY")

    def test_invalid_reference_quarantines_one_record(self):
        src = {"a": "Сервис должен вернуть чек."}
        row = dict(ref="a", summary=src["a"], action="Чек указан.", assessment="grounded", criterion="verifiable")
        payload = {"requirements": [row, dict(row, ref="несуществующая строка")], "findings": []}
        with patch("specguard.gemini_json", return_value=payload), self.assertRaises(PartialReview) as caught:
            semantic(src)
        self.assertEqual(len(caught.exception.rejected), 1)
        kept, = caught.exception.rows
        self.assertEqual(kept["summary"], src["a"])

    def test_bounds_link_to_feasibility_and_override_model_praise(self):
        src = {"a": "Буфер максимум 2 байта.", "b": "Буфер минимум 12 байтов."}
        result = analyze(src, [model_row(k, v) for k, v in src.items()], True)
        self.assertEqual(result["gate"], "BLOCKED")
        for r in result["requirements"]:
            self.assertEqual(r["criteria"]["feasible"]["status"], "FAIL")
            self.assertIn("F-001", r["action"])

    @patch("specguard.semantic", side_effect=TimeoutError)
    def test_failed_hybrid_has_no_quality_metrics(self, _request):
        metrics = run(cloud=True, hybrid=True, suite="transfer")
        self.assertEqual(metrics["status"], "INCOMPLETE")
        self.assertEqual(metrics["completed"], 0)
        self.assertIsNone(metrics["precision"])
        self.assertIsNone(metrics["recall"])

    def test_unrelated_corpus_regression(self):
        metrics = run(suite="transfer")
        self.assertEqual((metrics["documents"], metrics["true_positive"], metrics["false_positive"],
                          metrics["false_negative"]), (8, 3, 0, 0))

    @patch("specguard.revision", return_value="a"*40)
    @patch("package_submission.revision", return_value="a"*40)
    def test_package_matches_input_and_preserves_previous_zip_on_failure(self, _checkout, _engine):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            doc, review, target = folder/"in.md", folder/"out.json", folder/"submission.zip"
            text = "Сервис должен выдать талон."
            doc.write_text(text, encoding="utf8")
            with patch("specguard.semantic", return_value=[model_row("P1L1", text)]):
                self.assertEqual(main(["validate", str(doc), "--allow-cloud", "--verify", "--output", str(review)]), 0)
            build_package(doc, review, target)
            with ZipFile(target) as archive:
                self.assertEqual(set(archive.namelist()), {"review.json", "requirements.md", "review.html", "specguard-source.zip"})
                self.assertEqual(archive.read("requirements.md"), doc.read_bytes())
            good = target.read_bytes()
            with patch("package_submission.revision", return_value="b"*40), self.assertRaisesRegex(ValueError, "Git SHA"):
                build_package(doc, review, target)
            self.assertEqual(target.read_bytes(), good)
            doc.write_text("Другой текст.", encoding="utf8")
            with self.assertRaisesRegex(ValueError, "Вход"):
                build_package(doc, review, target)
            self.assertEqual(target.read_bytes(), good)
            self.assertEqual(main(["validate", str(doc), "--output", str(review)]), 0)
            with self.assertRaisesRegex(ValueError, "завершённый прогон"):
                build_package(doc, review, target)
