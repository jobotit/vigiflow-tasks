# Templates

`reportes_vigiflow.xlsx` is the template the robot fills. It was built from
the real daily report `REPORTES DEL VIGIFLOW DEL DIA 31-08-2026.xlsx` by
removing its 60 data rows.

The header text, the blue header fill, the medium borders, the 75.75 header
row height, the column widths and the `mm-dd-yy` date formats all come from
that file and are preserved. Row 2 is kept deliberately: it is empty of
values but carries the data-row styling, which the writer copies onto every
row it appends. openpyxl gives rows that never existed no formatting at all,
so without that specimen row the output would lose its borders.

If the business changes the layout, re-run:

```powershell
uv run --with openpyxl python scripts/make_template_from_sample.py "path/to/new report.xlsx"
```

then update `resources/field_mapping.json` if the columns moved.

The robot never writes to this file. Each batch is written to a copy in the
output folder.
