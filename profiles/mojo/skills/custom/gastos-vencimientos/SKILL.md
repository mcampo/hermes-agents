---
name: gastos-vencimientos
description: "Process credit card statements and utility bills forwarded to `${GASTOS_VENCIMIENTOS_EMAIL}` — extract amounts/due dates, load into 'Gastos bonitos' → 'Aux - Previsión' sheet, and archive PDFs/receipts to Drive/Vencimientos/<year>/<month>/."
metadata:
  version: "2.3.0"
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

## Mandatory Deterministic Path

For normal runs, invoke exactly one deterministic command. Do not manually
search Gmail, download sources, choose attachment roles, call `prepare_item`,
call `commit_item`, redirect ledgers, or call `render_report` yourself:

```bash
$HOME/.hermes/.venv/bin/python $HOME/.hermes/profiles/mojo/skills/custom/gastos-vencimientos/scripts/process_batch.py
```

It searches the fixed unread query, acquires and dispatches current sources,
prepares each message, commits it once, atomically saves every ledger, cleans
temporary sources, and prints the ledger-derived final report. Use its stdout
verbatim. For a targeted recovery, pass one or more `--message-id` values;
never rerun a message merely to recreate a ledger.

Ledgers go to the directory named by `GASTOS_VENCIMIENTOS_LEDGER_DIR` when set;
a direct command outside a scheduled run creates its own temporary ledger
directory, never a shared path.

> **HIGH-VALUE RULE — current inputs are the only authority.** Never inspect
> prior runs, previous-month rows/files, old reports, or model transcripts to
> infer a value. They are not evidence for the current bill and can contain
> exactly the errors this workflow is meant to prevent. If a current source is
> ambiguous, fail that message and leave it unread.

> **The installed skill is immutable during a run.** Treat this directory and
> its scripts as read-only. If a helper rejects a source or fails, record a
> failed ledger and leave that message unread; never patch, replace, or rewrite
> the helper in place. Operator fixes must be deployed before the next run.

## Loading Rules

1. **Never overwrite cells.** Read target range before writing. If the cell already has a value:
   - **Matches** what you'd write → already loaded (skip load, do Drive + mark read).
   - **Differs** → don't overwrite, leave unread, alert user.

   ⚠️ **Verification nuance:** `$GAPI sheets get` returns **FORMATTED_VALUE** by default — not formulas. When you wrote a formula like `=5306400,91-2946385,63` on a previous run, reading it back yields the **computed number** (e.g. `2.360.015,28`), not the formula text. When checking whether a cell "matches", compare against the **expected formatted result**, not the raw formula string. For non-formula cells, `sheets get` may return formatted strings (thousands separators, locale-dependent decimals) — normalize both sides before comparing: strip thousand separators and unify the decimal separator.
2. **Due day** → integer (1–31).
3. **M/A column** → `"M"` (manual), `"A"` (auto), or blank only where the
   type rule permits it. **Visa = `M`; Mastercard = `M`; Expensas = blank.**
   Mercado Pago and PagoMisCuentas use explicit current-source auto-debit text.
