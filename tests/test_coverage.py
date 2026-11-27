import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import NameObject, DictionaryObject, DecodedStreamObject

from quality import analyze
from specguard import PartialReview, complete_assessments, extract, main


def analyze_lines(*lines):
    blocks = {f"P1L{i}": s for i, s in enumerate(lines, 1)}
    reviewed = [dict(kind="requirement", refs=[k], summary=s, action="Проверено по тексту.")
                for k, s in blocks.items() if not s.startswith("#")]
    return analyze(blocks, reviewed, True)


class CoverageTests(unittest.TestCase):
    def test_question_about_goal_does_not_replace_its_assessment(self):
        goal = "Дать пассажиру возможность узнать об отмене до отправления."
        source = {"h": "## Бизнес-цели", "a": goal, "b": "Оператор должен зарегистрировать отмену."}
        rows = [dict(kind="requirement", refs=["b"], summary=source["b"], action="Указано действие."),
                dict(kind="question", refs=["a", "b"], summary="Срок регистрации и срок оповещения различаются.",
                     impact="Пассажир может опоздать.", action="Когда уведомляют пассажира?")]
        self.assertEqual(analyze(source, rows, True)["pending_requirements"], ["R-001"])
        reply = dict(id="R-001", criterion="verifiable", assessment="review", action="Как зафиксировать момент оповещения?")
        with patch("specguard.structured_json", return_value=[reply]) as ask:
            completed = complete_assessments(source, rows, set(), [])
        target, = ask.call_args.args[1]
        self.assertEqual((target["quote"], target["related_sources"]), (goal, {"b": source["b"]}))
        run = analyze(source, completed, True)
        req = run["requirements"][0]
        self.assertEqual((run["pending_requirements"], req["criteria"]["verifiable"]["status"]), ([], "REVIEW"))
        self.assertEqual((req["questions"], run["findings"], run["gate"]), (["Q-001"], [], "REVIEW"))
        with patch("specguard.structured_json") as ask:
            self.assertEqual(complete_assessments(source, completed, set(), []), completed)
            ask.assert_not_called()

    def test_followup_cannot_cover_sibling_with_duplicate_or_missing_id(self):
        source = {"h": "# Правила", "a": "Закрыть дверь. Сохранить отметку."}
        answer = dict(id="R-001", criterion="correct", assessment="unknown", action="Основание не указано.")
        with patch("specguard.structured_json", return_value=[answer, answer]), self.assertRaises(PartialReview) as caught:
            complete_assessments(source, [], set(), [])
        run = analyze(source, caught.exception.rows, False)
        self.assertEqual(run["pending_requirements"], ["R-002"])
        self.assertEqual(run["requirements"][0]["criteria"]["correct"]["status"], "UNKNOWN")
        self.assertTrue(any("R-002" in reason for reason in caught.exception.rejected))

    @patch.dict("os.environ", {"GEMINI_MODEL": "test-gemini"})
    def test_cloud_candidates_use_same_gemini_verifier(self):
        with tempfile.TemporaryDirectory() as folder:
            src, out = Path(folder) / "input.md", Path(folder) / "result.json"
            src.write_text("R-1. Ответить за 2 секунды.", encoding="utf8")
            req = dict(kind="requirement", refs=["P1L1"], summary="Ответить за 2 секунды.",
                       impact="", action="Срок указан.", scenario="")
            issue = dict(req, kind="issue", summary="Отсутствует срок.")
            with patch("specguard.semantic", return_value=[req, issue]), patch(
                "specguard.gemini_json", return_value=[{"id": 0, "keep": False, "reason": "Срок указан в цитате."}]
            ) as check:
                rc = main(["validate", str(src), "--output", str(out), "--allow-cloud",
                           "--verify"])
            self.assertEqual(rc, 0)
            check.assert_called_once()
            report = json.loads(out.read_text(encoding="utf8"))
            self.assertEqual(report["findings"], [])
            self.assertEqual(report["verification"][0]["kind"], "rejected")
            self.assertEqual(report["manifest"]["Модель сверки цитат"], "test-gemini")

    def test_unclassified_obligation_survives_successful_model_call(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "input.md"
            out = Path(folder) / "output.json"
            source.write_text("# Требования\nR-1. Отображать баланс.\n## Экран входа\nПри ошибке появляется сообщение.", encoding="utf8")
            with patch("specguard.semantic", return_value=[]):
                self.assertEqual(main(["validate", str(source), "--allow-cloud", "--output", str(out)]), 0)
            run = json.loads(out.read_text(encoding="utf8"))
            self.assertEqual(run["gate"], "REVIEW")
            self.assertEqual(run["unclassified_refs"], ["P1L4"])

    def test_distinct_parent_sections(self):
        run = analyze_lines("# Продажа", "## Лимиты", "Размер минимум 18 байт.",
                            "# Возврат", "## Лимиты", "Размер максимум 12 байт.")
        self.assertEqual(run["gate"], "READY")

    def test_scope_never_borrows_limits_from_code_example(self):
        run = analyze_lines("Размер минимум 18 байт.", "```text", "Размер максимум 12 байт.", "```")
        self.assertFalse(run["findings"])

    def test_numbered_steps_and_contract_metadata(self):
        run = analyze_lines("# Правила", "1. Проверить подпись. Сохранить запись.",
                            "## Метаданные", "| Поле | Значение |", "| **Authorization** | Bearer |")
        self.assertEqual([r["summary"] for r in run["requirements"]], [
            "Проверить подпись.", "Сохранить запись.", "| **Authorization** | Bearer |"])

    def test_bounds_convert_duration_only(self):
        self.assertEqual(analyze_lines("Пауза минимум 5 часов.", "Пауза максимум 40 минут.")["gate"], "BLOCKED")
        self.assertEqual(analyze_lines("Пауза минимум 60 минут.", "Пауза максимум 1 час.")["gate"], "READY")
        self.assertFalse(analyze_lines("Пауза минимум 5 месяцев.", "Пауза максимум 1 час.")["findings"])

    def test_march_and_may_are_distinct_without_duplicate_conflict(self):
        rule = "Месяц определяется по дате доставки."
        example = "| Доставка 2 мая | Учесть 1 марта | Мартовский счётчик увеличен |"
        self.assertEqual(len(analyze_lines(rule, example)["findings"]), 1)
        self.assertFalse(analyze_lines(rule, example.replace("Мартовский", "Майский"))["findings"])

    def test_pdf_empty_page_preserves_page_number(self):
        writer = PdfWriter()
        writer.add_blank_page(160, 160)
        page = writer.add_blank_page(160, 160)
        font = DictionaryObject({NameObject(k): NameObject(v) for k, v in
                                 {"/Type": "/Font", "/Subtype": "/Type1", "/BaseFont": "/Helvetica"}.items()})
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 10 Tf (R-1. Service must respond.) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pages.pdf"
            writer.write(path)
            self.assertIn("P2L1", extract(path))
