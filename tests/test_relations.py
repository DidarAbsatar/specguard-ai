import unittest
from quality import analyze


class RelationTests(unittest.TestCase):
    def test_state_question_on_unrelated_domain(self):
        source = {"a":"Сервис отправляет максимум один талон за неделю.",
                  "b":"Повторная регистрация вызывает талон независимо от истории пациента."}
        result = analyze(source, [], False)
        self.assertEqual(result["gate"], "REVIEW")
        finding, = result["findings"]
        self.assertEqual(finding["category"], "state")
        self.assertIn("неделю", finding["counterexample"])

    def test_calendar_example(self):
        source = {"a":"Месяц рассчитывается по дате доставки.",
                  "b":"| Доставка 28 февраля | Зарегистрировать 1 марта | Мартовский счётчик увеличен |"}
        self.assertEqual(analyze(source, [], False)["findings"][0]["category"], "calendar")
        source["b"] = source["b"].replace("Мартовский","Февральский")
        self.assertFalse(analyze(source, [], False)["findings"])

    def test_examples_remain_evidence(self):
        source = {"a":"### Ответ", "b":"```json", "c":'{"field":"example"}', "d":"```"}
        self.assertEqual(analyze(source, [], False)["requirements"], [])
