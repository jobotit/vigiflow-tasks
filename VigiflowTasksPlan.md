# VigiFlow to Excel: automation plan

Automating the manual process of opening health reports in VigiFlow and
copying their contents into an Excel template. Built as a Sema4.ai Task
Package using the producer/consumer pattern.

The process is triggered by an email carrying a spreadsheet of report links,
and it replies to the sender with the finished workbook attached. Sections 1
onwards describe that process as it now stands.

Status: the pipeline runs end to end against production and the workbook
matches the real daily report column for column. What remains is the Control
Room setup.

**Sections 0 to 0l are the record of how the system was established**, and
they include two designs that were tried and superseded: the saved filter and
the bulk export. They are kept because they are why the current design looks
the way it does, and because they document what was measured against the live
system rather than assumed. The code for them is gone; section 0m onwards
describes what exists.

---

## 0. What the live system turned out to be

Confirmed by running the `Login check` task against production on 12-09-2026.
That task and the other diagnostics were removed once the process settled;
what they established is recorded here.

The instance is WHO-UMC's VigiFlow at `vigiflow.who-umc.org`, the DIGEMID
tenant, and the interface runs in Spanish. Reports are ICSRs, individual case
safety reports. The account sees 21,991 reports in total, 1,675 of them with
status Abierto.

**Sign-in is Azure AD B2C**, not a form on VigiFlow itself. Opening the app
redirects to `whoumcprod.b2clogin.com` and a successful sign-in redirects
back. The policy in the URL is `b2c_1_signinnomfa2withpasswordreset`, and the
"nomfa" in that name is why unattended running is possible at all. The form
carries email, password and submit on one page: `#email`, `#password`,
`#next`. Success is judged by arriving back on the application host rather
than by an element, because every page in the redirect chain looks loaded and
an element check fires on the wrong one. B2C also rejects a password without
navigating, so the client reads the inline error and reports it rather than
timing out with nothing to say.

Credentials come from the Control Room vault item `Vigiflow_C001_Credentials`,
whose keys are `VIGIFLOW_URL`, `VIGIFLOW_USERNAME` and `VIGIFLOW_PASSWORD`.

**The search results already carry most of the workbook.** The landing page
is the ICSR search, and its table shows the world-wide id, the delegated
organisation, patient initials, birth date, MedDRA reaction, drug name, the
initial receipt date, the last modified date and the report status. Against
the workbook that covers columns B, E, H, J and K. If the remaining columns
can be added to that table or come out of the export, the consumer may never
need to open a report at all, which would change the run from hours to
minutes.

**There is a Descargar button** in the header, `#exportToggle`. If it exports
the filtered result set with the fields we need, it replaces the whole
per-report scraping design with filter, download, transform. That is the
first thing to investigate in the next session, because it decides how much
of the consumer survives.

Two details that affect the mapping as written:

- The id shows as `PE-DIGEMID-399999001`, while column H of the workbook holds
  only the digits. Whatever reads the id has to strip the prefix.
- The result list pages at 20 rows by default and the page size is a control
  on the page. Aligning it with `batch_size` avoids paging entirely for a
  batch.

**Filters are pills, not a form.** "Anadir filtro" opens a chooser, each
active filter shows as a removable pill, and the account already has saved
filter sets under "Mis filtros". The current `FILTER_CONTROLS` entries are
placeholders set to None, because the form they assumed does not exist. A
saved filter may turn out to be a better handle than rebuilding the criteria
each run.

---

## 0b. The filter, confirmed against production

Verified end to end on 12-09-2026. Every step below was performed against the
live system by the `Filter check` task, which is the same code the producer
runs.

| Step | Control |
| --- | --- |
| Clear all filters | `#searchIcsrsParametersComponentClear` |
| Open Filtro | the button whose icon ligature is `filter_alt` |
| Expand Filtro avanzado | `#mat-expansion-panel-header-0` |
| Reporte tab | `#reportFiltersTab` |
| Estado del reporte | `#Status_0_0-input` Abierto, `_0_1` Bajo evaluación, `_0_2` Cerrado |
| Delegado a organización | `#delegatedToOrganisationSelect` opens the chooser |
| Sub-organisation groups | `#delegatedToOrganisationSelectToggle-button` |
| Aplicar filtro | `#searchIcsrsParametersComponentSearch` |

**The result.** With all three states and CRR Lima Centro selected, the search
goes from 21,991 reports to 2,626, and the active filter pills list every
establishment under that centre. Those establishment names match column E of
the sample workbook, which is the strongest confirmation available that this
is the right filter.

Four things about this UI cost real time and are worth knowing before touching
it again.

**Buttons carry their Material icon as text.** A button reads `filter_alt`
then `Filtro`. A case-insensitive `has-text('Filtro')` therefore also matches
"Limpiar todos los filtros", and an early version of the walk silently cleared
the filters while believing it had opened the panel. The icon ligature is the
most distinctive handle available.

**"Filtro avanzado" is an accordion.** Its text is visible while the section
is still collapsed, so expansion has to be judged by the tab strip inside it.

**The organisation chooser is a tree of expansion panels**, not a list. Each
row is a `mat-expansion-panel-header` holding the title and a checkbox side by
side, and the row text includes the count, as in "CRR Lima Centro (0/152)".
Clicking the header expands the group rather than selecting it, so only the
checkbox inside may be clicked. The checkbox id carries the organisation's own
numeric id, so it is found by reading the title and matching the name exactly.

