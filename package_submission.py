"""Assemble the BCC hand-in from a completed run and the matching checkout."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

from reporting import format_report
from specguard import VERSION, extract

ROOT = Path(__file__).resolve().parent
ENGINE = ("specguard.py", "quality.py", "assessment.py", "reporting.py")


def build_package(document, report_path, output):
    if output.suffix.lower() != ".zip" or output.resolve() in {document.resolve(), report_path.resolve()}:
        raise ValueError("Укажите отдельный ZIP для комплекта.")
    report_bytes = report_path.read_bytes()
    run = json.loads(report_bytes)
    manifest = run["manifest"]
    if (manifest["Семантическая проверка"] != "выполнен"
            or manifest["Сверка цитат"] not in {"выполнена", "нет кандидатов"}):
        raise ValueError("Для сдачи необходим завершённый прогон с --allow-cloud --verify.")
    document_bytes = document.read_bytes()
    if hashlib.sha256(document_bytes).hexdigest() != manifest["SHA-256"] or extract(document) != run["sources"]:
        raise ValueError("Вход отличается от документа в отчёте.")
    for finding in run["findings"]:
        if not finding["source_refs"] or any(run["sources"].get(s["anchor"]) != s["quote"] for s in finding["source_refs"]):
            raise ValueError("Цитата замечания расходится с исходником.")
    names = [*ENGINE, "pyproject.toml", "package_submission.py", "benchmark.py", "README.md", "AGENTS.md",
             ".gitignore", ".env.example", ".github/workflows/tests.yml"]
    for pattern in ("docs/*.md", "tests/test_*.py", "examples/retention/*.md"):
        names.extend(p.relative_to(ROOT).as_posix() for p in sorted(ROOT.glob(pattern)))
    files = {n: (ROOT / n).read_bytes() for n in names}
    fingerprint = hashlib.sha256(b"".join(files[n].replace(b"\r\n", b"\n") for n in ENGINE)).hexdigest()[:16]
    if manifest["Версия"] != VERSION or manifest["Сборка"] != fingerprint:
        raise ValueError("Версия исходников или отпечаток движка отличается от паспорта.")
    src = io.BytesIO()
    with ZipFile(src, "w", ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    output.parent.mkdir(exist_ok=True, parents=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
            archive.writestr("specguard-source.zip", src.getvalue())
            archive.writestr("requirements" + document.suffix.lower(), document_bytes)
            archive.writestr("review.json", report_bytes)
            archive.writestr("review.html", format_report(run, ".html"))
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        build_package(args.document, args.report, args.output)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f"Комплект не собран: {exc}\n")
    print(args.output)
