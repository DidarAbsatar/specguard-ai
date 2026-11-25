# План реализации SpecGuard AI

Это план следующего этапа; разработка в рамках текущего анализа не начиналась.

## Этап 0. Контракты и воспроизводимость

Зафиксировать CLI `specguard input.pdf report.md`, формат run manifest, JSON Schema IR/finding/report, уровни severity, классификатор observed/inferred и версию правил. Добавить `.env.example`, provider adapter, лимиты файлов/токенов и redaction policy. Критерий выхода: пустой скелет запускает pipeline и возвращает понятную ошибку для неподдержанного файла без вызова модели.

## Этап 1. Ingestion и трассируемость

Сделать PDF text/layout extraction, Markdown/TXT adapter, anchors page/heading/block/quote, document fingerprint и сегментацию таблиц/списков/code blocks. Сохранить оригинал цитаты и normalized text рядом. Проверки: PDF с таблицами, кириллица, переносы строк, дубликаты страниц, скан без text layer. OCR включать явно и маркировать как менее надёжный источник.

## Этап 2. Requirement IR и deterministic baseline

Выделить numbered/bulleted/table requirements, присвоить IDs без изменения исходного текста, извлечь числа/единицы/даты/HTTP tokens/ссылки. Реализовать правила для: неполных ссылок, TBD, конфликтующих status codes, GET-with-side-effect сигналов, mismatch body/query, inconsistent units, missing timezone/precision, missing idempotency fields, empty review blocks. У каждой проверки должен быть unit-тест на положительный и отрицательный пример.

## Этап 3. LLM bounded review

Сделать три узких вызова: (a) atomization/classification, (b) individual quality, (c) set-level consistency/coverage. Передавать только evidence chunks и IR; требовать JSON Schema и source refs. Добавить timeout/retry/backoff, token budget и provider adapter. Невалидный ответ не считать finding. Для кейса организаторов использовать fixture только в тестах, не в production rules.

## Этап 4. Граф согласованности и контрпримеров

Построить graph с терминами, требованиями, API и acceptance criteria. Реализовать contradiction candidate → deterministic scope check → second-pass confirmation → human-review flag. Counterexample templates: min/max, just-below/at/above threshold, month boundary, duplicate/reorder/late event, reversal, disabled, unauthorized/foreign resource, provider failure. Результат каждого примера должен различать `resolved_by_document`, `unresolved`, `requires_external_context`.

## Этап 5. Report и бизнес-слой

Сгенерировать русскоязычный Markdown: паспорт; mapping; per-requirement matrix; set-level findings; evidence; counterexamples; risk register; coverage map; go/no-go; top fixes. Добавить JSON sidecar для машинной проверки. Go/no-go — правило на findings и unresolved critical questions, не свободное мнение LLM.

## Этап 6. Верификация качества

Собрать размеченную выборку из синтетических документов и минимум нескольких независимых requirement documents; не подменять её кейсом организаторов. Разметить gold findings двумя ревьюерами и считать precision/recall по категориям, anchor accuracy, invalid-output rate, duplicate finding rate и latency/cost. Для малой выборки показывать доверительные интервалы или явно указывать, что оценка предварительная. Ручной adjudication сохранять.

## Этап 7. Demo и операционная готовность

Подготовить чистый запуск с бесплатным ключом, offline deterministic fallback, пример `.env`, инструкцию, sample output, commit/tag в паспорте. Перед сдачей прогнать на выданном документе только командой агента; приложить фактический output как artifact рядом со ссылкой, не вписывать вывод вручную.

## Порядок приоритетов

1. Доказательная трассируемость и корректная нарезка.
2. Явные детерминированные противоречия и контракты.
3. Русскоязычный actionable report.
4. Событийная/доменная семантика и контрпримеры.
5. LLM-полировка, дополнительные провайдеры и UI.

## Риски плана и меры

| Риск | Мера |
|---|---|
| LLM меняет формат ответа | strict schema, validator, retry, fallback |
| PDF теряет координаты | layout-aware extractor, quote checksum, OCR flag |
| false positive конфликтов | scope-aware graph, второй pass, human decision |
| бесплатный API недоступен/ограничен | provider adapter, cache по hash, deterministic partial report |
| утечка финансовых данных | локальная обработка, redaction, явный consent, no-store policy |
| overfitting к кейсу | synthetic/held-out corpus и запрет case-specific rules |
| красивый отчёт без бизнес-эффекта | risk owner, impact, next question и go/no-go policy |

## Definition of Done для будущего MVP

- Один командный запуск принимает путь входа и выхода.
- PDF проходит end-to-end с координатами; невалидный/сканированный input честно диагностируется.
- Отчёт содержит все обязательные разделы официального ТЗ и не содержит findings без evidence.
- Есть deterministic и LLM слои с видимым статусом каждого.
- Повторный запуск с тем же input/config даёт эквивалентную структуру, а manifest позволяет объяснить различия модели.
- Case-specific test fixture не участвует в runtime rules.
- Smoke, unit и golden tests проходят; измерения качества подписаны как измерения, а не как обещания.