**The sub-organisation toggle matters.** Off, ticking a regional centre selects
only the centre. On, it takes all 152 establishments under it, which is what
produces the result above.

### Safety

The search page also carries buttons that create a report, create an AEFI
report, reassign a case to another person, and overwrite the account's saved
filters. A selector that drifts onto one of those does real damage silently.

Every click goes through `assert_safe`, which reads the element's own id and
visible text and refuses anything on its denylist: by id, by id prefix for the
per-row controls, and by visible label. It reads the element rather than
trusting the selector that found it, because the selector is exactly what goes
wrong. Twenty unit tests cover it, and they need no browser.

The guard outlived the filter walk it was written for and now guards the
report page, which carries worse controls: Eliminar, Guardar, and the inline
remove icons on the data entry form. It lives in
`vigiflow_tasks/vigiflow/safety.py`. Its one whitelisted label, "Limpiar todos
los filtros", was removed with the filter walk, because an exception nothing
uses is only a hole.

---

## 0c. What Descargar turned out to be

Checked against production on 12-09-2026 with the normal filter applied, so
what follows describes the real result set.

Descargar is a menu (`#exportToggle`) with four options. The first,
`#exportToExcel`, downloads a workbook of the **entire filtered set**, not
the current page. It arrived as a direct browser download, not a queued job,
and took seconds.

The file has four sheets:

| Sheet | Rows | What it holds |
| --- | --- | --- |
| Resumen | 3 | print date and the report count |
| Reportes | one per report | 50 columns of report-level data |
| Medicamentos | one per drug per report | 31 columns, including the drug's role |
| Reacciones | one per reaction per report | 14 columns |

**It covers six of the ten workbook fields cleanly**, straight from a column:

| Workbook | Export source |
| --- | --- |
| B Fecha de recepción inicial | `Fecha de recepción inicial` |
| E EESS. | `Delegado a organización` |
| H ID CODIGO | `Número de identificación único mundial` |
| I código asignado por la IPRESS | `Título del reporte` |
| J PACIENTE | `Iniciales` |
| K to O MEDICAMENTO SOSPECHOSO | Medicamentos sheet, rows where `Rol del medicamento` is Sospechoso |

The Medicamentos sheet is better than the result list for the drug columns,
because it separates suspect drugs from concomitant ones. The list column
mixes them. It also settles how many columns are needed: of 2,599 reports with
a suspect drug, 2,289 name one and only two exceed the five columns K to O,
one with six drugs and one with twelve.

**Four fields are not reliably in the export**, and this is the part that
needs a person's answer rather than more code.

- **C FECHA DE NOT.** There is a `Fecha del reporte`, filled on 2,376 of 2,626
  rows. Plausibly the same thing, but unconfirmed.
- **F RAM / TAB / VIH / ESAVI.** `Tipo de reporte` holds Espontáneo, Otro or
  Reporte de estudio, a different vocabulary entirely. The type can sometimes
  be read off the end of the report title, which ends in RAM on 1,057 rows and
  ESAVI on 17, but the remaining titles end in things like HNAL, ALIA or ONC.
  Roughly 40 per cent, so not a rule.
- **G EV.** Nothing in the export resembles it.
- **P GRAVEDAD.** This one is worth knowing about. The values LEVE, MODERADO
  and GRAVE do appear, but in `Ciudad (sub-distrito)` and `Estado o provincia`,
  which are the notifier's address fields. Those fields also hold real places:
  `Ciudad` reads LIMA on 676 rows and MODERADA on 508. Somebody has been
  typing the severity into an address box. About half the rows carry a
  severity token that way, mixed in with genuine addresses.

### What this means for the design

The export removes most of the per-report scraping but not all of it. Two
routes follow, and the choice is the business's rather than ours.

**Route A, export led.** The producer downloads the export once, joins
Reportes to Medicamentos, and queues rows rather than ids. The consumer then
writes Excel with **no browser at all**, which makes it fast, cheap and far
less brittle. The four unresolved fields are either left blank for a person to
complete, or derived by an agreed rule.

**Route B, export plus targeted scraping.** As above, but the consumer still
opens the reports that need C, F, G or P, using the export for everything
else. Slower, and it still needs report-detail selectors, but complete.

Route A is much the better engineering if the business can accept the four
fields being derived or left blank. That is a question about how the register
is used, not about the robot.

---

## 0d. Whether a report can be opened by URL

Checked against production. The short answer is that the list has no link, but
reports do have addresses.

**The list offers no href.** The identifier cell is a `<span>` carrying
`id="openDataEntry_0"` and a dummy `href="#"`, with no `routerLink`. It is
JavaScript navigation dressed up as a link, so there is nothing to read a
destination from.

**A report does have its own address**, and it survives a cold visit:

```
https://vigiflow.who-umc.org/dataentry/a1b2c3d4-0000-4000-8000-000000000000
```

Navigating away and back to that address loaded the same report, so it is a
real, stable route rather than something that only works while the application
already holds the report in memory.

**But the key is a GUID, not the report id.** That GUID bears no relation to
`PE-DIGEMID-399999001`, and a search of the result list's markup found it
nowhere: not on the row, not on any attribute, not anywhere in the HTML. The
only way to learn a report's GUID is to open it once.

So the consumer cannot jump straight to a report it has never seen. Three
consequences follow.

- The first visit to any report must go through the list.
- Caching the identifier against its GUID would make every later visit direct,
  since the GUID belongs to the report and does not change. Worth doing if the
  same reports are ever revisited, which reruns and retries would.
