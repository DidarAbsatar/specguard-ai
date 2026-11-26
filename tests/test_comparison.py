import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from zipfile import ZipFile

from comparison import compare
from package_submission import run_and_package
from quality import analyze
from specguard import gemini_json, main


def blocks(*lines):
    return {f"P1L{i}": line for i, line in enumerate(lines, 1)}


class ComparisonTests(unittest.TestCase):
    lower = "T-1. Пауза не менее 3 минут."
    upper = "T-2. Пауза не более 60 секунд."

    def test_interval_fix_after_reordering_has_witness_and_both_quotes(self):
        past = blocks("# Заказ", self.lower, self.upper)
        edited = blocks("# Заказ", self.upper, "T-1. Пауза не менее 1 минуты.")
        report = compare(past, edited)
        event, = report["changes"]
        self.assertEqual(event["status"], "FIX_CONFIRMED")
        self.assertEqual(event["proof"], {"kind": "feasible_interval", "subject": "пауза", "unit": "секунд",
                         "before_min": 180, "before_max": 60, "after_min": 60, "after_max": 60, "witness": 60})
        self.assertEqual(event["after"], [{"anchor": k, "quote": edited[k]} for k in ("P1L3", "P1L2")])

    def test_deletion_reused_identifier_and_changed_scope_do_not_prove_a_fix(self):
        before = blocks("# Заказ", self.lower, self.upper)
        zero = self.lower.replace("3 минут", "0 минут")
        for after in (blocks("# Заказ", self.upper), blocks("# Доставка", zero, self.upper),
                      blocks("# Заказ", zero.replace("Пауза", "Срок"), self.upper),
                      blocks("# Заказ", zero, "# Заказ", self.upper),
                      blocks("# Заказ", zero, self.upper, zero)):
            with self.subTest(after=after):
                self.assertEqual(compare(before, after)["counts"]["CHECK"], 1)
                self.assertEqual(compare(before, after)["counts"]["FIX_CONFIRMED"], 0)

    def test_changed_interval_still_empty_and_new_signal(self):
        before = blocks(self.lower, self.upper)
        after = blocks("T-3. Срок TBD.", self.lower.replace("3 минут", "2 минут"), self.upper)
        events = compare(before, after)["changes"]
        self.assertEqual([(e["status"], e["category"]) for e in events],
                         [("PERSISTS", "bounds"), ("NEW_OBSERVATION", "placeholder")])
        self.assertNotEqual(events[0]["previous_id"], events[0]["current_id"])

    def test_unchanged_lines_without_ids_survive_line_shifts(self):
        before = blocks("Пауза минимум 2 минуты.", "Пауза максимум 1 минута.")
        after = blocks("Введение", *before.values())
        self.assertEqual(compare(before, after)["counts"]["PERSISTS"], 1)

    def test_changed_month_only_confirms_fix_for_same_acceptance_case(self):
        rule = "Месяц определяется по дате доставки."
        row = "| Доставка 28 ноября | Учесть 1 декабря | Декабрьский счётчик увеличен на 20 |"
        fixed = row.replace("Декабрьский", "Ноябрьский")
        before = blocks(rule, row)
        ok, = compare(before, blocks(rule, fixed))["changes"]
        self.assertEqual(ok["proof"], {"kind": "calendar_alignment", "event_month": 11,
                         "before_expected": 12, "after_expected": 11})
        for after in (blocks(rule, fixed.replace("20", "200")), blocks(rule, fixed, row),
                      blocks(rule, fixed.replace("28 ноября", "27 ноября")), blocks(rule),
                      blocks(rule, fixed.replace("увеличен", "не увеличен"))):
            with self.subTest(after=after):
                self.assertEqual(compare(before, after)["counts"]["FIX_CONFIRMED"], 0)

    def test_independent_headings_prevent_calendar_cross_match(self):
        src = blocks("# Одна услуга", "Месяц определяется по дате доставки.", "# Другая услуга",
                     "| Доставка 30 ноября | Учесть 1 декабря | Декабрьский счётчик вырос |")
        self.assertFalse(analyze(src, [], False)["findings"])

    def test_method_declaration_does_not_leak_into_another_endpoint(self):
        src = blocks("# API", "## Методы", "### Архив", "| HTTP method | GET |",
                     "### Заявки", "1. Сохранить заявку.")
        self.assertFalse(analyze(src, [], False)["findings"])
        joined = blocks("# API", "## Архив", "### Метаданные", "| HTTP method | GET |",
                        "### Логика", "1. Удалить запись.")
        self.assertEqual([f["category"] for f in analyze(joined, [], False)["findings"]], ["http"])

    def test_omitted_operator_never_counts_as_full_model_coverage(self):
        text = "Сумма ≥ 100 ₸."
        rows = [dict(kind="requirement", refs=["P1L1"], summary=s, action="Оценено.") for s in ("Сумма", "100 ₸")]
        self.assertEqual(analyze(blocks("R-1. " + text), rows, True)["gate"], "REVIEW")
        rows[0]["summary"] = text
        self.assertEqual(analyze(blocks("R-1. " + text), rows, True)["gate"], "READY")

    def test_cli_comparison_round_trip_and_protects_both_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            base, revised, data, html = [Path(folder) / n for n in ("a.md", "b.md", "result.json", "result.html")]
            base.write_text(self.lower + "\n" + self.upper, encoding="utf8")
            revised.write_text(base.read_text("utf8").replace("3 минут", "1 минута"), encoding="utf8")
            with patch("specguard.urlopen", side_effect=AssertionError("unexpected network request")):
                self.assertEqual(main(["compare", str(base), str(revised), "--output", str(data)]), 0)
                self.assertEqual(main(["render", str(data), "--output", str(html)]), 0)
            report = json.loads(data.read_text("utf8"))
            self.assertEqual(report["after"]["sha256"], hashlib.sha256(revised.read_bytes()).hexdigest())
            self.assertIn("Исправление доказано", html.read_text("utf8"))
            for source in (base, revised):
                content = source.read_bytes()
                self.assertEqual(main(["compare", str(base), str(revised), "--output", str(source)]), 1)
                self.assertEqual(source.read_bytes(), content)


