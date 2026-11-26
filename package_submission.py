"""Assemble the BCC hand-in from a completed run and the matching checkout."""
import argparse
import getpass
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

from reporting import format_report
from provenance import revision
from specguard import ENGINE, VERSION, build_id, extract, main as validate_cli, provider_name

ROOT = Path(__file__).resolve().parent


def build_package(document, report_path, output):
    if output.suffix.lower() != ".zip" or output.resolve() in {document.resolve(), report_path.resolve()}:
        raise ValueError("Укажите отдельный ZIP для комплекта.")
    report_bytes = report_path.read_bytes()
    run = json.loads(report_bytes)
    manifest = run["manifest"]
    if (manifest["Семантическая проверка"] != "выполнена"
            or manifest["Сверка цитат"] not in {"выполнена", "нет кандидатов"}):
        raise ValueError("Для сдачи необходим завершённый прогон с --allow-cloud --verify.")
    document_bytes = document.read_bytes()
    if hashlib.sha256(document_bytes).hexdigest() != manifest["SHA-256"] or extract(document) != run["sources"]:
        raise ValueError("Вход отличается от документа в отчёте.")
    for finding in run["findings"]:
        if not finding["source_refs"] or any(run["sources"].get(s["anchor"]) != s["quote"] for s in finding["source_refs"]):
            raise ValueError("Цитата замечания расходится с исходником.")
    names = [*ENGINE, "pyproject.toml", "setup.py", "package_submission.py", "benchmark.py", "README.md", "AGENTS.md",
             ".gitignore", ".gitattributes", ".env.example", ".github/workflows/tests.yml"]
    for pattern in ("docs/*.md", "tests/test_*.py", "examples/retention/*.md"):
        names.extend(p.relative_to(ROOT).as_posix() for p in sorted(ROOT.glob(pattern)))
    files = {n: (ROOT / n).read_bytes() for n in names}
    fingerprint = build_id(files)
    if manifest["Версия"] != VERSION or manifest["Сборка"] != fingerprint:
        raise ValueError("Версия исходников или отпечаток движка отличается от паспорта.")
    commit = revision(ROOT, fingerprint)
    if not commit or commit != manifest.get("Git SHA"):
        raise ValueError("Git SHA прогона должен совпадать с проверенной версией исходников.")
    files["_specguard_release.py"] = f"# {commit} {fingerprint}\n".encode("ascii")
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


def run_and_package(document, output):
    if output.suffix.lower() != ".zip" or output.resolve() == document.resolve():
        raise ValueError("Укажите отдельный ZIP для комплекта.")
    if not document.is_file():
        raise ValueError("Входной документ не найден.")
    output.parent.mkdir(exist_ok=True, parents=True)
    with tempfile.NamedTemporaryFile(prefix=output.stem + "-run-", suffix=".json", dir=output.parent, delete=False) as handle:
        review = Path(handle.name)
    try:
        code = validate_cli(["validate", str(document), "--allow-cloud", "--verify", "--output", str(review)])
        if code:
            if review.stat().st_size:
                print(f"Частичный отчёт сохранён в {review}", file=sys.stderr)
            return code
        build_package(document, review, output)
        review.unlink()
        return 0
    finally:
        if review.exists() and not review.stat().st_size:
            review.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("report", type=Path, nargs="?", help="JSON завершённого прогона")
    parser.add_argument("--allow-cloud", action="store_true", help="Передать документ выбранной облачной модели и собрать ZIP")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.allow_cloud == bool(args.report):
        parser.error("Выберите сохранённый JSON или новый прогон с --allow-cloud.")
    try:
        if args.allow_cloud:
            os.environ.setdefault("GEMINI_MODEL", "gemini-3.5-flash")
            if provider_name() == "gemini" and not os.environ.get("GEMINI_API_KEY") and sys.stdin.isatty():
                os.environ["GEMINI_API_KEY"] = getpass.getpass("Ключ Gemini (ввод скрыт): ")
                print("Ввод завершён. Дождитесь результата обращения к Gemini.", flush=True)
            code = run_and_package(args.document, args.output)
            if code:
                print("Запуск завершён. Для новой попытки запустите команду сборки ещё раз.", file=sys.stderr)
                return code
        else:
            build_package(args.document, args.report, args.output)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Комплект не собран: {exc}", file=sys.stderr)
        return 1
    print(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