- The producer is the natural place to capture GUIDs, because it is already
  walking the list. It would have to open each report to do so, which costs
  exactly what it saves, so this is only worth it if the consumer would open
  them anyway.

**One thing to be careful about.** The address is under `/dataentry/`, and the
report opens as an editable form, not a read-only view. Any code that opens
reports in bulk is sitting in a data entry screen on live pharmacovigilance
records. That argues for reading fields and never typing, and it is another
point in favour of the export led route in section 0c, which never opens a
report at all.

---

## 0e. The per-report PDF

Each report has its own download, behind the toolbar's download icon. It
offers two files: **PDF enmascarado**, with personal data masked, and **PDF
completo**. The full one is what the process would need, since the workbook
carries patient initials in column J.

The file for one report was three pages, 82 KB, and yielded 4,970 characters
of extractable text. It carries every section of the report: report
information, patient, narrative, reaction, medicament, tests, assessment and
notifier.

**It resolves one of the four gaps but not the others.**

| Workbook column | In the PDF? |
| --- | --- |
| C FECHA DE NOT. | yes, as `Fecha del reporte`, 25082026 on the sample |
| F RAM / TAB / VIH / ESAVI | no. `Tipo de reporte` reads Espontáneo, the same wrong vocabulary as the export |
| G EV. | no, nothing resembling it anywhere in the file |
| P GRAVEDAD | no. The label `Criterio (s) de Gravedad` is present but empty on the sample, and it is a seriousness criterion, not the LEVE / MODERADO / GRAVE scale |

So the PDF is a complete rendering of the report, and it settles column C. It
does not contain columns F, G or P, because **VigiFlow does not hold those
three fields at all**. That is the real conclusion from three independent
looks: the results list, the Excel export and now the report's own PDF all
lack them.

Columns F, G and P are therefore not data to be extracted. They are either
derived by the analysts from something else, or recorded outside VigiFlow.
Column F looks derivable from the report title, which ends in RAM on 1,057 of
2,626 rows and ESAVI on 17, but that is a convention rather than a rule.

### What this means

Nothing in VigiFlow can supply F, G and P, so no amount of scraping will find
them. The choice narrows to how the robot should handle three fields it
cannot know, which is a business decision rather than a technical one.

The PDF is still useful as an audit artefact: one small file per report, a
faithful rendering, and obtainable without reading the editable form field by
field. Whether that is worth downloading per report depends on whether the
register needs the evidence attached.

### A safety note on the report toolbar

The download sits between **Eliminar** and **Guardar** on the same toolbar.
Those delete the report and write the data entry form. Both are now refused by
the click guard, by id and by visible label, with tests covering each. No code
in this package may click them.

---

## 0f. The report form itself, field by field

The PDF is only a rendering, so before concluding anything the form itself was
walked: all eleven sections down the left and all seven tabs across the
bottom, including the per-reaction and per-medicament sub-sections and the
Vista general overview. Navigation only. Nothing was typed and no button that
saves, deletes, clears or adds was pressed.

That yields **52 distinct labelled fields** for the whole report. The full
inventory is written to `output/report-field-inventory.txt` on each run, so
this is checkable rather than something to take on trust.

**None of the three columns is there.** Not under another name, not on another
tab, not in the overview.

The reason for column P is worth understanding, because it is not an
oversight. VigiFlow records **seriousness** the ICH way: a yes/no field
`Grave`, plus a criteria checklist of Muerte, Amenaza de vida, Anomalía
congénita, Causó o prolongó hospitalización, Discapacidad and Otra condición
médica importante. On the sample report `Criterio (s) de Gravedad` reads
Muerte.

The workbook's column P wants LEVE / MODERADO / GRAVE, which is **severity**,
or intensity: how bad the reaction was. Seriousness and severity are different
things in pharmacovigilance, and Spanish blurs them because both use the word
grave. A non-serious reaction can be severe, and a serious one can be mild.

VigiFlow has no severity field. That is why the notifiers have been typing
LEVE and MODERADO into the notifier's address boxes, as section 0c found:
there is nowhere else for it to go.

### The conclusion, from four independent looks

| Source | F | G | P |
| --- | --- | --- | --- |
| Result list | no | no | no |
| Excel export | no | no | in address fields, about half the rows |
| Report PDF | no | no | no |
| The form itself, 52 fields | no | no | no |

Columns F, G and P are not VigiFlow data and no amount of scraping will
produce them. They are conventions the analysts apply, or are recorded
somewhere outside the system entirely.

That makes the export led route in section 0c the clear choice: nothing is
gained by opening reports, because the fields that would justify opening them
do not exist.

---

## 0g. The rules, as confirmed by the business

Every column is now accounted for. Six come from the export, three are rules
the analysts apply, and one is the run's own date.

| Col | Source | Rule |
| --- | --- | --- |
| A | the run | The date the work is done, so today |
| B | export | `Fecha de recepción más reciente`, not the initial one |
| C | export | `Fecha del reporte` |
| D | the run | A correlative. Arbitrary, so it starts at 1 |
| E | export | The notifier's own organisation, which is the reporting clinic |
| F | derived | The last word of the report title. "P82-26 CD RAM" gives RAM |
| G | derived | See below |
| H | export | The digits of the world-wide id, leading zeros kept |
| I | export | `Título del reporte`, falling back to the world-wide id when empty |
| J | export | `Iniciales` |
| K to O | export | Drugs whose role is Sospechoso, up to five |
| P | derived | LEVE / MODERADO / GRAVE out of the notifier's address fields |

