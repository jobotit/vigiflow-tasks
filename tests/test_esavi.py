"""Reading an ESAVI report, tested against a fake form.

The ESAVI form holds the same workbook columns as an ICSR under different
field ids. On 14-09-2026 the first ESAVI link in a list came back with its type,
patient, establishment, drugs and severity all empty, because the scraper only
knew the ICSR ids. Every value below is invented.
"""

from datetime import date

from vigiflow_tasks.report_scraper import _suspect_names, scrape_report


class Field:
    """One element on the fake form. ``None`` means the element is not there."""

    def __init__(self, value):
        self.value = value

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def count(self):
        return 0 if self.value is None else 1

    def is_visible(self):
        return self.count() > 0

    def input_value(self):
        return self.value

    def inner_text(self):
        return self.value or ""

    def locator(self, _):
        return Field(None)


class FormPage:
    """A form with no click method at all, so any click fails the test."""

    def __init__(self, fields):
        self.fields = fields

    def locator(self, selector):
        return Field(self.fields.get(selector.lstrip("#")))

    def goto(self, *_, **__):
        pass

    def wait_for_load_state(self, *_, **__):
        pass

    def wait_for_timeout(self, *_):
        pass

    def evaluate(self, *_):
        # The authority's causality grid: two verdict cells, neither filled.
        return {"cells": 2, "filled": 0, "values": [], "methods": 1, "detail": []}


def _esavi(**overrides):
    fields = {
        "body": "VigiFlow DIGEMID PE-DIGEMID-399999001 ESAVI",
        "aefiReportingIdNumber": "P-12 ABC CENTRO ESAVI",
        "dateOfMostRecentInformationForThisReportDay": "3",
        "dateOfMostRecentInformationForThisReportMonth": "9",
        "dateOfMostRecentInformationForThisReportYear": "2026",
        "reportersInstitution": "HOSPITAL EJEMPLO",
        "healthFacilityName": "CENTRO DE SALUD EJEMPLO",
        "reportersCity": "",
        "reportersStateOrProvince": "",
        "patientCity": "MODERADO",
        "patientStateOrProvince": "LIMA",
        "patientInitials": "A.B.C",
        "patientName": "Nombre Completo Ejemplo",
        "nameOfVaccine_0": "VACUNA A",
        "drugNameWHODrug_0": "VACCINE A CODED",
        "drugRole_0": "Sospechoso",
        "nameOfVaccine_1": "VACUNA B",
        "drugNameWHODrug_1": "",
        "drugRole_1": "Concomitante",
        "nameOfVaccine_2": "",
        "drugNameWHODrug_2": "VACUNA C CODED",
        "drugRole_2": "",
    }
    fields.update(overrides)
    return FormPage(fields)


def _read(page):
    return scrape_report(page, "https://vigiflow.who-umc.org/aefiform/guid")


def test_an_esavi_report_is_read_from_its_own_fields_without_a_click():
    scraped = _read(_esavi())
    fields = scraped.fields

    assert scraped.ok
    assert scraped.unopened == []
    assert fields["id_codigo"] == "PE-DIGEMID-399999001"
    assert fields["codigo_ipress"] == "P-12 ABC CENTRO ESAVI"
    assert fields["tipo_reporte"] == "ESAVI"
    assert fields["fecha_recepcion_reciente"] == date(2026, 9, 3)
    assert fields["fecha_notificacion"] is None
    assert fields["paciente"] == "A.B.C"
    assert fields["eess"] == "HOSPITAL EJEMPLO"
    assert fields["gravedad"] == "MODERADO"
    assert fields["medicamentos_sospechosos"] == ["VACUNA A", "VACUNA C CODED"]
    assert fields["_clinic_assessed"] is False


def test_the_patients_full_name_is_never_read():
    """The workbook carries a nickname only."""
    scraped = _read(_esavi(patientInitials=""))
    assert scraped.fields["paciente"] is None
    assert "Nombre Completo Ejemplo" not in str(scraped.fields)
    assert "paciente" in scraped.missing


def test_the_health_facility_fills_eess_only_when_the_institution_is_empty():
    scraped = _read(_esavi(reportersInstitution=""))
    assert scraped.fields["eess"] == "CENTRO DE SALUD EJEMPLO"


def test_severity_in_the_notifiers_address_comes_before_the_patients():
    scraped = _read(_esavi(reportersCity="LEVE"))
    assert scraped.fields["gravedad"] == "LEVE"


def test_a_real_place_in_the_patients_city_is_not_taken_for_severity():
    scraped = _read(_esavi(patientCity="SAN ISIDRO", patientStateOrProvince="LIMA"))
    assert scraped.fields["gravedad"] is None


def test_the_type_is_esavi_even_without_a_reporting_id():
    scraped = _read(_esavi(aefiReportingIdNumber=""))
    assert scraped.fields["tipo_reporte"] == "ESAVI"
    assert scraped.fields["codigo_ipress"] == "PE-DIGEMID-399999001"


def test_suspect_names_keep_order_and_drop_repeats_and_non_suspects():
    entries = [
        ("VACUNA A", "CODED A", "Sospechoso"),
        ("VACUNA A", "CODED A", "Sospechoso"),
        ("VACUNA B", None, "Concomitante"),
        (None, "CODED C", None),
        ("Falta el nombre del medicamento", None, "Sospechoso"),
    ]
    assert _suspect_names(entries) == ["VACUNA A", "CODED C"]
