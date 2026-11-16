"""Transcribe selected complete sections from downloaded official statute PDFs.

Requires pdftotext. Keeps complete sections, including their qualifications;
normalizes PDF whitespace and removes page numbers/identified printer footnotes.
Original PDFs and hashes remain available for checking every quoted passage.
This is a bounded source corpus, not a complete or continuously updated legal library.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from ingestion.models import ParsedProvision  # noqa: E402

SOCIAL_URL = "https://www.indiacode.nic.in/bitstream/123456789/16823/1/aA2020-36.pdf"
POSH_URL = "https://www.indiacode.nic.in/bitstream/123456789/19302/1/sexual_harrassment_of_women_at_workplace_act_2013.pdf"


def read_pdf(path):
    content = subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True)
    pages = []
    offsets = []
    length = 0
    for number, page in enumerate(content.split("\f"), 1):
        lines = [
            line
            for line in page.splitlines()
            if not re.fullmatch(r"\s*\d+\s*", line) and "By Corrigenda dated" not in line
        ]
        clean = "\n".join(lines).replace("\uf02a", "") + "\n"
        offsets.append((length, number))
        pages.append(clean)
        length += len(clean)
    return "".join(pages), offsets


def page_at(offset, pages):
    return str(max(number for start, number in pages if start <= offset))


def sections(text):
    pattern = re.compile(r"(?m)^ {0,8}(\d+)\.[ \t]+([^—]{1,250}?)\.\s*—")
    matches = list(pattern.finditer(text))
    result = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.start() : end]
        # Chapter headings precede the next section; they are not part of this section.
        body = re.split(r"(?m)^\s*CHAPTER\s+[IVX]+\s*$", body)[0]
        result[int(match[1])] = (body, match.start())
    return result


def provision(identifier, act, section, body, page, since, notice, source_id, url, **extra):
    return ParsedProvision(
        provision_id=identifier,
        act=act,
        section=section,
        provision_type="Main Rule",
        provision_text=" ".join(body.split()),
        effective_from=since,
        legal_status="In Force",
        notification_ref=notice,
        source_doc_id=source_id,
        source_url=url,
        page_number=page,
        **extra,
    ).model_dump(mode="json")


def build(social_pdf, posh_pdf=None, posh_url=POSH_URL):
    text, pages = read_pdf(social_pdf)
    source = sections(text)
    act = "Code on Social Security, 2020"
    records = []
    for number in range(53, 73):
        body, offset = source[number]
        records.append(
            provision(
                f"OFFICIAL-SS2020-S{number}",
                act,
                str(number),
                body,
                page_at(offset, pages),
                "2025-11-21",
                "S.O. 5319(E), 21 November 2025; India Code commencement note, PDF p.8",
                "OFFICIAL-SS2020",
                SOCIAL_URL,
                chapter="Chapter V — Gratuity"
                if number <= 58
                else "Chapter VI — Maternity Benefit",
            )
        )
    definitions, offset = source[2]
    for number in (34, 88):
        start = re.search(rf"(?m)^ {{0,6}}\({number}\)\s", definitions)
        end = re.search(rf"(?m)^ {{0,6}}\({number + 1}\)\s", definitions)
        if not start or not end:
            raise ValueError(f"Definition {number} could not be isolated without truncation")
        records.append(
            provision(
                f"OFFICIAL-SS2020-S2-{number}",
                act,
                f"2({number})",
                definitions[start.start() : end.start()],
                page_at(offset + start.start(), pages),
                "2025-11-21",
                "S.O. 5319(E), 21 November 2025",
                "OFFICIAL-SS2020",
                SOCIAL_URL,
            )
        )
    if posh_pdf:
        text, pages = read_pdf(posh_pdf)
        source = sections(text)
        act = "Sexual Harassment of Women at Workplace (Prevention, Prohibition and Redressal) Act, 2013"
        for number in range(3, 29):
            body, offset = source[number]
            records.append(
                provision(
                    f"OFFICIAL-POSH2013-S{number}",
                    act,
                    str(number),
                    body,
                    page_at(offset, pages),
                    "2013-12-09",
                    "S.O. 3606(E), 9 December 2013",
                    "OFFICIAL-POSH2013",
                    posh_url,
                )
            )
    output = ROOT / "data" / "verified"
    output.mkdir(parents=True, exist_ok=True)
    (output / "legal_provisions.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    )
    sources = []
    for path, url, name in [(social_pdf, SOCIAL_URL, "social-security-2020.pdf")] + (
        [(posh_pdf, posh_url, "posh-2013.pdf")] if posh_pdf else []
    ):
        shutil.copyfile(path, output / name)
        sources.append(
            {
                "file": name,
                "source_url": url,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    (output / "provenance.json").write_text(
        json.dumps(
            {
                "sources": sources,
                "extraction": "pdftotext -layout; whitespace normalized; page numbers and identified printer footnote removed",
                "scope": "Complete Social Security Code sections 53–72 and definitions 2(34), 2(88); POSH sections 3–28 when supplied. Later amendments, rules, case law and historical statutes require separate sources.",
                "count": len(records),
            },
            indent=2,
        )
        + "\n"
    )
    print(json.dumps({"provisions": len(records), "output": str(output)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--social-security-pdf", type=Path, required=True)
    parser.add_argument("--posh-pdf", type=Path)
    parser.add_argument("--posh-url", default=POSH_URL)
    args = parser.parse_args()
    build(args.social_security_pdf, args.posh_pdf, args.posh_url)
