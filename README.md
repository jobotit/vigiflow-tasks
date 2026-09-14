# vigiflow-tasks

Sema4.ai Task Package that reads VigiFlow reports and fills the daily Excel
report. It is triggered by an email carrying a spreadsheet of report links, and
it replies to the sender with the finished workbook attached.

```
Producer  ->  Consumer  ->  Reporter
one work item     reads one report     writes the workbook
per link          from its own page    and emails it back
```

One work item per link, so each report is a transaction that can fail and be
retried on its own without disturbing the rest of the run.

See [VigiflowTasksPlan.md](VigiflowTasksPlan.md) for the field-by-field
derivation of the workbook and the reasoning behind each business rule.

## The input

The triggering email carries one spreadsheet, a single column of report links:

```
Links
https://vigiflow.who-umc.org/dataentry/<guid>
...
```

The header may be `Links`, `Link`, `URL`, `Enlace` or `Enlaces`, or absent
entirely. A cell holding a bare GUID and no address is accepted too, because
an analyst pasting from the id column produces exactly that. A report listed
twice is read once.

**No row is dropped quietly.** A row that is not a usable link still becomes a
transaction, and comes back in the reply saying the link provided is broken or
is not related to a report. A row dropped silently is a report the analyst
believes was processed and was not, which is the failure worth designing
against here.

Two kinds of unusable row, and they are told apart by whether there is
anything to show:

- **Not a VigiFlow address.** A stray note, an empty-looking cell, or a link
  to some other system. There is nothing to open, so the reply says so and
  there is no screenshot. The robot does not browse to an arbitrary address
  that arrived by email.
- **A VigiFlow address that is not a report.** A dead link, or the right
  system with the wrong path. This one is opened, and the page is
  photographed, so the reply carries a screenshot showing what is actually
  there.

The analyst chooses which reports to work on, so nothing in this package
applies a filter or walks a result page. Each report is reached directly by
the link supplied.

## The output

`REPORTES DEL VIGIFLOW DEL DIA <dd-mm-yyyy>.xlsx`, one sheet named `Hoja1`,
sixteen columns, header on row 1. Column A is the validation date and is the
same on every row. Column D is a running correlative. Columns K to O hold up
to five suspect drugs. The template's row formatting is copied onto every row
the run adds, so a long run comes out looking like the file the business
produces by hand.

To rebuild the template after a layout change:

```powershell
uv run --with openpyxl python scripts/make_template_from_sample.py "path/to/report.xlsx"
```

## The reply

The client is in Lima, so the reply is written in Spanish and every time in it
is Lima time, labelled "Lima (UTC-05:00)". The subject is "Reporte de VigiFlow"
followed by the name of the spreadsheet the analyst sent, and the sender's name
is "Automatización VigiFlow".

The same zone decides the validation date in column A and in the workbook's
name. Control Room workers usually keep UTC, where the date turns over at 19:00
in Lima, so a date taken from the worker's clock would be tomorrow's for five
hours every evening.

Peru has had no daylight saving since 1994, so where the time zone database is
missing, which is the default for Python on Windows, a fixed UTC-05:00 is used
and is exact. Set `VIGIFLOW_TIMEZONE` to another IANA zone name to change it; an
unknown name stops the run instead of quietly falling back.

The run log and Control Room's exception messages stay in English. They are for
whoever operates the robot, not for the analysts.

## Layout

