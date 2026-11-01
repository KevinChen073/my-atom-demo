# MYATOM code repository constraints

The product and architecture baseline lives in this repository: `docs/PRD.md`, `docs/ARCHITECTURE.md`, and `docs/decisions/`. Before changing behavior, read them. Atoms research and Spike process records live separately at `D:\AI\ATOM笔试\docs` on this machine; if they are unavailable, obtain the latest evidence before making platform compatibility claims.

- Use React + TypeScript + Vite for generated Web apps and Python + LangGraph for the single main Agent, as specified in the baseline.
- On the user-authorized `atom-deploy` branch, `APP_ENV=atom` follows [ADR-018](docs/decisions/ADR-018-atom-single-process-static-branch.md): generated apps are static HTML/CSS/JS and the runtime uses one Python process. The original template remains the baseline for other modes.
- Keep infrastructure, model, storage, runner, and preview implementations behind replaceable interfaces until the Atoms compatibility Spikes have evidence.
- Any new requirement or implementation finding that conflicts with the existing PRD or architecture must be presented to the user for confirmation **before** changing those documents or implementing the conflicting design. Do not silently overwrite the baseline.
- Maintain meaningful design, frontend, backend, and end-to-end test cases with the implementation. Test relevant flows before delivery and state what remains unverified.
- Never put credentials in source, generated apps, logs, or browser bundles. `.env` is local and ignored by Git.
- Do not commit, push, publish, or buy cloud resources without the user's explicit authorization.
