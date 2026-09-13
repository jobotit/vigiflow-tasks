"""Every VigiFlow selector in one place.

Keeping them here means a UI change is a one-file edit. Only what the
email-driven process touches is listed: sign-in, and the fields of one report.
The filter panel, the result list and the export went with the process that
used them.
"""

from __future__ import annotations

# --- Login ----------------------------------------------------------------
# VigiFlow is WHO-UMC's, and sign-in is delegated to Azure AD B2C. Opening the
# app redirects to whoumcprod.b2clogin.com, and a successful sign-in redirects
# back. Confirmed against the live instance: the form carries email, password
# and submit on one page, so there is no separate "next" step for the email.
LOGIN_USERNAME = "#email"
LOGIN_PASSWORD = "#password"
LOGIN_SUBMIT = "#next"

# Sign-in is judged by getting back to the application host rather than by an
# element. With a redirect flow that is the reliable signal: any element marker
# would be read on the identity provider's page while it is still showing.
APP_HOST = "vigiflow.who-umc.org"
IDP_HOST = "b2clogin.com"

# Checked once the browser is back on APP_HOST. Confirmed present on the
# signed-in search page of the DIGEMID instance.
LOGIN_SUCCESS_MARKER: str | None = "#newIcsr"

# B2C shows errors inline rather than changing page, so a rejected password
# looks like a page that simply did not move. These make the difference visible.
LOGIN_ERROR_MARKERS = (
    "#error",
    ".error.itemLevel[aria-hidden='false']",
    "text=Your password is incorrect",
    "text=We can't seem to find your account",
)

# --- Reaching one report --------------------------------------------------
# A report has its own address, and it survives a cold visit:
#     https://vigiflow.who-umc.org/dataentry/<guid>
# The <guid> is not the world-wide id and appears nowhere in the result list's
# markup, which is why the analyst's spreadsheet of links is the input: those
# links already carry the guid.
#
# Note what this URL is: the data entry form, and it opens editable. Every
# click on it goes through vigiflow.safety, and nothing is ever typed.
#
# The template is used for one thing: a cell holding a bare guid and no
# address, which an analyst pasting from the id column produces.
REPORT_URL_TEMPLATE = "https://{host}/dataentry/{guid}"

# --- Fields on the report form -------------------------------------------
# The application gives its inputs meaningful ids. The captions beside them
# are not wired to the inputs at all, so no label lookup finds them; the ids
# are both the only reliable handle and a steadier one.
#
# Dates are three boxes each, day then month then year, sharing a stem.
FIELD_TITLE = "#reportTitle"                       # column I
DATE_RECEIPT_LATEST = "dateOfMostRecentInformationForThisReport"   # column B
DATE_RECEIPT_INITIAL = "dateReportWasFirstReceivedFromSource"
DATE_REPORT = "dateOfInitialReport"                # column C, "Fecha del reporte"

FIELD_PATIENT_INITIALS = "#patientNameOrInitials"  # column J, Paciente section

# On the notifier tab. The city holds the severity by the standing agreement,
# which is why column P is read from an address field.
FIELD_NOTIFIER_ORG = "#reportersOrganisation_0"    # column E
FIELD_NOTIFIER_CITY = "#reportersCity_0"           # column P
FIELD_NOTIFIER_STATE = "#reportersStateOrProvince_0"

# Sections of the report, opened by name. Order matters to the scraper: the
# notifier tab has to be read before navigating elsewhere, because opening
# another section replaces that part of the page.
SECTION_PATIENT = "Paciente"
TAB_NOTIFIER = "Información del notificador"
