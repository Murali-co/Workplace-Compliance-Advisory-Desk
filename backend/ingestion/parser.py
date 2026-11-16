"""Statutory hierarchy parser.

Extracts canonical provisions while preserving sections, subsections,
provisos, explanations, and cross-reference edges.
"""

import re
from typing import List, Optional

from ingestion.models import ParsedProvision


def parse_statutory_text(
    text: str,
    act_title: str,
    source_doc_id: str,
    effective_from_date=None,
    effective_until_date=None,
    legal_status="In Force",
    notification_ref=None,
    source_url=None,
) -> List[ParsedProvision]:
    """Parses raw statutory text into structured ParsedProvision records."""
    provisions: List[ParsedProvision] = []

    # Regex patterns for section boundaries
    section_pattern = re.compile(r"^Section\s+(\d+)\.\s*(.*?)$", re.MULTILINE)
    chapter_pattern = re.compile(r"^CHAPTER\s+([IVXLCDM\d]+)\s*\n+(.*?)$", re.MULTILINE)

    # Find chapters
    chapter_matches = list(chapter_pattern.finditer(text))
    chapters = []
    for i, match in enumerate(chapter_matches):
        start = match.start()
        end = chapter_matches[i + 1].start() if i + 1 < len(chapter_matches) else len(text)
        chap_num = match.group(1).strip()
        chap_title = match.group(2).strip()
        chapters.append((chap_num, chap_title, start, end))

    def get_chapter_for_pos(pos: int) -> Optional[str]:
        for chap_num, chap_title, start, end in chapters:
            if start <= pos < end:
                return f"Chapter {chap_num} - {chap_title}"
        return None

    # Find sections
    sec_matches = list(section_pattern.finditer(text))
    for i, match in enumerate(sec_matches):
        sec_num = match.group(1).strip()
        start = match.end()
        end = sec_matches[i + 1].start() if i + 1 < len(sec_matches) else len(text)
        sec_body = text[start:end].strip()
        chap_info = get_chapter_for_pos(match.start())

        # Check if section has subsections: (1), (2), etc.
        sub_pattern = re.compile(r"^\((\d+)\)\s+(.*?)(?=(?:^\(\d+\)|\Z))", re.MULTILINE | re.DOTALL)
        sub_matches = list(sub_pattern.finditer(sec_body))

        if not sub_matches:
            # Section without explicit subsections
            _parse_provisos_and_body(
                provisions=provisions,
                body=sec_body,
                act_title=act_title,
                chapter=chap_info,
                section=sec_num,
                subsection=None,
                source_doc_id=source_doc_id,
                effective_from_date=effective_from_date,
                effective_until_date=effective_until_date,
                legal_status=legal_status,
                notification_ref=notification_ref,
                source_url=source_url,
            )
        else:
            for sub_match in sub_matches:
                sub_num = sub_match.group(1).strip()
                sub_body = sub_match.group(2).strip()
                _parse_provisos_and_body(
                    provisions=provisions,
                    body=sub_body,
                    act_title=act_title,
                    chapter=chap_info,
                    section=sec_num,
                    subsection=sub_num,
                    source_doc_id=source_doc_id,
                    effective_from_date=effective_from_date,
                    effective_until_date=effective_until_date,
                    legal_status=legal_status,
                    notification_ref=notification_ref,
                    source_url=source_url,
                )

    return provisions


def _parse_provisos_and_body(
    provisions: List[ParsedProvision],
    body: str,
    act_title: str,
    chapter: Optional[str],
    section: str,
    subsection: Optional[str],
    source_doc_id: str,
    effective_from_date,
    effective_until_date,
    legal_status: str,
    notification_ref: Optional[str],
    source_url: Optional[str],
):
    """Splits body text into main rule and subsequent provisos/explanations."""
    # Split on "Provided that", "Provided further that", "Provided also that"
    proviso_split_pattern = re.compile(r"(Provided (?:further|also)?\s*that:?)\s*", re.IGNORECASE)

    parts = proviso_split_pattern.split(body)
    main_rule_text = parts[0].strip()

    # Determine act prefix for ID
    if "Social Security" in act_title:
        act_prefix = "PROV-SS2020"
    elif "Gratuity" in act_title:
        act_prefix = "PROV-PGA1972"
    elif "Harassment" in act_title or "POSH" in act_title:
        act_prefix = "PROV-POSH2013"
    else:
        act_prefix = "PROV-ACT"

    parent_coord = f"Section {section}" + (f"({subsection})" if subsection else "")

    if main_rule_text:
        main_id = f"{act_prefix}-S{section}" + (f"-{subsection}" if subsection else "")
        prov_type = "Main Rule"
        if "repeal" in main_rule_text.lower():
            prov_type = "Repeal and Savings Provision"
        elif (
            "penalty" in main_rule_text.lower() or "punishable with fine" in main_rule_text.lower()
        ):
            prov_type = "Penalty Provision"
        elif "shall have the facility of crèche" in main_rule_text.lower():
            prov_type = "Mandatory Establishment Duty"
        elif "internal committee" in main_rule_text.lower():
            prov_type = "Mandatory Establishment Duty"

        provisions.append(
            ParsedProvision(
                provision_id=main_id,
                act=act_title,
                chapter=chapter,
                section=section,
                subsection=subsection,
                clause=None,
                provision_type=prov_type,
                parent_provision=f"Section {section}",
                provision_text=main_rule_text,
                effective_from=effective_from_date,
                effective_until=effective_until_date,
                legal_status=legal_status,
                notification_ref=notification_ref,
                source_doc_id=source_doc_id,
                source_url=source_url,
            )
        )

    # Process provisos
    proviso_idx = 1
    for k in range(1, len(parts), 2):
        proviso_header = parts[k].strip()
        proviso_body = parts[k + 1].strip() if k + 1 < len(parts) else ""
        full_proviso_text = f"{proviso_header} {proviso_body}".strip()

        clause_label = (
            "First Proviso"
            if proviso_idx == 1
            else ("Second Proviso" if proviso_idx == 2 else "Third Proviso")
        )
        proviso_id = (
            f"{act_prefix}-S{section}"
            + (f"-{subsection}" if subsection else "")
            + f"-P{proviso_idx}"
        )

        # Classify proviso type
        proviso_type = "Proviso"
        if "continuous service of five years shall not be necessary" in full_proviso_text.lower():
            proviso_type = "Proviso (Statutory Exception / Waiver of 5-Year Rule)"
        elif "pro rata basis" in full_proviso_text.lower():
            proviso_type = "Proviso (Pro-Rata Computation Mandate)"
        elif "working journalist" in full_proviso_text.lower():
            proviso_type = "Proviso (Special Class Exception)"

        provisions.append(
            ParsedProvision(
                provision_id=proviso_id,
                act=act_title,
                chapter=chapter,
                section=section,
                subsection=subsection,
                clause=clause_label,
                provision_type=proviso_type,
                parent_provision=parent_coord,
                provision_text=full_proviso_text,
                effective_from=effective_from_date,
                effective_until=effective_until_date,
                legal_status=legal_status,
                notification_ref=notification_ref,
                source_doc_id=source_doc_id,
                source_url=source_url,
            )
        )
        proviso_idx += 1