4. **ARS amount** (column +2):
   - Negative total → **`0`** (credit balance, literal).
   - Cards **with AFIP tax > 0** → **formula** with comma decimal: `=TOTAL,XX-TAX,XX` (e.g. `=5306400,91-2946385,63`). Lets Mariano audit.
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
| 2 | **Visa** | Subject: "Resumen de Cuenta VISA"; From: contains "Galicia" or "E-Resumen" | PDF via link in body | URL: `https://www.eresumen.com.ar/msc/descargar/m/<UUID>:0` (keep `:0`). Due: the single date in the helper's bounded window after `VENCIMIENTO` (same-line and tabular layouts supported). Total: `SALDO ACTUAL`. Tax: `DB.RG 5617` on totals page. | `Visa - Resumen YYYY-MM (vence DD-MM-YY).pdf` |
| 3 | **Mercado Pago** | Subject: "Debitaremos el total de tu tarjeta..."; From: `no-responder@mercadopago.com` | PDF attachment (encrypted) | Password: `${MERCADO_PAGO_PDF_PASSWORD}`. Due: `Fecha de vencimiento`. Total: space-separated decimal (e.g. `106.663 00`). Auto-debit check: "Tenés activo el débito automático" → `"A"`. No AFIP tax. | `Mercado Pago - Resumen YYYY-MM (vence DD-MM-YY).pdf` |
| 4 | **Expensas** | From: `no-reply@octopus.com.ar`; Subject: contains "Expensas Período" | 1–2 PDF attachments | Save the liquidación; save the recibo when attached. Due: `1° VTO: DD/MM/YYYY`. Amount: `TOTAL AL 1er VTO.: $XXX,XX`. Sheet column and Drive folder use the due month; **both filenames use the subject statement period**. Owner `${GASTOS_VENCIMIENTOS_EXPENSAS_OWNER}` = expected. | Liquidación: `Expensas - Liquidacion <STATEMENT-YYYY-MM> (vence DD-MM-YY).pdf`<br>Recibo: `Expensas - Recibo <STATEMENT-YYYY-MM>.pdf` (when attached) |
| 5 | **PagoMisCuentas digest** | From: `avisos@pagomiscuentas.com`; Subject: "Servicios por Vencer" | Email body (HTML) | Strip HTML first: `<br>`→`\n`, remove all tags, `html.unescape()`. Then regex per service block. Map company→service via table below. | `PagoMisCuentas - <Service> YYYY-MM.eml` |
| 6 | **PagoMisCuentas confirmation** | Subject: "Confirmación de Pago Automático" (or body contains "débito automático"/"se ha realizado con éxito") | — | **DISCARD.** Mark read. No sheet load. No Drive archive. Report as "administrative close" (1 line). This is a receipt, not a new bill. | — |
| 7 | **Other utility** | Any other matched email with PDF or body | PDF or body | Extract due date + ARS amount. Apply loading rules (literal, no formula). If ambiguous → don't mark read, include in report. | `<Service> - YYYY-MM.pdf` or `.eml` |

> The cookbook documents formats for maintenance only. Normal runs must call [`scripts/prepare_item.py`](scripts/prepare_item.py), which delegates extraction to [`scripts/extract_items.py`](scripts/extract_items.py) and row/range/filename policy to deterministic helpers.

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
- **M/A is always `M`.**
- Download PDF with `curl -sL --max-time 30 '<URL>'`. If response is HTML/302 → token expired. ⚠️ The email body does NOT contain structured data for extraction — leave the email unread and alert the user. Do not attempt to extract from body.
- ⚠️ `DEV.IMP. RG 5617` on page 1 is a **historical refund**, NOT current tax.
  Extract the current positive `DB.RG 5617` on the totals page. When it is
  present, the ARS cell must be the auditable locale formula
  `=<SALDO ACTUAL ARS>-<DB.RG 5617>`, never a literal total and never the
  already-subtracted result. If the `DB.RG 5617` marker is present but its
  amount is not unambiguous, fail the message; do not assume tax zero.

### Mastercard
- **M/A is always `M`.** The fourth of the six page-one dates (index 3) is
  authoritative for the due date. A negative ARS or USD balance becomes
  literal `0` as specified in Loading Rules.

### Mercado Pago
- Decimal separator in header is a **space**: `106.663 00` = $106,663.00. The "Consolidado" section uses comma normally.
- USD = 0 → load `0` literal.

### Expensas
- If no PDF (text-only email) → parse body with same patterns.
- M/A: blank. USD: blank.
- The `Expensas Período <Mes>-<Año>` subject supplies the statement period for
  **both** canonical filenames. The internal period printed on the receipt may
  describe the prior payment and must not rename the receipt. The first due
  date controls only the Sheet month and Drive `<year>/<month>` folder.

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

