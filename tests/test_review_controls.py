import json
from pathlib import Path
import tempfile
import unittest

from quality import analyze
from reporting import format_report
from specguard import main


class ReviewControlTests(unittest.TestCase):
    def test_control_without_marks_preserves_conditional_note_and_blocks_release(self):
        blocks = {"r": "R-1. Напечатать билет.", "h": "| Примечание | Проверено | Критерий |",
                  "c": "| При отказе принтера применить резервный бланк | Да / Нет / Не требуется | Описан резерв печати |"}
        model = [dict(kind="requirement", refs=[k], summary=v.removeprefix("R-1. "), action="Проверено.")
                 for k, v in blocks.items()]
        run = analyze(blocks, model, True)
        control, = run["review_controls"]
        self.assertEqual(control["state"], "UNMARKED")
        self.assertEqual(control["header_ref"], "h")
        self.assertEqual(control["notes"][0]["text"], "При отказе принтера применить резервный бланк")
        self.assertEqual([r["refs"] for r in run["requirements"]], [["r"]])
        self.assertEqual(run["unclassified_refs"], [])
        self.assertEqual(run["gate"], "REVIEW")
        md = format_report(dict(run, manifest={}, sources=blocks), ".md")
        for s in ("C-001", "резервный бланк", "Отметка не выбрана"):
            self.assertIn(s, md)

    def test_distinct_marks_roles_and_no_inherited_layout_after_blank_line(self):
        src = {"P1L1": "| Check | Available | Reviewed |", "P1L3": "| Policy | Yes | No |",
               "P1L4": "| Clock | Yes | Yes |", "P1L5": "| Legacy | N/A | N/A |",
               "P1L6": "| Route | Yes | |", "P1L8": "| Document | Revision | Notes |",
               "P1L9": "| Handbook | 2 | Archive |"}
        run = analyze(src, [], False)
        self.assertEqual([c["state"] for c in run["review_controls"]],
                         ["NEGATIVE", "DECLARED", "NOT_APPLICABLE", "UNMARKED"])
        self.assertEqual(run["review_controls"][-1]["marks"][0]["state"], "DECLARED")
        self.assertIn("P1L9", run["unclassified_refs"])

    def test_markdown_headers_evidence_and_explicit_obligation_in_intro(self):
        with tempfile.TemporaryDirectory() as d:
            doc, report = Path(d)/"spec.md", Path(d)/"review.json"
            doc.write_text("# Общие сведения\nСервис должен выдать билет.\n"
                           "| Поле | Значение |\n|---|---|\n| Каталог схем | — |\n"
                           "Дата документа не указана.\nЕсли дата не указана, сервис должен вернуть ошибку.\n"
                           "| Базовый тариф | Ночной тариф |\n|---|---|\n| 8 | 4 |", encoding="utf8")
            self.assertEqual(main(["validate", str(doc), "--output", str(report)]), 0)
            run = json.loads(report.read_bytes())
            self.assertEqual(set(run["document_gaps"]), {"P1L5", "P1L6"})
            self.assertEqual(set(run["table_headers"]), {"P1L3", "P1L8"})
            refs = {k for r in run["requirements"] for k in r["refs"]}
            self.assertTrue({"P1L2", "P1L7"} <= refs)

    def test_code_example_remains_evidence_only(self):
        src = {"a": "```text", "b": "| Check | Status |", "c": "| Backup | No |", "d": "```"}
        self.assertFalse(analyze(src, [], False)["review_controls"])
