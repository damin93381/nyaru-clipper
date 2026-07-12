# Documentation Index

This directory contains the current MVP documentation set for the Bilibili VTuber workstation.

Start here for setup and local deployment:

- `deployment-guide.md`: English deployment guide, includes the dedicated WSL + ROCm install, doctor, shared runtime, and smoke path
- `deployment-guide.zh-CN.md`: Chinese deployment guide, includes the dedicated WSL + ROCm install, doctor, shared runtime, and smoke path

Available documents:

- `user-manual.md`: English user manual
- `operator-manual.md`: English operator manual
- `deployment-guide.md`: English deployment guide
- `wsl-rocm-investigation.zh-CN.md`: Chinese WSL + ROCm investigation note, root cause background for the dedicated support path
- `wireframes.md`: English MVP wireframes
- `processing-flow.md`: English processing flow and artifact layout
- `README.zh-CN.md`: Chinese documentation index
- `user-manual.zh-CN.md`: Chinese user manual
- `operator-manual.zh-CN.md`: Chinese operator manual
- `deployment-guide.zh-CN.md`: Chinese deployment guide
- `wireframes.zh-CN.md`: Chinese MVP wireframes
- `processing-flow.zh-CN.md`: Chinese processing flow and artifact layout

The deployment guides are the fastest way to reach the supported local and self-hosted workflows. If you need WSL + ROCm, start from the deployment guides first, then use the operator manuals after the stack is up and reachable.

The English and Chinese manuals are kept as parallel document sets so operators and users can work in either language without losing MVP scope fidelity.

The operator and deployment guides now also document the current ASR lifecycle observability contract, including active phase timing visibility, `cancel_requested` overlay behavior, the narrower `force-kill` availability rules, worker execution-token boundaries for stage updates, and the developer regression commands for backend/frontend task-state changes.
