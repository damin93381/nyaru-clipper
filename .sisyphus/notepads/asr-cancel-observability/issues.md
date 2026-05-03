## 2026-05-03T03:45:57Z Task: session-start
Known issue baseline: current ASR only honors cancellation at stage boundaries and writes too little progress information for operators to distinguish slow vs stuck execution.

## 2026-05-03T06:02:00Z Task: state-restoration
Session-tracking state can regress independently of code scope: the ASR plan file disappeared from `.sisyphus/plans/` while `.sisyphus/boulder.json` drifted to an unrelated workspace/plan, so Task 3 verification must explicitly re-check both plan presence and active-plan pointers after any cleanup pass.

## 2026-05-03T05:20:09Z Task: runner-control-regression-repair
- Parent-owned ASR child orchestration is not sufficient by itself: if `worker.py` does not activate/bind a real execution token and `task_runner.py` does not revalidate ownership at stage boundaries, the new ASR path silently bypasses cancellation/supersedence safety and stale-token aborts get misclassified as ordinary stage failures.
- The corrected approach is to keep process-group cancel semantics in `pipeline_support.py`, but restore a small execution-control layer in `task_runner.py` and `worker.py` so stage-boundary cancel finalization and stale-token exits remain control-flow, not failure-flow.
