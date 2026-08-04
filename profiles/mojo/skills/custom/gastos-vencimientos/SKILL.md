---
name: gastos-vencimientos
description: "Process credit card statements and utility bills forwarded to `${GASTOS_VENCIMIENTOS_EMAIL}` — extract amounts/due dates, load into 'Gastos bonitos' → 'Aux - Previsión' sheet, and archive PDFs/receipts to Drive/Vencimientos/<year>/<month>/."
version: 2.0.0
author: agent
platforms: [linux]
metadata:
  hermes:
    tags: [expenses, due-dates, credit-cards, google-sheets, google-drive, gmail, argentina, afip]
    related_skills: [google-workspace]
---

# Expenses — Due Dates

Process unread emails containing credit card statements and utility bills
forwarded to `${GASTOS_VENCIMIENTOS_EMAIL}`. Extract amount (ARS + USD), due date,
and payment method. Write to **"Gastos bonitos" → "Aux - Previsión"**.
Archive PDFs/receipts to **Drive → Vencimientos / `<year>` / `<month>` /**.

## Fixed Resources

| Resource | ID / Value |
|---|---|
| Spreadsheet | `1FlO3LLSWQmTRoKL8WFeYQKQ-GZWU3HW4zbKgfFuHPqw` |
| Sheet tab | `${GASTOS_VENCIMIENTOS_SHEET_ID}` |
| Drive root | `${GASTOS_VENCIMIENTOS_DRIVE_ROOT_ID}` |
| Gmail query | `is:unread newer_than:30d ("resumen de cuenta" OR "resumen de tarjeta" OR resumen OR mastercard OR visa OR pago OR vencimiento OR factura OR expensas OR servicios OR servicio OR boleta OR deuda)` |

> **Canonical service→row and month→column tables:** [`references/quick-lookup.md`](references/quick-lookup.md). Load before writing to the sheet.

## Loading Rules

1. **Never overwrite cells.** Read target range before writing. If the cell already has a value:
   - **Matches** what you'd write → already loaded (skip load, do Drive + mark read).
   - **Differs** → don't overwrite, leave unread, alert user.

   ⚠️ **Verification nuance:** `$GAPI sheets get` returns **FORMATTED_VALUE** by default — not formulas. When you wrote a formula like `=5306400,91-2946385,63` on a previous run, reading it back yields the **computed number** (e.g. `2.360.015,28`), not the formula text. When checking whether a cell "matches", compare against the **expected formatted result**, not the raw formula string. For non-formula cells, `sheets get` may return formatted strings (thousands separators, locale-dependent decimals) — normalize both sides before comparing: strip thousand separators and unify the decimal separator.
2. **Due day** → integer (1–31).
3. **M/A column** → `"M"` (manual), `"A"` (auto), or blank if unknown.
4. **ARS amount** (column +2):
   - Negative total → **`0`** (credit balance, literal).
   - Cards **with AFIP tax > 0** → **formula** with comma decimal: `=TOTAL,XX-TAX,XX` (e.g. `=5306400,91-2946385,63`). Lets the configured account holder audit.
   - Cards **without tax** (tax=0/None) + all utilities → **literal** value.
5. **USD amount** (column +3):
   - Negative → **`0`**.
   - ≥ 0 → **literal** with comma decimal (e.g. `6840,33`).
6. **Month column** = calendar month of the **due date** (not statement close date or email date).
   - ⚠️ Sheet covers **Junio–Diciembre**. If due date falls in Enero–Mayo, skip the sheet — just notify via Telegram.

## Mail Type Dispatch

Identify each email by subject + sender, then follow its extraction rules.

| # | Type | Identify By | Source | Key Extraction | File Name |
|---|------|------------|--------|---------------|-----------|
| 1 | **Mastercard** | Subject: "Resumen de Tarjeta MasterCard"; From: contains "Galicia" | PDF attachment | Due: 4th of 6 dates on page 1 (index 3). Total: `TOTAL A PAGAR`. Tax: `PERCEP.AFIP RG 4815/5617 30%`. | `Mastercard - Resumen YYYY-MM (vence DD-MM-YY).pdf` |
| 2 | **Visa** | Subject: "Resumen de Cuenta VISA"; From: contains "Galicia" or "E-Resumen" | PDF via link in body | URL: `https://www.eresumen.com.ar/msc/descargar/m/<UUID>:0` (keep `:0`). Due: `VENCIMIENTO DD Mes YY`. Total: `SALDO ACTUAL`. Tax: `DB.RG 5617` on totals page. | `Visa - Resumen YYYY-MM (vence DD-MM-YY).pdf` |
| 3 | **Mercado Pago** | Subject: "Debitaremos el total de tu tarjeta..."; From: `no-responder@mercadopago.com` | PDF attachment (encrypted) | Password: `${MERCADO_PAGO_PDF_PASSWORD}`. Due: `Fecha de vencimiento`. Total: space-separated decimal (e.g. `106.663 00`). Auto-debit check: "Tenés activo el débito automático" → `"A"`. No AFIP tax. | `Mercado Pago - Resumen YYYY-MM (vence DD-MM-YY).pdf` |
| 4 | **Expensas** | From: `no-reply@octopus.com.ar`; Subject: contains "Expensas Período" | 2 PDF attachments | Save both (liquidación + recibo). Due: `1° VTO: DD/MM/YYYY`. Amount: `TOTAL AL 1er VTO.: $XXX,XX`. ⚠️ Column month = due date month, not period month. Owner `${GASTOS_VENCIMIENTOS_EXPENSAS_OWNER}` = expected. | Liquidación: `Expensas - Liquidacion YYYY-MM (vence DD-MM-YY).pdf`<br>Recibo: `Expensas - Recibo YYYY-MM.pdf` |
| 5 | **PagoMisCuentas digest** | From: `avisos@pagomiscuentas.com`; Subject: "Servicios por Vencer" | Email body (HTML) | Strip HTML first: `<br>`→`\n`, remove all tags, `html.unescape()`. Then regex per service block. Map company→service via table below. | `PagoMisCuentas - <Service> YYYY-MM.eml` |
| 6 | **PagoMisCuentas confirmation** | Subject: "Confirmación de Pago Automático" (or body contains "débito automático"/"se ha realizado con éxito") | — | **DISCARD.** Mark read. No sheet load. No Drive archive. Report as "administrative close" (1 line). This is a receipt, not a new bill. | — |
| 7 | **Other utility** | Any other matched email with PDF or body | PDF or body | Extract due date + ARS amount. Apply loading rules (literal, no formula). If ambiguous → don't mark read, include in report. | `<Service> - YYYY-MM.pdf` or `.eml` |

> **Regex patterns** for PDF extraction (Mastercard, Visa, Mercado Pago): [`references/pdf-regex-cookbook.md`](references/pdf-regex-cookbook.md). Row builder helpers (`_open_pdf_text()`, `build_tarjeta_row()`, `build_servicio_row()`) are in [`scripts/row_builders.py`](scripts/row_builders.py) — import them, don't copy-paste.

## Company → Service Mapping

| Company (in email) | Service (sheet) |
|---|---|
| AYSA, Aguas Bonaerenses | Agua |
| Metrogas, Gas Natural Fenosa | Gas |
| M.BLUM, Administracion M.BLUM, Octopus | Expensas |
| Banco Galicia / Mastercard | Mastercard |
| Banco Galicia / Visa / E-Resumen | Visa |
| Mercado Pago | Tarjeta MP |

> **Row numbers live exclusively in [`scripts/cell_range.py`](scripts/cell_range.py).** They are intentionally NOT duplicated here to avoid drift. Always use `cell_range.py --json` or the `cell_range()` Python helper to resolve any (service, month) pair — do not hard-code row numbers in extraction code.

If a company can't be mapped → log, skip, don't mark read.

## Per-Type Details

Non-obvious extraction rules not covered by the cookbook:

### Visa
- Download PDF with `curl -sL --max-time 30 '<URL>'`. If response is HTML/302 → token expired. ⚠️ The email body does NOT contain structured data for extraction — leave the email unread and alert the user. Do not attempt to extract from body.
- ⚠️ `DEV.IMP. RG 5617` on page 1 is a **historical refund**, NOT current tax. Use `DB.RG` on totals page.

### Mercado Pago
- Decimal separator in header is a **space**: `106.663 00` = $106,663.00. The "Consolidado" section uses comma normally.
- USD = 0 → load `0` literal.

### Expensas
- If no PDF (text-only email) → parse body with same patterns.
- M/A: blank. USD: blank.

### PagoMisCuentas Digest
Body parsing — extract plain text from HTML, then split into service blocks:

**Step 1 — Strip HTML safely:**
```python
import re, html as _html

# 1. Remove <style> and <script> blocks WITH their contents.
#    The previous approach only stripped tags, leaving CSS text behind
#    that could match Empresa/Vencimiento/Importe regexes.
text = re.sub(r'<style[^>]*>.*?</style>', '', body, flags=re.DOTALL | re.IGNORECASE)
text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)

# 2. Convert <br> variants to newlines.
text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)

# 3. Strip remaining HTML tags.
text = re.sub(r'<[^>]+>', ' ', text)

# 4. Decode HTML entities (á, &amp;, etc.).
text = _html.unescape(text)

# 5. Collapse whitespace.
text = re.sub(r'[ \t]+', ' ', text)
text = re.sub(r'\n{3,}', '\n\n', text)
```

**Step 2 — Segment into service blocks:**

Split the cleaned text on `Empresa:` to isolate individual services, then re-prefix:
```python
blocks = ['Empresa:' + b for b in text.split('Empresa:')[1:]]
```

**Step 3 — Parse each block:**
```python
for block in blocks:
    empresa  = re.search(r'Empresa:\s*(.+?)\s*(\(PA\))?$', block, re.M)
    vto      = re.search(r'Vencimiento:\s*(\d{2})/(\d{2})/(\d{4})', block)
    importe  = re.search(r'Importe:\s*\$\s*([\d.,]+)', block)
```

- `(PA)` suffix or "Pago Automático" → M/A = `"A"`.
- Multi-service digest → process all. Unmappable ones → log, continue.
- ⚠️ **Normalize** the extracted `empresa` before mapping: `.strip().lower()`. Match against lowercase versions of company names (e.g. `"aysa"`, `"metrogas"`). If exact match fails, try partial matching (e.g. `"galicia"`). ⚠️ When `"galicia"` matches BOTH Visa and Mastercard, resolve by inspecting other email signals: the subject line identifies the specific card type. Only skip if no partial match at all.

### Other Utilities
- If PDF has a link → download and save. If no PDF → save as `.eml` with `scripts/save_gmail_eml.py`. Fallback: save body as `.txt`.
- Amount: literal (no AFIP tax). Negative → 0.
- If ambiguous → **don't mark read**, include in report for review.

## Drive Folder Structure

```
Vencimientos/
├── 2025/
│   ├── Enero/
│   └── ...
└── 2026/
    ├── Junio/
    └── ...
```

- Create year/month folders if missing. Reuse existing IDs (never recreate).
- To check folder existence, use `--raw-query` (plain `drive search` does fullText contains and breaks with structured queries):
  ```bash
  $GAPI drive search "mimeType='application/vnd.google-apps.folder' and name='Julio' and '<PARENT_ID>' in parents and trashed=false" --raw-query --max 10
  ```
- Discover year ID by searching with parent = Vencimientos root. Create only if absent.

## Procedure

0. **Auth pre-check.** Verify the OAuth token is valid before touching any API:
   ```bash
   $GAPI_PY $HOME/.hermes/profiles/mojo/skills/productivity/google-workspace/scripts/setup.py --check
   ```
   If it doesn't print `AUTHENTICATED` → exit with error (don't be silent). The token may need refresh.
1. **Search** unread emails with the Gmail query from Fixed Resources. Use `--max 100` to avoid the default 10-result limit. If the API returns 100 results and you have not checked `nextPageToken`, re-run with pagination (the Gmail API list endpoint accepts `pageToken`). Keep fetching while a `nextPageToken` is present — no email should be silently dropped because it fell outside a single page.
2. **If no results** → silent exit (respond `[SILENT]` so the cron scheduler suppresses delivery).
3. **For each email** — wrap in try/except. If any unhandled exception occurs: log the error, leave the email unread, and **continue to the next email**. Never let one bad email block the rest.
   a. **Identify type** via dispatch table. Unknown → report, don't mark read, skip. PagoMisCuentas confirmation → discard (mark read, report 1 line).
   b. **Download** PDF/attachments per type. For Visa PDF download, always use a timeout: `curl -sL --max-time 30 '<URL>'`.
   c. **Extract data** using cookbook regex patterns. Import row builders from the script instead of copying inline code:
      ```python
      import sys
      sys.path.insert(0, '$HOME/.hermes/profiles/mojo/skills/custom/gastos-vencimientos/scripts')
      from row_builders import build_tarjeta_row, build_servicio_row, _open_pdf_text
      ```
   d. **Look up** service row + month column from quick-lookup.md. Map the due-date Spanish month name to a `MONTH_BLOCKS` key. If the month is not in MONTH_BLOCKS (Enero–Mayo) → skip the sheet load, notify via Telegram.
   e. **Read target cells** before writing (see Loading Rule 1 for comparison nuance). If value matches what you'd write after normalizing formatted vs formula output → already loaded (mark read, skip rest of this email). If value differs → skip, alert user, leave unread.
   f. **Build row** with `build_tarjeta_row()` or `build_servicio_row()`.
   g. **Upload** PDF/EML to `Vencimientos/<year>/<month>/` **first** (before writing to the sheet). Create folders if needed. ⚠️ If upload fails → stop here, leave email unread, report error — do NOT write to the sheet.
   h. **Write** to sheet via `sheets update` (exact range from `cell_range()` helper).
   i. **Verify** the write by reading the same range back with `sheets get`. ⚠️ Because `sheets get` returns **formatted** values (not formulas), compare **normalized** values: strip thousand separators (`.`), unify decimal to `,`. For formula cells, compute the expected numeric result. For blank trailing cells (USD in utilities), `sheets get` may return fewer columns than written — treat missing trailing columns as matching blank. If normalized values don't match → leave email unread, report error.
   j. **Mark read** (`gmail modify --remove-labels UNREAD`). Only if all prior steps succeeded.
4. **Clean up** temp files. Delete all PDFs and EMLs downloaded to `/tmp` during this run.
5. **Report** to user (see below).

## Report

- **All OK, no issues** → 1–3 line summary:
  > ✅ Processed 2: Mastercard Jun ($0 / USD 1,731.24), Visa Jun ($2,360,015 / USD 6,840.33). [PDFs in Drive](https://drive.google.com/drive/folders/<FOLDER_ID>).
  Include a Drive link for each file.
- **Issues** → table of unprocessed emails + reason, plus what succeeded.
- **Nothing new** → respond with exactly `[SILENT]` (cron scheduler suppresses delivery).

## Critical Pitfalls

1. **Decimal = comma, not dot** (AR locale). Dot in formulas → `#ERROR!`.
2. **Visa URL must end in `:0`.** Without it → 302 error page.
3. **Visa PDF may return HTML** if token consumed. The body has no structured data — leave unread, alert user. Do not attempt "body fallback."
4. **Mastercard: 6 dates, index 3** is the current due date.
5. **`DEV.IMP. RG 5617` ≠ tax.** That's a historical refund on Visa page 1. Use `DB.RG` on totals page.
6. **Negative balance → `0` literal**, no formula. Same for USD.
7. **Never mark read if any step failed** (except PagoMisCuentas confirmations — those are intentional discards).
8. **`sheets update` is destructive** — always read the cell first.
9. **PyMuPDF ≥ 1.27: no `doc.get_text()`.** Use `_open_pdf_text()` from `scripts/row_builders.py`.
10. **`drive search` needs `--raw-query`** for structured queries like `name='X'`. Plain mode does fullText contains → `HttpError 400`.
11. **PagoMisCuentas body is HTML.** Strip tags before regex or you'll match CSS, not data.
12. **OAuth token expires every 7 days** in Testing mode. The `google-workspace` watchdog cron (`preflight google oauth token`) handles alerts. Don't delete it.
13. **One bad email must not block the rest.** Wrap each email's processing in try/except. On exception → log, leave unread, continue to the next.
14. **Always verify the sheet write** by reading the range back after writing. Silent write failures are real — the API can return 200 OK without persisting.
15. **Upload to Drive before writing to the sheet.** If Drive fails, the sheet stays clean and the email stays unread for retry next run.
16. **Clean up `/tmp` after each run.** Delete downloaded PDFs/EMLs to avoid slowly filling the disk.
17. **Pre-check auth at the start** of every run with `setup.py --check`. Don't assume the token is fresh — the watchdog may not have run yet.
18. **`gmail get` body extraction is shallow.** The `$GAPI gmail get` command (via `google_api.py`) only extracts body text from top-level MIME parts. It does NOT recurse into nested `multipart/alternative` or `multipart/related` structures — a common pattern in forwarded or HTML-rich emails. If `gmail get` returns an empty body for a message you know has content, the body is nested deeper. Workaround: use `scripts/save_gmail_eml.py` to save the raw `.eml`, then extract text with Python's `email` module:
   ```python
   import email
   msg = email.message_from_file(open('/tmp/message.eml'))
   # Iterate msg.walk() to find text/plain or text/html parts
   for part in msg.walk():
       if part.get_content_type() == 'text/plain':
           body = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
           break
   ```
   Always respect the declared MIME charset — do not assume UTF-8.

## Shell Aliases

```bash
GAPI_PY=$HOME/.hermes/.venv/bin/python
GAPI="$GAPI_PY $HOME/.hermes/profiles/mojo/skills/productivity/google-workspace/scripts/google_api.py"
GSETUP="$GAPI_PY $HOME/.hermes/profiles/mojo/skills/productivity/google-workspace/scripts/setup.py"
```

> Import row builders in Python with:
> ```python
> import sys
> sys.path.insert(0, '$HOME/.hermes/profiles/mojo/skills/custom/gastos-vencimientos/scripts')
> from row_builders import build_tarjeta_row, build_servicio_row, _open_pdf_text
> ```

> Spreadsheet and Drive folder IDs in Fixed Resources table above.

## Dependencies

Verify `pymupdf` is installed:
```bash
~/.hermes/.venv/bin/python -c "import fitz"
```
If missing: `uv pip install --python ~/.hermes/.venv/bin/python pymupdf`.

## Cron

Schedule: `0 */2 * * *`. Prompt: `Process unread due-date emails per skill 'gastos-vencimientos'.`
Toolsets: `["terminal", "file"]`. Wrap response: `false`.

Requires the **OAuth token watchdog** (`preflight google oauth token`, every 6h, `no_agent=true`) — see `google-workspace` skill for details. Without it, the cron silently breaks every 7 days.

## References

- `references/quick-lookup.md` — service→row, month→column tables + `cell_range()` helper (also available as CLI: `scripts/cell_range.py`)
- `references/pdf-regex-cookbook.md` — PDF extraction regex patterns (Visa, Mastercard, Mercado Pago)
- `scripts/row_builders.py` — `build_tarjeta_row()`, `build_servicio_row()`, `_open_pdf_text()`, `_fmt_ar()` as an importable Python module. Always import from here — don't copy inline code from the cookbook.

## Scripts

- `scripts/cell_range.py` — compute Sheets `'Aux - Previsión'!Xn:Yn` range for a (service, month) pair. Use `--json` to dump all.
- `scripts/download_gmail_attachments.py` — download all attachments from a Gmail message. Used for Mastercard, Expensas, Mercado Pago PDFs.
- `scripts/save_gmail_eml.py` — download a Gmail message as `.eml` (RFC822 raw). Used when no PDF is available (PagoMisCuentas, other text-only utilities).
- `scripts/row_builders.py` — `build_tarjeta_row()`, `build_servicio_row()`, `_open_pdf_text()`, `_fmt_ar()` as an importable Python module. Use this instead of copying inline code from the cookbook.
