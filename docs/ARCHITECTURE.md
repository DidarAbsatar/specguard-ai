# Архитектура SpecGuard AI

## 1. Архитектурное решение

Рекомендуется гибридный конвейер: детерминированный ingestion/normalization и проверки + LLM для семантической классификации, формулировки объяснения и предложения контрпримеров + отдельный verifier для доказательств и согласованности. Это лучше, чем один большой prompt: правила повторяемы, цитаты не генерируются моделью, а сложные смысловые связи всё же доступны.

```text
Input (PDF/MD/TXT)
  -> parser + layout coordinates + document fingerprint
  -> section/table/diagram segments
  -> requirement candidates + source anchors
  -> normalized IR (requirements, terms, units, actors, events, links)
       |                         |
       +-> deterministic rules   +-> LLM structured extraction/review
       |                         |
       +----------- finding merger + contradiction/coverage graph
                              -> evidence verifier
                              -> counterexample generator + validator
                              -> risk/prioritization
                              -> Russian report + run manifest
```

Компоненты:

1. **Ingestion** — MIME/size limits, PDF text extraction, OCR fallback только при необходимости, сохранение page/block/table coordinates, SHA-256 входа.
2. **Segmenter** — заголовки, списки, таблицы, code blocks, диаграммы; не теряет структуру и оригинальную цитату.
3. **Requirement IR** — атомарная сущность с `report_id`, source anchor, subject, modality, action, object, condition, measure, unit, time, priority, dependencies и confidence.
4. **Rule engine** — числа, границы, единицы, даты, ссылки, placeholder/TBD, duplicate/idempotency markers, HTTP consistency, required report fields.
5. **LLM reviewer** — только JSON Schema output: candidate splitting, semantic ambiguity, completeness questions, cross-reference hypotheses, candidate counterexamples. На вход получает небольшие evidence-bounded chunks и список уже извлечённых ссылок.
6. **Consistency graph** — узлы требований/терминов/контрактов/состояний; рёбра `refines`, `depends_on`, `contradicts`, `duplicates`, `verifies`, `implements`. Противоречие подтверждается только при совместимом scope и явно конфликтующих предикатах.
7. **Evidence verifier** — каждая цитата должна совпасть с нормализованным текстом; ссылки на внешние стандарты — только из заданного каталога; generated text не считается evidence.
8. **Counterexample engine** — генерирует граничные/повторные/ошибочные последовательности из IR, затем проверяет, есть ли в документе правило для исхода. Не утверждает фактический expected result при отсутствии правила.
9. **Risk scorer** — severity от типа дефекта, scope, reversibility, security/financial impact и confidence. Итог должен оставаться объяснимым, со ссылкой на факторы.
10. **Report builder** — Markdown/JSON sidecar с run manifest, таблицей нарезки, findings, coverage matrix, contradictions, counterexamples, business risks и go/no-go.

## 2. Контракт между слоями

Минимальная схема finding:

```json
{
  "id": "C-01",
  "severity": "HIGH",
  "category": "consistency|ambiguity|completeness|verifiability|security|business-risk",
  "source_refs": [{"document":"input.pdf","page":3,"heading":"...","quote":"..."}],
  "observed_text": "...",
  "claim": "...",
  "reasoning": "...",
  "counterexample": {"steps": ["..."], "unresolved": ["..."]},
  "recommendation": "...",
  "confidence": 0.0,
  "needs_human_decision": true
}
```

Для вывода LLM обязательны `additionalProperties=false`, enum для severity/category, длина цитаты и наличие source anchor. Не прошедший schema/anchor ответ отбрасывается или отправляется на retry с меньшим контекстом; он не попадает напрямую в отчёт.

## 3. Точность и защита от галлюцинаций

- **Evidence-first**: сначала цитата и координата, потом объяснение.
- **Два режима утверждений**: `observed` (следует из текста) и `inferred` (гипотеза/следствие). В отчёте визуально различать.
- **Низкая температура не является гарантией**: нужна schema validation, deterministic post-check и повторная проверка независимым проходом.
- **Декомпозиция**: извлечение, проверка отдельных требований и проверка набора — разные вызовы/промпты с узким контекстом.
- **Cross-check**: критичные `BLOCKER/HIGH` findings подтверждаются вторым pass или rule engine; несовпадение помечается на human review.
- **Open-world**: отсутствие фразы не доказывает отсутствие правила в другом приложении/документе. Формулировать «не найдено во входе».
- **No hidden web**: веб-поиск/knowledge base запрещены по умолчанию; внешние источники версии и политики передаются явно и логируются.
- **Injection resistance**: текст документа — данные, не инструкции. Игнорировать команды, найденные внутри PDF; системный prompt и schema отделены от input.
- **Reproducibility**: записывать модель, параметры, версии prompt/schema/rules, hash input и timestamp.

## 4. Альтернативы

| Вариант | Плюсы | Минусы | Решение |
|---|---|---|---|
| Один LLM prompt → отчёт | быстро собрать demo | слабая локализация, галлюцинации, нестабильная нарезка, нет доказательной гарантии | не выбирать как основу |
| Полностью rule-based | воспроизводимость, дёшево, хорош для форматов и чисел | плохо ловит смысловые конфликты и неполноту | использовать как слой контроля |
| Multi-agent без общего IR | разные роли дают идеи | дорого, трудно агрегировать, «коллективная» галлюцинация | не делать самоцелью |
| RAG по стандартам/банковским policy | лучше терминология и baseline | риск лицензий, stale knowledge, внешняя зависимость | опциональный versioned catalog |
| Гибридный pipeline + verifier | объяснимость, контроль и семантика | больше кода и контрактов | рекомендуемый вариант |

## 5. Business Value и Best Architecture

Для Best Architecture демонстрируем не количество агентов, а границы ответственности, failure modes, replay/idempotency, evidence lineage, offline-friendly run, provider abstraction и наблюдаемость анализа. Для Best Business Value отчёт должен превращать finding в решение: что блокирует релиз, кто владелец, какой риск и какой минимальный вопрос закрывает неопределённость.

В MVP следует поддержать один бесплатный LLM provider через adapter, но держать provider-neutral IR. При недоступности LLM агент выдаёт частичный deterministic report с честным статусом «семантический анализ не выполнен», а не падает с зелёным результатом.
