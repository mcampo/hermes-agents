# Quick lookup — Aux - Previsión

## Service → Row

> **Row numbers are defined exclusively in [`scripts/cell_range.py`](../scripts/cell_range.py).**
> Always use `cell_range.py --json` or `from cell_range import cell_range, SERVICE_ROWS` to resolve
> row numbers — never hard-code them.

| Service | Type |
|---|---|
| Gas | Utility |
| Visa | Credit card |
| Cochera | Utility |
| Seguro Auto | Utility |
| Angélica | Utility |
| Mastercard | Credit card |
| Tarjeta MP | Credit card (encrypted PDF) |
| Expensas | Utility |
| Agua | Utility |
| ABL | Utility |
| Total | (aggregate formula — DO NOT write) |

⚠️ **Row verification:** when adding a new service, add it to `scripts/cell_range.py` and keep
this list in sync. The sheet layout is considered stable — rows are fixed mappings, not dynamic.

## Month → Column

The sheet uses **Spanish month names** as column headers. MONTH_BLOCKS keys must match.

| Month (EN) | Month (ES, sheet key) | Block | Due Day | M/A | Amount | Amount USD |
|---|---|---|---|:---:|:---:|:---:|:---:|:---:|
| June | Junio | B–E | B | C | D | E |
| July | Julio | F–I | F | G | H | I |
| August | Agosto | J–M | J | K | L | M |
| September | Septiembre | N–Q | N | O | P | Q |
| October | Octubre | R–U | R | S | T | U |
| November | Noviembre | V–Y | V | W | X | Y |
| December | Diciembre | Z–AC | Z | AA | AB | AC |

⚠️ **Sheet covers Junio–Diciembre.** If the due date falls in Enero–Mayo, don't load into the sheet — notify via Telegram instead.

## Python Range Helper

> **The canonical `SERVICE_ROWS`, `MONTH_BLOCKS`, and `cell_range()` function live in [`scripts/cell_range.py`](../scripts/cell_range.py).**
> Use `cell_range.py --json` for a full dump, or `cell_range.py --service Visa --month Junio` for a single range.
> Import programmatically with:
> ```python
> import sys
> sys.path.insert(0, '$HOME/.hermes/profiles/mojo/skills/custom/gastos-vencimientos/scripts')
> from cell_range import cell_range, SERVICE_ROWS, MONTH_BLOCKS
> ```

Each month spans 4 columns: Due Day, M/A, Amount, Amount USD. The helper stores
each month's explicit start and end columns.

## Sheet Locale

- **Thousands separator**: `.` (dot)
- **Decimal separator**: `,` (comma)
- Formulas MUST use comma as decimal (`=823130,13-744000,37`). Dot → `#ERROR!`.
- When reading with `sheets get`, numbers come back as comma-separated strings (`"79129,76"`, `"1731,24"`).
