"""Unit tests for statutory hierarchy parser.

Tests both official statutory excerpts and synthetic non-legal structure fixtures.
"""

import datetime

from ingestion.parser import parse_statutory_text


def test_parse_social_security_section_53_provisos():
    """Tests parsing of Section 53 of Code on Social Security 2020.

    Crucial check for Section 4.1 test case:
    Verifies that the Second Proviso (Fixed-Term Exception) is parsed as a distinct,
    structured provision preserving parent hierarchy.
    """
    sample_text = """
CHAPTER V
GRATUITY

Section 53. Payment of gratuity.
(1) Gratuity shall be payable to an employee on the termination of his employment after he has rendered continuous service for not less than five years:
Provided that in case of working journalist as defined in clause (f) of section 2 of the Working Journalists and Other Newspaper Employees (Conditions of Service) and Miscellaneous Provisions Act, 1955, the expression "five years" occurring in this sub-section shall be deemed to be three years:
Provided further that the completion of continuous service of five years shall not be necessary where the termination of the employment of any employee is due to death or disablement or expiration of fixed term employment or happening of any such event as may be notified by the Central Government.

(2) For every completed year of service or part thereof in excess of six months, the employer shall pay gratuity to an employee at the rate of fifteen days' wages:
Provided also that in the case of an employee employed on fixed term employment or a deceased employee, the employer shall pay gratuity on pro rata basis.
"""
    parsed = parse_statutory_text(
        text=sample_text,
        act_title="The Code on Social Security, 2020",
        source_doc_id="DOC-01",
        effective_from_date=datetime.date(2025, 11, 21),
        legal_status="In Force",
        notification_ref="S.O. 5319(E)",
    )

    prov_ids = [p.provision_id for p in parsed]
    assert "PROV-SS2020-S53-1" in prov_ids
    assert "PROV-SS2020-S53-1-P1" in prov_ids
    assert "PROV-SS2020-S53-1-P2" in prov_ids
    assert "PROV-SS2020-S53-2-P1" in prov_ids

    # Inspect Second Proviso specifically (Fixed Term Exception)
    p2 = next(p for p in parsed if p.provision_id == "PROV-SS2020-S53-1-P2")
    assert p2.clause == "Second Proviso"
    assert p2.provision_type == "Proviso (Statutory Exception / Waiver of 5-Year Rule)"
    assert p2.parent_provision == "Section 53(1)"
    assert "expiration of fixed term employment" in p2.provision_text
    assert p2.effective_from == datetime.date(2025, 11, 21)


def test_parse_posh_section_4():
    """Tests parsing of Section 4 of POSH Act 2013."""
    sample_text = """
CHAPTER II
CONSTITUTION OF INTERNAL COMMITTEE

Section 4. Constitution of Internal Committee.
(1) Every employer of a workplace shall, by an order in writing, constitute a Committee to be known as the "Internal Committee":
Provided that where the offices or administrative units of the workplace are located at different places or divisional or sub-divisional level, the Internal Committee shall be constituted at all administrative units or offices.
"""
    parsed = parse_statutory_text(
        text=sample_text,
        act_title="Sexual Harassment of Women at Workplace (Prevention, Prohibition and Redressal) Act, 2013",
        source_doc_id="DOC-03",
        effective_from_date=datetime.date(2013, 12, 9),
    )

    prov_ids = [p.provision_id for p in parsed]
    assert "PROV-POSH2013-S4-1" in prov_ids
    assert "PROV-POSH2013-S4-1-P1" in prov_ids

    main_rule = next(p for p in parsed if p.provision_id == "PROV-POSH2013-S4-1")
    assert main_rule.provision_type == "Mandatory Establishment Duty"


def test_parse_synthetic_structure_fixture_non_legal():
    """Synthetic structure fixture clearly labeled as NON-LEGAL FIXTURE.

    Validates parser robustness across arbitrary nested provisos and formatting.
    """
    synthetic_text = """
CHAPTER IX
SYNTHETIC BENCHMARK CHAPTER (NON-LEGAL FIXTURE)

Section 999. Synthetic Rule on Automated Processing.
(1) All robotic workers shall submit daily diagnostic logs:
Provided that in the case of micro-drones, the reporting interval shall be hourly:
Provided further that underwater exploration units are completely exempt from acoustic ping requirements.
"""
    parsed = parse_statutory_text(
        text=synthetic_text,
        act_title="Synthetic Benchmark Testing Act (Non-Legal Test Fixture)",
        source_doc_id="DOC-SYNTHETIC-99",
    )

    assert len(parsed) == 3
    assert parsed[0].provision_id == "PROV-ACT-S999-1"
    assert parsed[1].provision_id == "PROV-ACT-S999-1-P1"
    assert parsed[2].provision_id == "PROV-ACT-S999-1-P2"
    assert "underwater exploration units" in parsed[2].provision_text
