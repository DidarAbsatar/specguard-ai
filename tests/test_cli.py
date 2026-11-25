import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import specguard


class ReviewTest(unittest.TestCase):
    def test_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "input.md"
            out = Path(tmp) / "out.md"
            src.write_text("Лимит: TBD", encoding="utf8")
            self.assertEqual(specguard.main(["validate", str(src), "--output", str(out)]), 0)
            report = out.read_text(encoding="utf8")
            for expected in ["REVIEW", "P1L1", "Лимит: TBD"]:
                self.assertIn(expected, report)

    @patch.dict("os.environ", {"GEMINI_MODEL": "test", "GEMINI_API_KEY": "test"})
    @patch("specguard.urlopen")
    def test_unknown_reference(self, remote):
        row = dict(kind="issue", refs=["invented"], summary="x", action="", impact="", scenario="")
        result = dict(candidates=[dict(finishReason="STOP", content=dict(parts=[dict(text=json.dumps([row]))]))])
        remote.return_value.__enter__.return_value.read.return_value = json.dumps(result)
        with self.assertRaises(ValueError):
            specguard.semantic({"P1L1": "x"})
