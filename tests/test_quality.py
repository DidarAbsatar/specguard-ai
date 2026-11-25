import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark import run
from quality import analyze
from specguard import main


class QualityTests(unittest.TestCase):
    def test_corpus(self):
        metrics = run()
        self.assertEqual((metrics["true_positive"], metrics["false_positive"], metrics["false_negative"]), (4,0,0))

    def test_gate_and_evidence(self):
        blocks = {"P1L1":"R-1. Размер не менее 12 байт.", "P1L2":"R-2. Размер не более 6 байт."}
        result = analyze(blocks, [], False)
        self.assertEqual(result["gate"], "BLOCKED")
        self.assertEqual(len(result["requirements"]), 2)
        for ref in result["findings"][0]["source_refs"]:
            self.assertEqual(ref["quote"], blocks[ref["anchor"]])
        self.assertIn("6 байт", result["findings"][0]["counterexample"])
        self.assertEqual(analyze({"a":"Сервис должен вернуть квитанцию."}, [], True)["gate"], "READY")

    def test_partial_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp)/"in.txt", Path(tmp)/"out.json"
            src.write_text("Сервис должен вернуть ответ.", encoding="utf8")
            with patch("local_review.review", side_effect=TimeoutError):
                code = main(["validate", str(src), "--output", str(out), "--ollama", "test"])
            self.assertEqual(code, 2)
            result = json.loads(out.read_text(encoding="utf8"))
            self.assertEqual(result["gate"], "REVIEW")
            self.assertEqual(len(result["requirements"]), 1)