### Column EV, and why it runs backwards

EV counts the analyses **the analyst performs**, which is the opposite of what
the name suggests.

- The notifying clinic has already filled in its causality assessment. The
  analyst has nothing to analyse, so the cell reads **S/E**.
- The clinic left it empty. The analyst does the analysis, so the cell takes
  the **next sequential number**.

The correlative therefore skips the S/E rows rather than numbering them. An
implementation that numbered the assessed ones instead would produce a column
full of plausible, wrong values that nobody would think to check, which is why
it has tests of its own.

This is the one field the export cannot supply. The causality matrix appears
in no sheet of it, so each report in the quota has to be opened and its
Evaluación section read. That costs a page load per report and is the only
reason the run touches a report at all.

Reading it correctly took two attempts. The section holds two kinds of
dropdown: `internalMethodOfAssessment_*` always reads "WHO-UMC Causality"
whether or not anyone has judged anything, while `internalResultOfAssessment_*`
holds the verdict and is empty until somebody makes the call. Counting the
first marks every report as assessed. Only the second answers the question.

### Leading zeros

Column H holds the digits of the world-wide id. Most are nine digits and
belong in the sheet as numbers, matching the file produced by hand. But ids
such as `PE-EXAMPLE-00009` exist, and writing those as a number would turn
00009 into 9 and lose the identifier. A value with a leading zero is written
as text, which is the only way Excel keeps the zeros.

---

## 0h. The first full run

Sixty reports from the corrected filter of 1,713, oldest first by last
modification, on 12-09-2026. Producer, consumer and reporter all passed. One
file, sixty rows.

| Column | Filled |
| --- | --- |
| A, B, D, E, G, H, J | 60 of 60 |
| I código IPRESS | 54 |
| K first suspect drug | 51 |
| P GRAVEDAD | 42 |
| F RAM / TAB / VIH / ESAVI | 38 |
| C FECHA DE NOT. | 30 |
| L, M, N further drugs | 4, 2, 1 |

The correlative runs 1 to 60 with no gap. Column EV shows 22 S/E, where the
clinic had already assessed causality, and 38 numbered 1 to 38 for the reports
the analyst must analyse. Every one was verified; none was left blank.

The earlier run against the wrong filter had thirteen unverified EV cells,
because the causality pass ran out of list pages before reaching the tail. It
did not recur here. The default is now safe either way: a report that cannot
be opened leaves EV blank rather than taking a number it has not earned.

---

## 0i. The filter was wrong, and how it was found

The first full run produced 2,626 reports where the business expects exactly
1,713, and the identifiers it wrote could not be found. Measured against the
live system:

| Count | Filter |
| --- | --- |
| 2,626 | delegated to the centre, sub-organisations included, all three states |
| 1,306 | as above, only Abierto and Bajo evaluación |
| **1,713** | **delegated to the centre only, all three states** |
| 1,642 | created by the centre, sub-organisations included |
| 1,304 | no state filter |

**The sub-organisation toggle must stay off.** Ticking CRR Lima Centro alone
selects reports delegated to the centre itself. Turning on "Activar para
seleccionar/deseleccionar grupos de suborganizaciones" also pulls in the 152
establishments under it, which are not the centre's work.

I had it on, reasoning from a screenshot that showed "(152/152)". The counts
say otherwise, and the counts are what the business recognises. A filter that
returns nearly a thousand reports too many is not a near miss: it produces a
register full of cases that belong to someone else, which is exactly what
happened.

**The ordering was wrong too.** The analysts do not re-sort the list. They
apply the filter and go to its **last page**, because the default order is by
last modification with the newest first. So the oldest work is the least
recently modified, not the earliest received. The run now orders by last
modification ascending, which selects the same set without paging to the end.

Both were things a screenshot could not settle and only a count could.

---

## 0j. Two more columns corrected

**Column E is the reporting clinic, not the delegated organisation.** Once the
filter selects one regional centre, `Delegado a organización` reads "CRR Lima
Centro" on all 1,713 rows, so using it wrote the same value into column E
sixty times over. The clinic is the notifier's own organisation, which has 169
distinct values across the filtered set and 37 across a run of sixty.

The export offers three organisation columns and they are not
interchangeable:

| Column | Distinct values | What it is |
| --- | --- | --- |
| Delegado a organización | 1 | the regional centre the filter selected |
| Organización (Notificador primario) | 169 | the clinic that reported, column E |
| Creado por organización | 50 | who keyed the report in |

The third is worth knowing about. It carries cleaner, fuller names, with
accents, where the notifier's own entry is whatever that person typed, so it
holds abbreviations such as INSNSB and HNAL alongside full names. If the
register is meant to read consistently, `Creado por organización` may be the
better source. The notifier's organisation is used because that is the field
the business pointed at, and it is a one line change if not.

**Column I falls back to the world-wide id.** About one report in seventeen
has no title, 127 of 1,713, and the business reads the identifier off the top
of the report instead.

---

## 0k. The saved filter, and a full extraction

The business keeps a filter under "Mis filtros" called "Lima Centro - Filtro".
Reusing it is better than rebuilding the criteria, because it cannot drift
from what they actually use, and it is one click rather than a dozen. Applied,
it returns 2,619 reports.

It is a modal listing each saved filter as a row of a `mat-table`, so it has
no `td` or `tr`; the name sits in a cell whose id follows
`myFiltersModalSelect_<index>`, and clicking that applies the filter. The next
cell holds a delete button, which the guard refuses by its label.

