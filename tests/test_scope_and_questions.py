import unittest
from unittest.mock import patch

from benchmark import run as benchmark
from quality import analyze
from reporting import format_report
from specguard import semantic, verify_candidates


class ScopeAndQuestionTests(unittest.TestCase):
    def test_scope_preserves_evidence_and_normative_siblings(self):
        scope = "В разделе описаны выдача и учёт пропусков."
        rule = "Терминал печатает пропуск."
        blocks = {"a": scope + " " + rule, "b": "Раздел посвящён регистрации посетителей."}
        rows = [dict(kind="requirement", refs=["a"], summary=text, action="Проверить печать.")
                for text in (scope, rule)]
        for model_rows in ([], rows):
            with self.subTest(model=bool(model_rows)):
                run = analyze(blocks, model_rows, bool(model_rows))
                self.assertEqual([r["summary"] for r in run["requirements"]], [rule])
                self.assertEqual(run["document_context"], [{"ref":"a","text":scope}, {"ref":"b","text":blocks["b"]}])
                self.assertEqual(run["unclassified_refs"], [])
                self.assertEqual(run["pending_requirements"], [] if model_rows else ["R-001"])

    def test_intro_with_embedded_obligation_is_not_suppressed(self):
        blocks = {"h":"# Требования", "a":"В этом разделе описано, как терминал выдаёт пропуск.",
                  "b":"Документ описывает порядок, при котором терминал обязан закрыть проход.",
                  "c":"Печать пропусков находится за пределами этого документа."}
        run = analyze(blocks, [], False)
        self.assertEqual([r["refs"] for r in run["requirements"]], [["a"], ["b"]])
        self.assertEqual(run["document_context"], [{"ref":"c", "text":blocks["c"]}])

    def test_intro_roles_are_scored_per_sentence(self):
        actor = "Гость пришёл за пропуском."
        premise = "У гостя уже есть приглашение."
        behavior = "Терминал печатает пропуск."
        blocks = {"a": f"{actor} Здесь описана выдача пропусков.", "b": f"{premise} {behavior}"}
        context = [dict(ref=k, summary=s) for k, s in (("a", actor), ("b", premise), ("b", behavior))]
        with patch("specguard.structured_json", return_value=dict(requirements=[], findings=[], context=context)):
            rows = semantic(blocks)
        self.assertEqual(verify_candidates(rows, blocks), rows)
        run = analyze(blocks, rows, True)
        self.assertEqual([r["summary"] for r in run["requirements"]], [behavior])
        self.assertEqual([c["text"] for c in run["document_context"]], [actor, "Здесь описана выдача пропусков.", premise])
        unknown = analyze(blocks, [], False)
        self.assertIn(dict(ref="a", text=actor), unknown["unclassified_clauses"])
        self.assertIn("a", unknown["unclassified_refs"])

    def test_background_claim_cannot_remove_a_product_rule(self):
        lines = ["SR-1. Доступ открыт с полудня.", "Приложение выдаёт пропуск.",
                 "Вход разрешён только до полуночи."]
        for sentence in lines:
            src = {"a": sentence}
            with self.subTest(text=sentence):
                row = dict(kind="context", refs=["a"], summary=sentence.removeprefix("SR-1. "))
                run = analyze(src, [row], True)
                self.assertEqual(len(run["requirements"]), 1)
                self.assertFalse(run["document_context"])

    def test_scope_alone_does_not_make_a_document_ready(self):
        blocks = {"a":"Здесь рассматривается выпуск пропусков."}
        with patch("specguard.structured_json", return_value={"requirements": [], "findings": []}):
            self.assertEqual(semantic(blocks), [])
        run = analyze(blocks, [], True)
        self.assertEqual(run["requirements"], [])
        self.assertEqual(run["gate"], "REVIEW")
        self.assertEqual(run["unclassified_refs"], [])

    def test_question_preserved_without_inflating_defects_or_corroboration(self):
        blocks = {"a":"Буфер минимум 6 байтов.", "b":"Буфер максимум 2 байта."}
        issue = analyze(blocks, [], False)["findings"][0]
        question = dict(kind="question", category="bounds", provider="codex", refs=["a","b"],
                        action="Почему выбрана эта ёмкость?", summary="Цель ограничения не указана.",
                        impact="Нужно согласование владельца.", scenario="", rule_match=issue)
        run = analyze(blocks, [question, question], True)
        self.assertEqual(run["gate"], "BLOCKED")
        self.assertEqual(run["candidate_count"], 1)
        self.assertEqual([f["detectors"] for f in run["findings"]], [["rule"]])
        q, = run["questions"]
        self.assertEqual(q["id"], "Q-001")
        self.assertEqual([s["quote"] for s in q["source_refs"]], list(blocks.values()))
        self.assertEqual(run["requirements"][0]["questions"], ["Q-001"])
        self.assertEqual(run["decision"]["order"], ["F-001"])
        html = format_report(dict(run, sources=blocks, manifest={}), ".html")
        self.assertIn("Дефектов: 1 · Вопросов владельцу: 1", html)
        self.assertIn(q["question"], html)

    def test_question_alone_reaches_review_without_failing_criteria(self):
        blocks = {"a":"Сервис должен выдать пропуск."}
        req = dict(kind="requirement", refs=["a"], summary=blocks["a"], action="Проверить выдачу.")
        question = dict(kind="question", refs=["a"], summary="Цель требует уточнения.", action="Какова цель?",
                        impact="Уточнение владельцу.", scenario="", category="semantic")
        run = analyze(blocks, [req, question], True)
        self.assertEqual((run["gate"], run["findings"]), ("REVIEW", []))
        self.assertEqual(run["decision"]["next_step"], question["action"])
        self.assertEqual(run["set_criteria"]["consistent"]["status"], "UNKNOWN")
        with patch("specguard.semantic", return_value=[question]):
            score = benchmark(cloud=True)
        self.assertEqual(score["false_positive"], 0)

    def test_historical_combined_report_keeps_its_label(self):
        run = analyze({"a":"Раздел описывает выдачу пропусков."}, [], True)
        del run["questions"]
        text = format_report(dict(run, manifest={}, sources={}), ".md")
        self.assertIn("Замечаний: 0", text)
        self.assertNotIn("Вопросов владельцу: 0", text)
