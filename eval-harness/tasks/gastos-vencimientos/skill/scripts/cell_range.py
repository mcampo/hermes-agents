#!/usr/bin/env python3
"""
Compute the Sheets update range for a (service, month) pair.

Usage:
    cell_range.py --service Visa --month Junio
    # Output: "'Aux - Previsión'!B4:E4"

    cell_range.py --json            # dump all rows as JSON
    cell_range.py --json --month Julio  # filter by month

Used by the gastos-vencimientos cron job to deterministically
look up spreadsheet ranges without re-deriving them each time.
"""

import argparse
import json
import sys

SERVICE_ROWS = {
    'Gas': 3, 'Visa': 4, 'Cochera': 5, 'Seguro Auto': 6,
    'Angélica': 7, 'Mastercard': 8, 'Tarjeta MP': 9,
    'Expensas': 10, 'Agua': 11, 'ABL': 12,
}

# Spanish month names — these match the sheet's column headers.
MONTH_BLOCKS = {
    'Junio': 'B', 'Julio': 'F', 'Agosto': 'J',
    'Septiembre': 'N', 'Octubre': 'R', 'Noviembre': 'V',
    'Diciembre': 'Z',
}

COL_SPAN = 3


def col_to_num(letter: str) -> int:
    """Convert column letter(s) to 1-based index: A=1, Z=26, AA=27, AC=29."""
    result = 0
    for char in letter:
        result = result * 26 + (ord(char) - ord('A') + 1)
    return result


def num_to_col(n: int) -> str:
    """Convert 1-based index to column letter(s): 1=A, 26=Z, 27=AA."""
    result = ''
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(ord('A') + rem) + result
    return result


def cell_range(service: str, month: str) -> str:
    """Return the A1 range for a (service, month) pair."""
    row = SERVICE_ROWS[service]
    start_letter = MONTH_BLOCKS[month]
    start_num = col_to_num(start_letter)
    end_letter = num_to_col(start_num + COL_SPAN)
    return f"'Aux - Previsión'!{start_letter}{row}:{end_letter}{row}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute gastos-vencimientos sheet ranges."
    )
    parser.add_argument(
        "--service",
        choices=list(SERVICE_ROWS.keys()),
        help="Service name (e.g. 'Visa', 'Mastercard', 'Expensas')",
    )
    parser.add_argument(
        "--month",
        choices=list(MONTH_BLOCKS.keys()),
        help="Month in Spanish (e.g. 'Junio', 'Julio')",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Dump all service×month ranges as JSON",
    )
    args = parser.parse_args()

    if args.json:
        if args.service and args.month:
            result = {args.service: {args.month: cell_range(args.service, args.month)}}
        elif args.month:
            result = {
                svc: cell_range(svc, args.month) for svc in SERVICE_ROWS
            }
        else:
            result = {
                svc: {
                    mo: cell_range(svc, mo) for mo in MONTH_BLOCKS
                }
                for svc in SERVICE_ROWS
            }
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.service and args.month:
        print(cell_range(args.service, args.month))
    else:
        parser.error("Pass --service + --month, or --json")
    return 0


if __name__ == '__main__':
    sys.exit(main())