`saved_filter` is now a run parameter, defaulting to that filter. Set it to an
empty string to rebuild the criteria instead.

### Extracting everything

All 2,619 reports were extracted in one run: one export download, 53 batches
of 50, merged into a single file of 2,619 rows. The correlative runs 1 to
2,619 without a gap and column E holds 316 distinct clinics.

| Column | Filled |
| --- | --- |
| A, D, E, H, I | 100% |
| B, J | 99% |
| K first suspect drug | 95% |
| C | 90% |
| P GRAVEDAD | 85% |
| F RAM / TAB / VIH / ESAVI | 77% |
| L, M, N, O further drugs | 10%, 3%, under 1% |
| G EV. | 0%, see below |

**This scales because of the export.** Nine of the ten data columns come from
one download, so 2,619 reports cost no more browser work than 60 did. The
consumer then runs without a browser at all.

**Column EV does not scale, and was left empty.** It is the one field the
export cannot supply, so it needs the report opened. At roughly six seconds
each that is about four hours for 2,619 reports, against minutes for
everything else. The run was made with the causality pass off rather than
quietly spending half a day on it.

That leaves three ways forward, and the choice is the business's:

1. Accept EV blank on a full extraction and fill it only on the daily runs of
   sixty, where it costs about six minutes.
2. Run the causality pass once overnight for the whole backlog.
3. Decide EV is not needed for a bulk extraction at all.

---

## 0l. An on-demand list of links, and running on Linux

### The analyst's list

The analyst can hand over a spreadsheet of report links rather than relying on
the filter. One column, headed Links or similar:

```
https://vigiflow.who-umc.org/dataentry/<guid>
```

Those URLs are keyed by a GUID that is not the world-wide id and appears
nowhere in the export, so each listed report is opened once to learn which
report it is. The causality assessment for column EV is read during the same
visit, since the visit is the expensive part. Everything else then comes from
the export as usual.

The reader tolerates what a hand-made list contains: a missing header, a bare
GUID without the URL, a blank row, a row that is not a link, and the same
report listed twice. Each is skipped and named rather than failing the list.

**A listed report can fall outside the export.** The export contains what the
filter selected, so a report the analyst names from elsewhere has no data.
Those are reported by identifier rather than dropped silently.

Widening the export does not help, and this was tested. Clearing the filters
does not mean "every report": the application keeps a default state filter, so
an unfiltered export returned 1,669 reports where the saved filter returns
2,619. The saved filter is the widest export available. An unfiltered export
of all ~22,000 also exceeded a three minute download window, so it is not a
practical source either.

If on-demand lists routinely name reports outside the filter, the options are
to widen the saved filter, or to read those reports from their own pages,
which would need the report-detail selectors that nothing has needed so far.

### Linux

Nothing here needs Excel or a desktop, which was checked rather than assumed:

| Concern | Finding |
| --- | --- |
| Excel automation | none. No xlwings, win32com, COM or LibreOffice anywhere |
| Workbook writing | openpyxl, pure Python, writes the file directly |
| Template formatting | copied onto every row by openpyxl, verified at row 2,620 of a 2,619 row file |
| Windows-only imports | none |
| Hardcoded Windows paths in code | none. Only a work item payload, which is configuration |
| Platform branches | none |
| Display | the browser is headless by default |

On a bare Linux VM, Chromium's shared libraries are the one extra step:
`python -m playwright install-deps chromium`. `rcc` builds the rest from
`conda.yaml`, which pins only cross-platform packages, and `robot.yaml`
already lists a Linux environment file.

---

## 0m. The email-driven process

A second process, alongside the filter-driven daily one. An email with a
spreadsheet of report links starts it, and the finished workbook comes back to
whoever sent it.

```
  email + Links.xlsx
        |
        v
  +--------------+   one work item   +--------------+   rows   +--------------+
  |   PRODUCER   | ----------------> |   CONSUMER   | -------> |   REPORTER   |
  |  reads the   |   per link, so    |  reads ONE   |          |  workbook +  |
  |  attachment  |   each report is  |  report from |          |  reply email |
  +--------------+   a transaction   |  its page    |          +--------------+
                                     +--------------+
```

**Each link is a transaction.** One work item per report, so a report that
cannot be read fails on its own and is retried on its own, without touching
the others.

**The consumer uses no export.** An on-demand list can name any report, and
the export only ever holds what some filter selected. So each report yields
its whole row from its own page.

### Reading a report from its page

The fields have meaningful ids, and this matters: the captions beside them are
not wired to the inputs at all, so no label lookup finds them. An early version
read every section as empty for exactly that reason.

| Workbook | Field |
| --- | --- |
| B | `#dateOfMostRecentInformationForThisReport` Day/Month/Year |
| C | `#dateOfInitialReport` Day/Month/Year |
| E | `#reportersOrganisation_0`, on the notifier tab |
| I | `#reportTitle` |
| J | `#patientNameOrInitials`, in the Paciente section |
| P | `#reportersCity_0`, falling back to the state field |
| K to O | the left sidebar's MEDICAMENTO entries |
| EV | the causality matrix in the Evaluación section |
| F | derived from the title |
| H | read from the page header |

Every date is three boxes sharing an id stem, so a date is assembled from
Day, Month and Year rather than read from one control.

Order matters: the notifier tab sits at the foot of the report section, so it
has to be read before navigating anywhere else. Opening Paciente replaces that
part of the page and the tab is gone. That cost one debugging round.

