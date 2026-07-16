# Quality and evaluation

SQ-BI separates deterministic regression tests from live model/data evaluation.
Both are required: unit tests establish safety and contract behavior, while a live
benchmark measures whether a multi-turn answer selects the intended asset and
returns traceable evidence within the latency budget.

## Deterministic regression suite

```bash
./scripts/test-all.sh
```

This runs all Python package tests, frontend lint, and the production frontend
build. CI executes the same command on each push and pull request.

## Live conversational benchmark

Prerequisites:

- a running SQ-BI runtime;
- an active domain-pack deployment and reachable data source;
- a configured model endpoint;
- benchmark asset names that match the installed pack.

```bash
uv run python scripts/evaluate_queries.py \
  benchmarks/tms_sim_harness_cases.json \
  --output .local/evaluation/tms-sim.json
```

Environment variables can replace command arguments:
`SQBI_EVAL_BASE_URL`, `SQBI_EVAL_USERNAME`, `SQBI_EVAL_PASSWORD`, and
`SQBI_EVAL_DATA_SOURCE_ID`.

The score checks completion, expected asset reuse, requested dimension/field,
lineage evidence and latency. Raw results are kept in the JSON report so failures
can be inspected rather than hidden behind one aggregate number. Benchmark scores
are environment-specific and should never be presented without the suite, model,
data snapshot and date.

## 2026-07-16 local baseline

The local `postgres_tms_sim` suite scored **46.67% (7/15 checks)** with the model
endpoint configured on that workstation. All four turns found the intended metric
within the latency ceiling, but none completed execution or produced lineage: the
parameter-binding model dependency timed out at roughly 26 seconds. This is a
failed usability baseline, not a claimed product accuracy score.

The run also exposed and led to a fix for an exception-classification defect:
a timeout raised *inside* a completed tool future had been reported as an outer
Harness tool deadline and its trace step was lost. The new regression test keeps
dependency timeouts in the trace. A new live baseline should be recorded after the
model endpoint is stable.

## 2026-07-16 optimized baseline

After adding an explicit model probe, bounding the underlying HTTP request (not
only its worker future), increasing the controlled parameter-binding budget, and
rejecting false `completed` results after a failed tool, the same suite was run
again with `deepseek-v4-flash`:

- score: **100% (15/15 checks)**;
- single metric: 17.3s;
- repeated first turn: 16.2s;
- conversational carrier drill-down: 22.5s;
- combined comparison/trend request: 31.9s.

All turns completed under the 45s benchmark ceiling and retained the expected
asset, requested carrier field and lineage evidence. This is a dated simulation
baseline, not a claim about arbitrary schemas or production accuracy.
