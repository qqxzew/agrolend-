# Yehor frontend integration — 31 October 2026

Merged `Yehor` at `ee3b472` into `merge/yehor-frontend` at `99c4558`.
The merge keeps the workspace assistant, agent avatars, Germany/India parcel
selection and consent-based clusters alongside the server Coworker runtime,
deployment configuration and existing payment evidence.

Integration fixes:
- Consolidated duplicate assistant environment entries in Docker Compose.
- Resolved the test runner's Python executable before changing directories, so
  `PYTHON=/absolute/path/to/python bash scripts/test_all.sh` also runs geo tests.

Verified in this merge:
- `scripts/test_all.sh`: web syntax; 4 conversation tests; 85 gateway tests;
  all 10 original geo test files; 32 Node agent tests. All passed.
- Scripted-model end-to-end check: real Eve runtime, tools and merged gateway;
  valid German audit plan, rejected out-of-country point, missing-location
  clarification. All passed; this check creates no paid task.
- Browser: German parcel selection (191 parcels), cluster page, India region
  selection (40 Kutch, 36 Anantapur, 6 Beed fields), contextual agent avatars and
  a real assistant response explaining free registration.
- Compose YAML parses and has no duplicate environment keys; assistant key,
  model, base URL and rate limit are included.

The local preview runs in `dev-unpaid` mode. Production was not redeployed and
no real payment or registration was submitted during this merge. Docker is not
installed on this machine, so container images were not rebuilt here. Existing
production payment evidence is preserved in `docs/EVIDENCE.md` and `docs/evidence/`.