The report PDF was considered and rejected. It has every label, but it renders
the notifier block and the medicament table as a block of labels followed by a
block of values, so reading them means counting positions.

### The reply

The sender, the file's name and the start time travel on every work item, so
the reporter can compose the reply without going back to the trigger. The
message reports the input file, links received, reports read, rows written,
start, finish and duration, plus a note for anything partial.

The workbook is a run artefact whichever way the send goes, so a failed email
never loses the work.

### Sending

Working, verified by a real message with the workbook attached.

The vault supplies `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURE`, `SMTP_USERNAME`
and `SMTP_PASSWORD`. `SMTP_SECURE` follows the convention the mail libraries
use, which is not "encrypted or not":

- **true** wraps the socket in TLS from the first byte. Port 465.
- **false** connects in the clear and upgrades with STARTTLS when the server
  offers it. Ports 587 and 25, and still encrypted in practice.

**The From address can differ from the account that signs in**, which is how
`the sending account` sends while `the sending account` authenticates. A
provider only allows this for an address the account owns or has configured as
an alias; Google rewrites the header otherwise. `VIGIFLOW_SMTP_REPLY_TO` sets
a Reply-To, since a no-reply From leaves nowhere to write back to.

**One credential trap, and it cost three attempts.** The App Password in the
vault belonged to one mailbox while `SMTP_USERNAME` named another. Google answers a password that belongs to another
account with the same 535 as a wrong one, so nothing in the error says which
of the two is at fault.

Two things now make that diagnosable without guessing. The check reports each
stage separately, because reaching the server, upgrading to TLS and signing in
fail for different reasons and want different fixes. And it reports the
password's *shape*, never its value: sixteen lowercase characters is a Google
App Password, anything else against Gmail is an account password and will be
refused. Here the shape was right, which is what pointed at the account rather
than the credential.

Spaces are also stripped from the password. Google displays an App Password as
four blocks of four, and pasted in as shown the spaces produce the same 535.

---

## 1. The process as automated

Today an analyst signs in to VigiFlow, opens each report on their list, and
retypes its contents into a spreadsheet. The robot does the same in three
steps, triggered by the analyst sending that list in an email.

**Producer.** Reads the spreadsheet attached to the triggering email and
queues one work item per link. Each item carries the link and the run context:
who to reply to, what the input file was called, when the run started, and how
many links there were. No browser, no credentials.

**Consumer.** Signs in once, then reads one report per work item straight from
its own page. One browser for the whole run rather than one per report;
signing in again for each would be the slowest thing the process could do.

**Reporter.** Collects the rows, assigns column EV across the whole run,
writes one workbook, and emails it back to whoever sent the list with a short
summary of the run.

```
  email + Links.xlsx
        |
        v
  +--------------+   one work item   +--------------+   rows   +--------------+
  |   PRODUCER   | ----------------> |   CONSUMER   | -------> |   REPORTER   |
  |  reads the   |   per link, so    |  reads ONE   |          |  workbook +  |
  |  attachment  |   each report is  |  report from |          |  reply email |
  +--------------+   a transaction   |  its page    |          +--------------+
                                     +--------------+
```

**Each link is a transaction.** One work item per report, so a report that
cannot be read fails on its own and is retried on its own, without touching
the others. That is the whole reason the producer explodes the list rather
than passing it along whole.

**No export.** An on-demand list can name any report, and the export only ever
holds what some filter selected. So each report yields its whole row from its
own page.

---

## 2. Selecting the work

**The analyst selects it.** This is the significant change from the earlier
design, and it removes the sharpest risk that design had.

The filter-driven version took the oldest sixty reports off a backlog with no
marker of what had already been done, so two runs on consecutive days would
take the same reports and write them twice. A person remembers where they
stopped; the robot did not. Guarding that needed a store of processed
identifiers.

With the analyst supplying the list, there is nothing to guard. The robot
processes exactly what it was sent, every time, and a report appears twice in
one run only if it appears twice in the spreadsheet, which the producer
already deduplicates.

The order of the workbook is the order of the spreadsheet. The producer stamps
each work item with its position in the list and the reporter sorts on that
before writing, so the rows come back in the order the analyst listed them
however the work items were scheduled.

---

## 3. The Excel template

Taken from the real file `REPORTES DEL VIGIFLOW DEL DIA 31-08-2026.xlsx`.
That file is a finished daily report, not a blank template, so the template
is that file with its 60 data rows removed. `scripts/make_template_from_sample.py`
does the stripping and preserves the header text, the blue fill, the medium
borders, the 75.75 row height, the column widths and the date formats. Re-run
it if the business changes the layout.

One sheet, `Hoja1`. Header on row 1, data from row 2, sixteen columns:

| Col | Header | Source | Notes |
| --- | --- | --- | --- |
| A | FECHA DE VALIDACION vigiflow | run | Same on every row, the day being reported |
| B | FECha de recepcion inicial vigiflow (virtual) | VigiFlow | Date |
| C | FECHA DE NOT. | VigiFlow | Date |
| D | N. | counter | Running correlative |
| E | EESS. | VigiFlow | The notifier's organisation |
| F | RAM / TAB / VIH / ESAVI | rule | Read off the end of the report title |
| G | EV. | rule | A number, or `S/E`, or blank |
| H | ID CODIGO | VigiFlow | The numeric part of the world-wide id |
| I | vigiflow ( codigo asignado por la ipres) | VigiFlow | The report title |
| J | PACIENTE | VigiFlow | Initials |
| K to O | MEDICAMENTO SOSPECHOSO | VigiFlow | One list field across five columns |
| P | GRAVEDAD | rule | LEVE / MODERADO / GRAVE, from the address |