class CallMetadataTests(unittest.TestCase):
    @patch.dict("os.environ", {"GEMINI_MODEL": "test", "GEMINI_API_KEY": "test"})
    @patch("specguard.time.sleep")
    @patch("specguard.urlopen")
    def test_one_retry_for_503_tracks_both_requests(self, remote, sleep):
        from unittest.mock import MagicMock
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "[]"}]}}]}).encode()
        remote.side_effect = [HTTPError("url", 503, "busy", {"Retry-After": "3"}, None), response]
        calls = []
        self.assertEqual(gemini_json("system", {}, {}, calls=calls), [])
        self.assertEqual([(c["attempt"], c["status"]) for c in calls], [(1, "error"), (2, "received_json")])
        sleep.assert_called_once_with(3)

    @patch.dict("os.environ", {"GEMINI_MODEL": "test", "GEMINI_API_KEY": "test"})
    @patch("specguard.time.sleep")
    @patch("specguard.urlopen")
    def test_persistent_503_is_bounded_and_auth_or_long_backoff_is_respected(self, remote, sleep):
        for code, headers, attempts in [(503, {}, 2), (503, {"Retry-After": "90"}, 1), (403, {}, 1), (429, {}, 1)]:
            with self.subTest(code=code, headers=headers):
                remote.reset_mock()
                sleep.reset_mock()
                remote.side_effect = [HTTPError("url", code, "error", headers, None) for _ in range(attempts)]
                with self.assertRaises(HTTPError):
                    gemini_json("system", {}, {})
                self.assertEqual(remote.call_count, attempts)
                self.assertEqual(sleep.call_count, attempts - 1)

    @patch.dict("os.environ", {"GEMINI_MODEL": "test", "GEMINI_API_KEY": "sensitive-test-value"})
    @patch("specguard.urlopen")
    def test_only_provider_counts_are_logged_without_document_or_credentials(self, remote):
        envelope = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "[]"}]}}],
                    "usageMetadata": {"promptTokenCount": 4, "totalTokenCount": 9}}
        remote.return_value.__enter__.return_value.read.return_value = json.dumps(envelope).encode()
        calls = []
        self.assertEqual(gemini_json("system", {"a": "private document"}, {}, calls=calls), [])
        self.assertEqual(calls[0]["usage"], envelope["usageMetadata"])
        self.assertEqual(calls[0]["status"], "received_json")
        self.assertNotIn("private document", str(calls))
        self.assertNotIn("sensitive-test-value", str(calls))
        remote.side_effect = TimeoutError
        with self.assertRaises(TimeoutError):
            gemini_json("system", {}, {}, stage="verification", calls=calls)
        self.assertEqual(calls[1]["stage"], "verification")
        self.assertEqual(calls[1]["status"], "error")
        self.assertNotIn("usage", calls[1])

    def test_submission_preserves_completed_zip_when_next_cloud_run_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            src, output = Path(folder)/"input.md", Path(folder)/"hand-in.zip"
            src.write_text("Сервис должен выдать квитанцию.", "utf8")
            row = dict(kind="requirement", refs=["P1L1"], summary=src.read_text("utf8"), action="Квитанция указана.")
            with patch("specguard.semantic", return_value=[row]):
                self.assertEqual(run_and_package(src, output), 0)
            with ZipFile(output) as z:
                self.assertEqual(json.loads(z.read("review.json"))["manifest"]["Сверка цитат"], "нет кандидатов")
            original = output.read_bytes()
            with patch("specguard.semantic", side_effect=TimeoutError):
                self.assertEqual(run_and_package(src, output), 2)
            self.assertEqual(output.read_bytes(), original)
            partial, = Path(folder).glob("hand-in-run-*.json")
            self.assertIn("не завершён", json.loads(partial.read_text("utf8"))["manifest"]["Семантическая проверка"])