0. **Auth pre-check is built in.** `process_batch.py` performs Gmail discovery
   before any mutation. If authentication fails, it exits with the API error
   before acquiring sources or changing Gmail, Drive, or Sheets.
1. **Run `process_batch.py` once.** It paginates the fixed unread Gmail query,
   handles every supported message as one transaction, and prints `[SILENT]`
   when none are found. A failed source, preparation, or commit creates a
   persisted failed ledger, leaves that message unread, and continues. It
   recognizes a PagoMisCuentas confirmation as an administrative close, not a
   bill.
2. **Use its report verbatim.** Do not invoke `commit_item.py` afterwards,
   reconstruct ledgers, or compose a success claim from tool output.

## Report

- **All OK, no issues** → summary plus one direct link per archived file:
  > ✅ Procesados 2 correos (2 vencimientos) correctamente.
  > - Visa: [Visa - Resumen 2026-07 (...).pdf](https://drive.google.com/file/d/<FILE_ID>/view)
  A folder link does not substitute for per-file links.
- **Issues** → every unprocessed email and reason, plus what succeeded and all links for successful archives.
- **Nothing new** → respond with exactly `[SILENT]` (cron scheduler suppresses delivery).
- Never say that all items succeeded when a ledger failed, a target conflicted, a required artifact has no link, or a source remained unread.

## Critical Pitfalls

1. **Decimal = comma, not dot** (AR locale). Dot in formulas → `#ERROR!`.
2. **Visa URL must end in `:0`.** Without it → 302 error page.
3. **Visa PDF may return HTML** if token consumed. The body has no structured data — leave unread, alert user. Do not attempt "body fallback."
4. **Mastercard: 6 dates, index 3** is the current due date.
5. **`DEV.IMP. RG 5617` ≠ tax.** That's a historical refund on Visa page 1. Use `DB.RG` on totals page.
5a. **Visa and Mastercard M/A are `M`.** Do not infer `A` or blank from history.
5b. **Expensas names use the subject statement period; folder and Sheet use due month.**
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
19. **Never use prior runs or prior-month state as evidence.** This is a high-value correctness and isolation rule. Parse the current message and current attachment only; ambiguity is a failed transaction, not a guess.

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
- `references/pdf-regex-cookbook.md` — supported PDF formats for helper maintenance; not the normal execution path
- `scripts/row_builders.py` — canonical row and PDF primitives used by the deterministic pipeline.

## Scripts

- `scripts/cell_range.py` — compute Sheets `'Aux - Previsión'!Xn:Yn` range for a (service, month) pair. Use `--json` to dump all.
- `scripts/download_gmail_attachments.py` — download all attachments from a Gmail message. Used for Mastercard, Expensas, Mercado Pago PDFs.
- `scripts/save_gmail_eml.py` — download a Gmail message as `.eml` (RFC822 raw). Used when no PDF is available (PagoMisCuentas, other text-only utilities).
- `scripts/row_builders.py` — `build_tarjeta_row()`, `build_servicio_row()`, `_open_pdf_text()`, `_fmt_ar()` as an importable Python module. Use this instead of copying inline code from the cookbook.
- `scripts/extract_items.py` — deterministic, Decimal-safe extraction for every supported current source.
- `scripts/item_planner.py` — canonical M/A, row/range, period, folder, and filename policy.
- `scripts/prepare_item.py` — read-only one-message manifest preparation; keeps multi-service digests atomic.
- `scripts/commit_item.py` — target pre-read plus upload→write→verify→mark-read transaction; emits a ledger.
- `scripts/render_report.py` — derives success/issues text and individual artifact links exclusively from ledgers.
- `scripts/process_batch.py` — normal-run orchestrator: Gmail discovery,
  current-source acquisition, dispatch, exactly-once commit, atomic ledgers,
  temporary-source cleanup, and ledger-derived report.