The mapping lives in `resources/field_mapping.json`, keyed by column letter
rather than by field name. That is forced by the sheet itself: columns M, N
and O carry the identical header text `MEDICAMENTO SOSPECHOSO` and could not
otherwise be told apart. Each column declares where its value comes from,
which is what lets a counter, a run constant and a list live in the same
table as ordinary scraped fields.

The template's formatting is copied from its specimen row onto every row the
run adds, which is what makes a long list come out looking like the file the
business produces by hand. Verified at row 2,620 of a 2,619 row run.

Columns K to O hold up to five suspect drugs. Anything past the fifth is
dropped with a warning in the run log rather than overflowing into GRAVEDAD.

The template is never written to. Each run copies it and fills the copy.

---

## 4. Work item contracts

### Producer input, the trigger

The triggering email itself. Control Room puts its body in the payload and its
attachments in the work item's files. A run started by hand can name a file
instead, through `links_file` in the payload or `VIGIFLOW_LINKS_FILE` in the
environment.

```json
{
  "payload": {
    "reply_to": "analista@example.org",
    "subject": "Reportes VigiFlow",
    "sender_name": "Analista"
  },
  "files": { "Links.xlsx": "Links.xlsx" }
}
```

`reply_to` is read from the email itself when Control Room supplies it, and
falls back to the payload. A trigger with no address to reply to fails as a
BUSINESS error rather than running and having nowhere to send the result.

### Producer output, consumer input

One per link. The run context travels on every item so any one of them can
tell the reporter where to send the result, which means the reporter does not
depend on a particular item arriving.

```json
{
  "url": "https://vigiflow.who-umc.org/dataentry/<guid>",
  "guid": "e71a7f06-ba16-415e-a827-134939a6323e",
  "source_row": 2,
  "position": 1,
  "run_id": "a1b2c3d4e5f6",
  "reply_to": "analista@example.org",
  "input_file": "Links.xlsx",
  "started_at": "2026-09-13T00:10:00+00:00",
  "subject": "Reportes VigiFlow",
  "sender_name": "Analista",
  "total_links": 2
}
```

`source_row` is the row of the spreadsheet the link came from, so a failure
names something the analyst can find. `position` is the order to write it in.

A row that is not a usable link is queued the same way, carrying `problem` and
`value` instead of `url`. It is queued rather than dropped because a row that
vanishes here is a report the analyst believes was processed and was not.

### Consumer output, reporter input

```json
{
  "report_id": "PE-DIGEMID-300289386",
  "fields": { "...": "one row of the workbook" },
  "missing": ["paciente"],
  "position": 1,
  "source_row": 2,
  "run_id": "a1b2c3d4e5f6",
  "reply_to": "analista@example.org"
}
```

Dates are written as ISO strings so a record survives the queue. `missing`
names the fields that were empty on the page, which is how a systematic gap
becomes visible before somebody notices it in the workbook.

The reporter emits no output work item. The workbook is a run artefact and the
result goes out by email, so there is nothing for a downstream step to consume.

---

## 5. Failure handling

Control Room distinguishes two kinds of failure, and the distinction decides
whether a human or a retry fixes it.

| Situation | Kind | Code | What happens |
| --- | --- | --- | --- |
| No spreadsheet attached | BUSINESS | `NO_ATTACHMENT` | A person resends with the list |
| The spreadsheet cannot be read | BUSINESS | `UNREADABLE_LIST` | A person fixes the file |
| No address to reply to | BUSINESS | `NO_REPLY_ADDRESS` | A person resends |
| A work item carries no link | APPLICATION | `NO_URL` | A defect, not a retry |
| A row is not a VigiFlow address | BUSINESS | `NOT_A_LINK` | Reported in the reply, no screenshot |
| A link opens but is not a report | BUSINESS | `LINK_NOT_A_REPORT` | Reported in the reply with a screenshot |
| VigiFlow unreachable or sign-in fails | APPLICATION | | Safe to retry the item |
| The reply cannot be sent | APPLICATION | | The workbook survives as a run artefact |

The two middle cases matter most. One bad link does not sink the run. The
others are still written, the reply names every bad row and says the link
provided is broken or is not related to a report, and the row is visible in
Control Room by its place in the analyst's spreadsheet.

They are failed work items rather than quiet successes because a bad link is a
real exception a person should see, and they still produce an output item, so
the reporter can tell the analyst about them. The distinction the codes draw
is whether there was anything to photograph: a cell that is not an address has
nothing behind it, while a dead VigiFlow link has a page worth showing.

A send failure fails the reporter loudly, because a run nobody receives is not
a finished run. The workbook is still in the run artefacts, so the work itself
is never lost, and the log carries a staged diagnosis: reaching the server,
encryption and sign-in are reported separately, since they fail in ways that
look alike from outside and the difference decides who fixes it.

---

## 5b. What the run keeps

The business drew the line clearly: the finished workbook holds a nickname and
the agreed columns and is not sensitive, so it needs no encryption. Everything
the robot reads to produce it is, because a report page is the whole case.

Three routes had to be closed, and the first was not obvious.

