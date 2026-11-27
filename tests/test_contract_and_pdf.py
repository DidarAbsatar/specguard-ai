import unittest
from pathlib import Path

from contract_rules import contract_findings
from quality import analyze
from specguard import read_document

FIXTURES = Path(__file__).parent / "fixtures"


def blocks_of(text):
    return {f"P1L{n}": line.strip() for n, line in enumerate(text.splitlines(), 1) if line.strip()
            and not set(line.strip()) <= set("|:- ")}


# Synthetic contract from another domain: deposit statements, not the hackathon case.
BROKEN = """## Выписка API
### Тело запроса
* Content-Type: application/json
* Тело запроса не используется.
### Параметры запроса
| Parameter | Format | Description |
| --- | --- | --- |
| `period` | integer | Месяцев |
### Ответ
Успешный результат 200 или 204.
| Parameter | Format | Description |
| --- | --- | --- |
| `period` | string | Месяцев |
### Статусы
**200.** Выписка сформирована.
**422.** Параметры запроса заполнены неверно.
#### 200. Successful — Accepted
```json
{"status":"FAILED","message":"Период слишком длинный"}
```
#### 422. Unsuccessful — Unprocessable
Для закрытого вклада возвращается 410.
"""

CLEAN = """## Выписка API
### Тело запроса
* Content-Type: application/json
### Параметры запроса
| Parameter | Format | Description |
| --- | --- | --- |
| `period` | integer | Месяцев |
### Ответ
| Parameter | Format | Description |
| --- | --- | --- |
| `period` | integer | Месяцев |
### Статусы
**200.** Выписка сформирована.
**422.** Параметры запроса заполнены неверно.
#### 200. Successful — OK
```json
{"status":"OK"}
```
#### 422. Unsuccessful — Unprocessable
```json
{"message":"Период слишком длинный"}
```
"""


class ContractRuleTests(unittest.TestCase):
    def test_broken_contract(self):
        reasons = [f[2] for f in contract_findings(blocks_of(BROKEN))]
        joined = "\n".join(reasons)
        self.assertIn("HTTP 204 упомянут", joined)
        self.assertIn("HTTP 410 упомянут", joined)
        self.assertIn("Раздел ответа 422 утверждает, что возвращается 410", joined)
        self.assertIn("«Accepted», которая соответствует 202", joined)
        self.assertIn("Под успешным статусом 200 приведён пример ответа с ошибкой", joined)
        self.assertIn("Content-Type", joined)
        self.assertIn("period (integer / string)", joined)

    def test_clean_contract_has_no_findings(self):
        self.assertEqual(contract_findings(blocks_of(CLEAN)), [])

    def test_quotes_are_exact(self):
        blocks = blocks_of(BROKEN)
        for finding in analyze(blocks, [], True)["findings"]:
            for ref in finding["source_refs"]:
                self.assertEqual(ref["quote"], blocks[ref["anchor"]])

    def test_no_contract_no_findings(self):
        self.assertEqual(contract_findings(blocks_of("Сервис должен вернуть 200 записей за 5 секунд.")), [])


class PdfLayoutTests(unittest.TestCase):
    def test_structure_restored(self):
        blocks, _ = read_document(FIXTURES / "layout.pdf")
        lines = list(blocks.values())
        self.assertIn("## Функциональные требования", lines)
        self.assertIn("## Критерии приемки", lines)
        wrapped = [l for l in lines if l.startswith("В-1.")]
        self.assertEqual(len(wrapped), 1)
        self.assertTrue(wrapped[0].endswith("обслуживание вклада."))
        self.assertIn("| Период 13 месяцев | Запросить выписку | Сообщение об ошибке |", lines)

    def test_requirements_mapped_from_pdf(self):
        blocks, _ = read_document(FIXTURES / "layout.pdf")
        sources = {r["source_id"] for r in analyze(blocks, [], False)["requirements"] if r.get("source_id")}
        self.assertTrue({"В-1", "В-2"} <= sources, sources)


if __name__ == "__main__":
    unittest.main()
