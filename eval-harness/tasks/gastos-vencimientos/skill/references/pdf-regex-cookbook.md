# PDF Regex Cookbook — credit card statements

Validated regex patterns against real Galicia PDFs (June 2026). Apply to text extracted with `pymupdf.fitz.open()`.

## PyMuPDF Compatibility

The `_open_pdf_text()` helper (in `scripts/row_builders.py`) handles both old (≤1.23) and new (≥1.27) APIs — always import and use it, never call `doc.get_text()` directly. In 1.27+ the API changed: `Document.get_text()` was removed; you must iterate pages and extract `TextPage` per page. Direct calls will raise `AttributeError`.

No need to check versions — `_open_pdf_text()` detects the API at runtime.

## Mastercard (PDF attachment)

### Due day

Page 1 has 6 dates in `DD-MMM-YY` format. The 4th (index 3) is the current due date:

```python
import re
FECHA = r'\b(\d{1,2}-[A-Za-z]{3}-\d{2})\b'
fechas = re.findall(FECHA, text)
dia = int(fechas[3].split('-')[0])  # index 3 = current due
```

⚠️ If more than 6 matches appear (consumption table, installments), take only the first 6 from page 1.

### TOTAL A PAGAR (ARS + USD)

```python
# Typical line: "TOTAL A PAGAR\n-823.130,13\n1.731,24"
# USD may also be negative (credit balance on USD sub-account).
m = re.search(r'TOTAL\s+A\s+PAGAR\s+(-?[\d.,]+)\s+(-?[\d.,]+)', text)
if m:
    total_pesos = float(m.group(1).replace('.', '').replace(',', '.'))
    total_usd = float(m.group(2).replace('.', '').replace(',', '.'))
```

⚠️ `total_pesos` may be negative (credit balance) → sheet gets `0` literal.

### AFIP tax

```python
# Line: "PERCEP.AFIP RG 4815 30%          744.000,37"
m = re.search(r'PERCEP\.AFIP\s+RG\s+(?:4815|5617)\s+30%\s+([\d.,]+)', text)
if m:
    percepcion = float(m.group(1).replace('.', '').replace(',', '.'))
```

Also try variants: `PERCEP.RG 4815`, `PERCEP.AFIP RG 4815`.

---

## Visa (PDF downloaded from link in body)

### Download link

URL pattern: `https://www.eresumen.com.ar/msc/descargar/m/<UUID>:0`

⚠️ The `:0` suffix IS part of the URL — include it always. Without it → 302 → HTML error page.

Extract from email body (text or HTML):
```python
m = re.search(r'(https://www\.eresumen\.com\.ar/msc/descargar/m/[A-Za-z0-9-]+:0)', body)
url = m.group(1)
```

### Due day

Page 1 has it explicit:
```
VENCIMIENTO 26 Jun 26 5.306.400,91
```

```python
m = re.search(r'VENCIMIENTO\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{2,4})', text)
if m:
    dia = int(m.group(1))
```

### SALDO ACTUAL (ARS + USD)

On totals page (typically page 4):
```python
# "SALDO ACTUAL $  5.306.400,91  U$S  6.840,33"
# Both amounts may be negative (credit balance).
m = re.search(r'SALDO\s+ACTUAL\s+\$\s+(-?[\d.,]+)\s+U\$S\s+(-?[\d.,]+)', text)
if m:
    total_pesos = float(m.group(1).replace('.', '').replace(',', '.'))
    total_usd = float(m.group(2).replace('.', '').replace(',', '.'))
```

### AFIP tax (DB.RG 5617)

On totals page (NOT page 1):
```python
# "DB.RG 5617  30% (  9821285,46 )                             2.946.385,63"
m = re.search(r'DB\.RG\s+5617\s+30%.*?\s+([\d.,]+)\s*$', text, re.MULTILINE)
if m:
    percepcion = float(m.group(1).replace('.', '').replace(',', '.'))
```

⚠️ Do NOT confuse with `DEV.IMP. RG 5617` on page 1 — that's a historical REFUND from the previous month, already subtracted from the current balance. This regex uses `DB.RG` (not `DEV.IMP`) to avoid the false positive. If only `DEV.IMP.` appears, there is no new tax this month → use the total directly.

---

## Mercado Pago (PDF attachment, password-protected)

### Opening the PDF

The PDF is encrypted. Password = first 5 digits of Mariano's DNI: `31507`.

```python
import fitz
doc = fitz.open(path)
if doc.is_encrypted:
    doc.authenticate("31507")
text = _open_pdf_text(path, password="31507")
```

### Due day

Page 1, explicit line:
```
Fecha de vencimiento
17 de junio
```

```python
m = re.search(r'Fecha de vencimiento\s+(\d{1,2})\s+de\s+([A-Za-záéíóú]+)', text)
if m:
    dia = int(m.group(1))
```

Fallback on page 3 (billing cycle):
```python
m = re.search(r'Vencimiento actual\s+(\d{1,2})\s+de\s+([A-Za-záéíóú]+)', text)
```

### Total to pay (ARS + USD)

⚠️ Page 1 header uses SPACE as decimal separator (not comma):
```
Total a pagar
$ 106.663 00
US$ 0 00
```

ARS:
```python
m = re.search(r'Total a pagar\s+\$\s+(-?[\d.]+)\s+(\d{2})', text)
if m:
    total_pesos = float(f"{m.group(1)},{m.group(2)}".replace('.', '').replace(',', '.'))
```

USD — anchored to the "Total a pagar" section to avoid matching other USD references:
```python
m = re.search(r'Total a pagar[\s\S]*?US\$\s+([\d.]+)\s+(\d{2})', text)
if m:
    total_usd = float(f"{m.group(1)},{m.group(2)}".replace('.', '').replace(',', '.'))
```

Note: the "Consolidado" section on page 1 uses normal comma decimal (`$ 106.663,00`), but the header uses space. Both formats may appear.

### Auto-debit (M/A)

```python
if "débito automático" in text.lower() or "debito automatico" in text.lower():
    manual_auto = "A"
else:
    manual_auto = ""
```

### AFIP tax

Mercado Pago does NOT apply AFIP tax. Load as literal without formula: `build_tarjeta_row(…, percepcion=0)`.

---

## Post-extraction sanity checks

Before writing to the sheet, validate:

1. `dia` between 1 and 31
2. `total_pesos` and `total_usd` not both 0 (email is likely not a real statement)
3. `percepcion <= total_pesos` when `total_pesos > 0` (tax shouldn't exceed the total)
4. If `percepcion` is None or 0 → amount = `total_pesos` literal (no formula), unless negative

If any sanity check fails → log the email as "unprocessed", don't mark read.