| Path | Purpose |
| --- | --- |
| `robot.yaml`, `conda.yaml` | Task Package manifest and environment |
| `tasks.py` | The three tasks: producer, consumer, reporter |
| `vigiflow_tasks/links.py` | Reads the emailed spreadsheet of links |
| `vigiflow_tasks/email_run.py` | The trigger email, and the run context carried on every work item |
| `vigiflow_tasks/report_scraper.py` | Reads one report page into one workbook row |
| `vigiflow_tasks/causality.py` | Column EV: who did the analysis |
| `vigiflow_tasks/mailer.py` | Sending the reply, and diagnosing SMTP when it fails |
| `vigiflow_tasks/privacy.py` | Keeping report data out of the logs and off the disk |
| `vigiflow_tasks/excel/template_writer.py` | Fills the template from a field-to-cell mapping |
| `vigiflow_tasks/vigiflow/browser_client.py` | Signing in, and handing over the page |
| `vigiflow_tasks/vigiflow/safety.py` | The click guard |
| `vigiflow_tasks/vigiflow/locators.py` | Every selector |
| `vigiflow_tasks/config.py` | Parameters and their precedence |
| `resources/templates/` | `reportes_vigiflow.xlsx`, built from the real daily report |
| `resources/field_mapping.json` | Which field goes to which column |
| `devdata/` | Local run configuration and a sample trigger |
| `tests/` | Unit tests, no browser and no Control Room needed |

## Two ways to run it

The same code runs in either of two shapes, and `robot.yaml` offers both.

| | Single run | Producer, Consumer, Reporter |
| --- | --- | --- |
| Environment start-ups per email | one | three |
| Sign-ins to VigiFlow | one | one |
| Work items per link | none | one each |
| A bad link in Control Room | named in the reply and the run log | its own business exception |
| Retry one link on its own | no | yes |
| Rows kept if the run fails midway | none | every row already read |
| Best for | short lists, when waiting matters | long lists, when traceability matters |

Every Control Room step starts its own environment, and for a list of a few
dozen links those start-ups take longer than reading the reports. The single
task pays for one start-up, signs in once, and replies from the same process.
It also skips the browser entirely when no row of the list is a usable link.

Both shapes start a run, read a row and finish a run through the same
functions, so the workbook and the reply are identical whichever one produced
them. Choosing between them is a Control Room decision: a process with one step
running `Single run`, or a process with three steps running `Producer`,
`Consumer` and `Reporter` in that order, each with the email trigger on the
first step.

## Run locally

With the Sema4.ai VS Code extension: open the command palette, run
"Sema4.ai: Run Task Package", pick the task, and pick the matching
`devdata/env-for-*.json`. The extension supplies the Control Room access the
vault needs.

From a terminal, the vault needs an account and a workspace:

```powershell
rcc task run -t "Single run" -e devdata/env-for-single.json --account <account> --workspace <id>

rcc task run -t Producer -e devdata/env-for-producer.json --account <account> --workspace <id>
rcc task run -t Consumer -e devdata/env-for-consumer.json --account <account> --workspace <id>
rcc task run -t Reporter -e devdata/env-for-reporter.json --account <account> --workspace <id>
```

`rcc cloud workspace --account <account>` lists the workspace ids.

Each task's output work items feed the next, so run them in order. The
producer reads `devdata/work-items-in/email-trigger/`, which holds a sample
trigger payload; drop a `Links.xlsx` beside it to try a real list. That file
is git ignored, because a real list points at real patient records.

For a local vault instead of Control Room, copy `devdata/vault.example.json`
to `devdata/vault.json`, fill it in, and add `RC_VAULT_SECRET_MANAGER` set to
`FileSecrets` and `RC_VAULT_SECRETS_FILE` set to that path in the env file.
`devdata/vault.json` is git ignored, as is anything else matching a credential
shape. **Never commit real credentials.**

## Credentials

One Control Room vault item, `Vigiflow_C001_Credentials`, holds everything:

