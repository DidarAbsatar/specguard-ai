"""Rebuild Markdown-like structure from a text PDF.

The rule layer reads headings (#), table rows (| a | b |) and list items line by line.
Plain PDF text extraction loses all three: wrapped lines split sentences, tables become
one cell per line and headings look like body text. This module restores them from
font sizes, bold runs, table ruling lines and vertical gaps. It returns one string per
page so anchors keep the P<page>L<line> form.
"""
import io
import re
from collections import Counter

TERMINAL = re.compile(r"[.!?:;»\"')\]]$")
LIST_START = re.compile(r"^(?:[•·▪◦‣●○■□–-]\s*|\d{1,3}[.)]\s+|[A-ZА-ЯЁ]{1,12}-\d+[.:]?\s)")
BULLET = re.compile(r"^[•·▪◦‣●○■□]\s*")


def _clean(text):
    text = re.sub(r"(?<=\w-)\n(?=\w)", "", (text or "").replace("|", "/"))
    return re.sub(r"\s+", " ", text).strip()


def _inside(word, boxes):
    cx = (word["x0"] + word["x1"]) / 2
    cy = (word["top"] + word["bottom"]) / 2
    return any(x0 - 1 <= cx <= x1 + 1 and top - 1 <= cy <= bottom + 1 for x0, top, x1, bottom in boxes)


def _bold(word):
    return bool(re.search(r"bold|black|heavy|semibold", word.get("fontname", ""), re.I))


def _lines(words):
    """Group words into visual lines by their top coordinate."""
    rows = []
    for word in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if rows and abs(rows[-1][0]["top"] - word["top"]) <= max(2.0, word["size"] * 0.3):
            rows[-1].append(word)
        else:
            rows.append([word])
    result = []
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        result.append(dict(
            top=min(w["top"] for w in row), bottom=max(w["bottom"] for w in row),
            x0=row[0]["x0"], size=max(round(w["size"], 1) for w in row),
            bold=all(_bold(w) for w in row), mono=all("mono" in w.get("fontname", "").lower() or
                                                     "courier" in w.get("fontname", "").lower() for w in row),
            text=_clean(" ".join(w["text"] for w in row))))
    return result


def pdf_pages(data):
    """Return Markdown-like text per page, or None when no characters are found."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        sizes = Counter(round(c["size"], 1) for page in pdf.pages for c in page.chars if c["text"].strip())
        if not sizes:
            return None
        body = sizes.most_common(1)[0][0]
        larger = sorted({s for s in sizes if s >= body * 1.12}, reverse=True)[:5]
        levels = {s: n for n, s in enumerate(larger, 1)}
        bold_level = min(len(levels) + 1, 6)

        pages, previous_table_cols = [], None
        for page in pdf.pages:
            items = []
            tables = page.find_tables()
            boxes = [t.bbox for t in tables]
            for n, table in enumerate(tables):
                rows = [[_clean(c) for c in row] for row in table.extract()]
                rows = [r for r in rows if any(r)]
                if not rows:
                    continue
                cols = len(rows[0])
                continuation = (n == 0 and previous_table_cols == cols and table.bbox[1] < page.height * 0.15)
                lines = []
                for i, row in enumerate(rows):
                    lines.append("| " + " | ".join(row) + " |")
                    if i == 0 and not continuation:
                        lines.append("| " + " | ".join("---" for _ in row) + " |")
                items.append((table.bbox[1], "table", lines))
                previous_table_cols = cols
            if not tables:
                previous_table_cols = None
            words = [w for w in page.extract_words(extra_attrs=["size", "fontname"], use_text_flow=False)
                     if not _inside(w, boxes)]
            for line in _lines(words):
                items.append((line["top"], "line", line))
            items.sort(key=lambda item: item[0])
            pages.append(items)

    out_pages, para, para_page = [], None, None
    out = [[] for _ in pages]

    def flush():
        nonlocal para
        if para:
            out[para_page].append(para["text"])
        para = None

    for p, items in enumerate(pages):
        for top, kind, value in items:
            if kind == "table":
                flush()
                out[p].extend(value)
                continue
            line = value
            text = line["text"]
            if not text:
                continue
            level = levels.get(line["size"])
            standalone_bold = (line["bold"] and line["size"] <= body * 1.05 and len(text) <= 100
                               and not TERMINAL.search(text) and not re.fullmatch(r"[\d\W]+", text))
            if level or standalone_bold:
                flush()
                out[p].append("#" * (level or bold_level) + " " + text)
                continue
            if line["mono"]:
                flush()
                out[p].append(text)
                continue
            starts_item = bool(LIST_START.match(text))
            if para and not starts_item and line["size"] == para["size"] and (
                    (p == para_page and top - para["bottom"] < line["size"] * 0.75)
                    or (p != para_page and not TERMINAL.search(para["text"]))):
                joiner = "" if re.search(r"\w-$", para["text"]) else " "
                para["text"] += joiner + text
                para["bottom"] = line["bottom"]
                continue
            flush()
            para = dict(text=BULLET.sub("* ", text), size=line["size"], bottom=line["bottom"])
            para_page = p
    flush()
    return ["\n".join(lines) for lines in out]
