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

## Run locally

With the Sema4.ai VS Code extension: open the command palette, run
"Sema4.ai: Run Task Package", pick the task, and pick the matching
`devdata/env-for-*.json`. The extension supplies the Control Room access the
vault needs.

From a terminal, the vault needs an account and a workspace:

```powershell
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
| `validation_date` | `VIGIFLOW_VALIDATION_DATE` | today |
| `template` | `VIGIFLOW_TEMPLATE` | `reportes_vigiflow.xlsx` |
| `links_file` | `VIGIFLOW_LINKS_FILE` | the trigger's attachment |
| | `VIGIFLOW_HEADLESS` | `true` |
| | `VIGIFLOW_TIMEOUT_MS` | 30000 |

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
