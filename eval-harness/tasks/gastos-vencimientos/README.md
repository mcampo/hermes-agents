# gastos-vencimientos evaluation operations

This task is stateful and **must never run concurrently**. It shares five Gmail
messages, one evaluation Sheet tab, one evaluation Drive root, and one runtime
snapshot across every model run.

## Quiet-window procedure

1. Confirm no other evaluation or mailbox automation is running for
   `mcampo.agents@gmail.com`.
2. Confirm none of the five labeled messages would match the production predicate
   if unread. `reset.py` probes this before mutation and fails closed by
   default; the `eval` label alone does not exclude them from the production
   query. If the operator explicitly confirms production automation is inactive,
   authorize only that command with
   `GASTOS_VENCIMIENTOS_ALLOW_PRODUCTION_OVERLAP=1`; never persist the override.
3. Confirm the task-local and installed evaluation skills pass
   `verify_skill.py`. Never install this variant in the Mojo profile.
4. Run `reset.py` and require all four confirmations: exact Sheet baseline,
   empty evaluation Drive root, five unread query results, and a fresh
   `results/runtime/gastos-vencimientos/run_state.json`.
5. Run one model at a time. Do not start another task or model until validation
   and result persistence finish.
6. If Gmail history reports unrelated label activity, discard the run and
   repeat during a quieter window.
7. Run `reset.py` after integration checks or interrupted runs.

Only these external resources are in scope:

- Gmail label `eval` in `mcampo.agents@gmail.com`;
- Spreadsheet `1Qvybe0z_QoI698DRfP1uCjF9f0BcrWLuriaw976mOZs`, tab
  `Aux - Previsión` (`sheetId 1359523290`); and
- Drive root `Hermes Eval - Vencimientos`
  (`1zpLE3gXabspesoSPjkO-gGJDZZmF1zXk`).

The production Spreadsheet and Drive root must never be inspected or changed by
reset, validation, integration tests, or agent runs.

## Revision traceability

Before comparative runs, record the fixture and scoring revisions plus SHA-256
checksums of `fixtures/expected.json`, `validator.py`, `google_helper.py`, and
the complete `skill/` source tree beside the benchmark results. Do not compare
results when any of these values differ.

`gastos-vencimientos-v2` introduced populated-row field gating,
final-response-only report classification, and deterministic skill helpers.
`gastos-vencimientos-v3` added bounded Visa tabular due-date extraction and
manifest-pinned source/installed-skill integrity gates.
`gastos-vencimientos-v4` adds deterministic batch orchestration, pre-commit
atomic ledger checkpoints, exactly-once commits, and ledger-derived reporting.
`gastos-vencimientos-v5` recognizes truthful English/Spanish negated issue
phrases, adds generic executed benchmark sidecars, and retains ledgers in
harness-owned run directories. v4 and v5 are not directly comparable for
final-report deductions.
`gastos-vencimientos-v6` accepts one- or two-PDF Expensas statements
(liquidación mandatory, recibo optional) and maps AGIP to the ABL service.
v6 scores are not directly comparable with v5 on messages exercising those
paths. `benchmark-manifest.json` remains `rerun_required`
until v5 is deployed and models are rerun from a verified reset in a separately
authorized operation.

End-to-end harness acceptance does not require a model score of `1.0`. It
requires a complete reset/execution/validation/persistence cycle with no hard
safety failure. Scores below `1.0` remain valid model-performance results.