**robocorp-log instruments this package automatically** and records the
arguments and return values of every call it makes. Reading a page returns it
as one string, so a full report was landing in `log.html` without a single
line of code asking for it. Every task now runs inside
`privacy.no_data_in_logs`, which suppresses values and keeps the call graph:
a failure is still locatable, what flowed through it is not recorded. Measured
after the change, a run that read two reports put none of their identifiers,
organisations, drugs or initials into `log.html` or the `.robolog`.

Exception messages are trimmed to one line. Playwright reports a strict-mode
violation by listing the text of every element that matched, which is patient
data arriving through the error path.

**Screenshots are off, not "only-on-failure".** A failure screenshot of a
report page is the whole case in a picture, embedded in the log. The only
screenshots kept are of pages that turned out not to be reports, which is an
error dialog rather than a case, and they are taken deliberately.

**The disk is cleared after the reply is sent**: the workbook, the spreadsheet
that arrived by email, and the screenshots. Nothing is deleted when the send
fails, so a report nobody received can still be delivered by hand. The next
run also clears whatever an earlier one left, because the end of a run is the
part that does not happen when it fails midway.

**The work item queue is the one store this does not finish.** A scraped row
reaches the reporter as a payload. Locally that is a folder of JSON and the
producer clears it; in Control Room it is the platform's storage and its
retention is a workspace setting. That is a deliberate boundary, not an
oversight: a task reaching into the queue's storage would be reaching past the
platform that owns it.

---

## 6. Layout

| Path | What it is |
| --- | --- |
| `tasks.py` | The three tasks. Owns the queue, nothing else |
| `vigiflow_tasks/links.py` | Reading the emailed spreadsheet |
| `vigiflow_tasks/email_run.py` | The trigger, and the run context |
| `vigiflow_tasks/report_scraper.py` | One report page into one workbook row |
| `vigiflow_tasks/causality.py` | Column EV |
| `vigiflow_tasks/mailer.py` | Sending the reply, and diagnosing SMTP |
| `vigiflow_tasks/privacy.py` | **Report data out of the logs and off the disk** |
| `vigiflow_tasks/excel/template_writer.py` | Filling the template |
| `vigiflow_tasks/models.py` | The payload contract |
| `vigiflow_tasks/config.py` | Parameters and their precedence |
| `vigiflow_tasks/vigiflow/browser_client.py` | Signing in, and handing over the page |
| `vigiflow_tasks/vigiflow/safety.py` | **The click guard** |
| `vigiflow_tasks/vigiflow/locators.py` | **Every selector, in one file** |
| `resources/field_mapping.json` | Which field goes to which column |
| `resources/templates/` | The template, built from the real daily report |
| `devdata/` | Local run configuration and a sample trigger |
| `tests/` | Unit tests, no browser and no Control Room needed |

---

## 7. What is done and what is left

**Done and verified against production.** The whole pipeline runs end to end.
The producer reads the attached list and queues one item per link. The
consumer signs in through Azure AD B2C and reads each report from its own
page. The reporter writes the workbook, applies the EV rule across the run,
and emails it back with the run summary attached. A supervised run of two
links produced a workbook checked column by column against the rules, and the
reply arrived.

All sixteen columns have a confirmed source. Column EV was the last, and its
rule runs opposite to the obvious reading.

Nothing is written to VigiFlow. That was proved rather than assumed: two
exports taken before and after a full extraction were compared, and none of
1,712 reports differed in last editor, delegated organisation or last
modified date.

**Left to do.**

1. **Control Room setup**: the email trigger, the process, and the failure
   notifications.
2. **A long run**, to measure how it scales. A run of 2,619 reports has been
   done under the earlier design and the workbook came out correctly
   formatted throughout, but not through this pipeline.

---

## 8. Open questions

1. **MODERADA or MODERADO?** The address fields carry both spellings, 714 and
   881 times respectively in the live set. The sample workbook uses MODERADO.
   The reader writes whichever it finds rather than normalising, because
   inventing consistency where the source has none seemed the wrong call.
   Say the word and it can fold both to one.
2. **The blank cells.** Column C is empty on about a tenth of reports, F on a
   fifth, and P on a sixth, because the source genuinely has nothing. They are
   left blank rather than guessed. Confirm a person fills them in afterwards,
   or say what the robot should put there.
3. **The EV correlative starts at 1 each run.** The business called the number
   arbitrary, so that is the default. If it should continue across runs the
   way column D's correlative does, it needs a value supplied per run.

---

## 9. Running it

The vault holds both the VigiFlow credentials and the SMTP account, so every
task except the producer needs Control Room access. From VS Code the Sema4.ai
extension supplies it. From a terminal, name an account and a workspace:

```powershell
rcc task run -t Producer -e devdata/env-for-producer.json --account <account> --workspace <id>
rcc task run -t Consumer -e devdata/env-for-consumer.json --account <account> --workspace <id>
rcc task run -t Reporter -e devdata/env-for-reporter.json --account <account> --workspace <id>
```

`rcc cloud workspace --account <account>` lists the workspace ids. Each task's
output feeds the next, so run them in order.

The producer reads `devdata/work-items-in/email-trigger/`. Drop a `Links.xlsx`
beside its `work-items.json` to try a real list; that file is git ignored,
because a real list points at real patient records. The workbook lands in
`output/`, named the way the business names it.

For a local vault instead of Control Room, copy `devdata/vault.example.json`
to `devdata/vault.json` and point the env file at it with
`RC_VAULT_SECRET_MANAGER` and `RC_VAULT_SECRETS_FILE`. That file is git
ignored. **Never commit real credentials.**

Tests:

```powershell
uv run --with pytest --with openpyxl python -m pytest -q tests
```