| Key | For |
| --- | --- |
| `VIGIFLOW_URL`, `VIGIFLOW_USERNAME`, `VIGIFLOW_PASSWORD` | Signing in to VigiFlow |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURE`, `SMTP_USERNAME`, `SMTP_PASSWORD` | Sending the reply |
| `SMTP_FROM` | The address the reply comes from, if not the one signing in |

Sign-in goes through Azure AD B2C: opening VigiFlow redirects to
`whoumcprod.b2clogin.com` and returns after a successful sign-in. Success is
judged by arriving back on the VigiFlow host, not by finding an element, since
every page in the redirect chain looks loaded.

`SMTP_SECURE` means TLS from the first byte, not "encrypted or not". Leave it
false for port 587 and the connection still upgrades through STARTTLS.

Against Gmail the password must be a 16 character App Password, and it must
belong to the account in `SMTP_USERNAME`. Google answers a password from a
different account with the same error as a wrong one. When a send fails the
reporter reports reaching the server, encryption and sign-in separately, and
describes the password's shape without printing it, which is what tells those
two cases apart.

Set `VIGIFLOW_SMTP_REPLY_TO` to give a person somewhere to write back to when
the reply is sent from a no-reply address.

## What the robot keeps

A report page carries the whole case. The finished workbook carries far less,
and the business treats that as not sensitive, so it needs no encryption. What
the robot reads on the way there does, and three routes had to be closed.

**The logs.** robocorp-log instruments this package automatically and records
the arguments and return values of every call it sees. Reading a page returns
it as a string, so by default a full report landed in `log.html`. Every task
now runs inside `privacy.no_data_in_logs`, which suppresses values while
leaving the call graph, so a failure is still locatable and what flowed through
it is not recorded. Nothing printed by the tasks carries a value read from a
report either: progress is reported by spreadsheet row, and missing fields are
counted across the run rather than named per report.

Exception messages are trimmed to one short line. Playwright reports a
strict-mode violation by listing the text of every element that matched, and
that text is patient data.

**The screenshots.** Automatic screenshots are off, not "only-on-failure": a
failure screenshot of a report page is the whole case in a picture, embedded
in `log.html`. The only screenshots taken are of pages that turned out not to
be reports, which is an error dialog rather than a case.

**The disk.** Once the reply has been sent, the run deletes what it created:
the workbook, the spreadsheet that arrived by email, and the screenshots. If
the send fails nothing is deleted, so a report nobody received can still be
delivered by hand. The next run also clears anything an earlier one left
behind, because the end of a run is the part that does not happen when it
fails midway.

The one store this cannot finish is the work item queue, which is how a
scraped row reaches the reporter. Locally that is a folder of JSON and the
producer clears it. In Control Room it is the platform's storage, and its
retention is a workspace setting rather than something a task should reach
into.

## VigiFlow notices

VigiFlow announces maintenance in a dialog titled "Avisos / Información
relevante", with a single "Ok" button. It covers the whole application with a
backdrop, so while it is up every click lands on the backdrop instead of the
control underneath.

On 14-09-2026 that notice emptied four columns on every row of a run: EESS.,
PACIENTE, GRAVEDAD and EV. Those are the columns read from a section the robot
has to click open. The columns visible as soon as a report loads came back
filled, so the workbook looked plausible and nothing said otherwise.

The robot now closes that notice after signing in, after each report loads and
before every section click. It closes it by the id of its own button, through
the same safety guard as every other click, and it closes nothing else. Any
other dialog is left where it is, because the robot cannot know what an
unknown dialog's button does. VigiFlow's "El reporte no pudo ser encontrado"
is one of those, and it is what a broken link's screenshot exists to show.

If a section still cannot be opened, the row is not passed off as complete.
The run log counts those rows, and the reply says how many are incomplete and
names the dialog that was covering the page.

## Nothing is written to VigiFlow

The report page opens as the data entry form, editable, with controls that
delete the report, save the form, reassign the case and clear whole sections
sitting beside the ones this package legitimately uses.

So every click goes through `vigiflow_tasks/vigiflow/safety.py`, which reads
the element's own id and visible label and refuses anything on its denylist.
It reads the element rather than trusting the selector that found it, because
the selector is exactly what goes wrong. Nothing is ever typed.

## Parameters

Read from the input work item payload first, then the environment, then the
default.

| Parameter | Environment variable | Default |
| --- | --- | --- |
| `start_number` | `VIGIFLOW_START_NUMBER` | 1 |
| `validation_date` | `VIGIFLOW_VALIDATION_DATE` | today, in Lima |
| `template` | `VIGIFLOW_TEMPLATE` | `reportes_vigiflow.xlsx` |
| `links_file` | `VIGIFLOW_LINKS_FILE` | the trigger's attachment |
| | `VIGIFLOW_HEADLESS` | `true` |
| | `VIGIFLOW_TIMEOUT_MS` | 30000 |
| | `VIGIFLOW_TIMEZONE` | `America/Lima` |

`links_file` is only a fallback, for starting a run by hand with no email.

## How a report becomes a row

Most of the row is read straight off the report page by field id. The captions
beside the inputs are not wired to them, so no label lookup finds anything;
the ids are both the only reliable handle and a steadier one.

Four columns are rules the analysts apply rather than fields:

- **Severity** (column P) comes from the notifier's city or province. VigiFlow
  has no severity field, so by a standing agreement the notifiers put it in
  the address. Those fields also hold real places, so only the agreed
  vocabulary counts and anything else leaves the cell empty.
- **Report type** (column F) is read off the end of the report title.
- **Column H** is the numeric part of the world-wide identifier. Most are nine
  digits and belong in the sheet as numbers, but ids like `PE-PERULAB-00009`
  exist, and writing those as a number would lose the leading zeros. A value
  with a leading zero is written as text, everything else as a number.
- **Column EV** counts the analyses the analyst performs, and the rule runs
  opposite to the obvious reading. When the notifying clinic has already
  filled in its causality assessment the analyst has nothing to do and the
  cell reads `S/E`. When the clinic left it empty the cell takes the next
  number. When the assessment could not be read at all the cell is left blank,
  because a number there would claim the analyst did work nobody checked.

### ESAVI reports

Vaccine adverse events live on their own VigiFlow form, reached by an
`/aefiform/<guid>` address instead of `/dataentry/<guid>`. The robot recognises
that form by a field only it has, and reads it with its own field ids. The
whole form is one page, so nothing on it is clicked.

| Column | ICSR form | ESAVI form |
| --- | --- | --- |
| C, FECHA DE NOT. | `dateOfInitialReport` | `dateOfReport` |
| E, EESS. | the notifier's organisation | the notifier's institution, else the health facility |
| F, type | the end of the report title | the end of the ESAVI reporting id, else ESAVI |
| I, IPRESS code | the report title | the ESAVI reporting id |
| J, PACIENTE | `patientNameOrInitials` | `patientInitials`, never the full name |
| K to O, suspect products | the sidebar, which shows the name as reported | each vaccine whose role is suspect, by name as reported |
| P, GRAVEDAD | the notifier's city or province | the notifier's, else the patient's, city or province |

Column EV uses the same rule on both forms. On the ESAVI form the only
causality assessment is the authority's, which is an open question below.

## Running on Linux

Nothing in this package needs Excel or a desktop.

The workbooks are written with **openpyxl**, which is pure Python: it reads
and writes the .xlsx file directly and never launches Excel. That includes
copying the template's formatting onto every row it adds, verified on a run of
2,619 rows. There is no `xlwings`, no `win32com`, no COM automation and no
LibreOffice anywhere in the code.

The browser runs headless by default, so no display is needed. Chromium is
downloaded by robocorp-browser on first use. On a bare Linux VM it also needs
the usual shared libraries:

```bash
python -m playwright install-deps chromium
```

`rcc` builds the environment from `conda.yaml`, which pins only
cross-platform packages, and `robot.yaml` already lists a Linux environment
file alongside the Windows one.

Use forward slashes in any path in a work item payload. They work on both
systems.

## Tests

```powershell
uv run --with pytest --with openpyxl python -m pytest -q tests
```

## Linting

flake8 is configured in `.flake8` with a 120 character line limit.

```powershell
uv run --with flake8 python -m flake8
```

Dev tooling is pinned in `requirements-dev.txt` and is deliberately kept out
of `conda.yaml`, which builds the environment every Control Room run uses.
