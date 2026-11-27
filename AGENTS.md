# Working in this repo

Paired with bm1549/frigidaire. The library owns the appliance model: enums, `Appliance` accessors, `set_*` command sequencing, typed errors, session store, and `frigidaire.testing`. This repo is Home Assistant glue only. Device knowledge goes in the library, not here.

## Setup and checks

```
uv venv --python 3.14 .venv && uv pip install -r requirements_test.txt
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Against an unreleased library: `uv pip install -e ../frigidaire`, then deselect `tests/test_requirements.py::test_installed_frigidaire_matches_manifest_pin`.

## Tests

- `setup_entry` fixture: records in, `(entry, stub)` out. `stub` is the `frigidaire.testing.FakeBackend` that the sign-in method's `build_backend` patch point returns; assert sent commands on `stub.commands`, parsed data on `entry.runtime_data.data[appliance_id]`.
- Sign-in method: the first method in `auth.METHODS` (password) unless a test parametrizes `auth_method`; `list(METHODS)` runs it for every method, `["password"]` marks a test that only makes sense for that method. The `method` fixture says what to type, the resync interval and a definite auth error. A new method adds a `MethodCase` in `tests/conftest.py`, with an installer for its fake.
- Keep shared tests method-neutral, so deleting a method is deleting its module, its METHODS line, its translations, its `test_auth_<method>.py` and the tests marked for it: no hard-coded intervals or method-specific errors outside those. Wait with the `settle` fixture rather than `async_block_till_done(wait_background_tasks=True)`.
- Sample records: `LEGACY_AC` (uppercase firmware), `TELICA_AC` (lowercase), `DEHUMIDIFIER`, adjusted with `with_reported`.
- Poll: `await poll()` (just past the method's resync interval, then settle), or `await poll(seconds=...)` for a longer step. Each fire is relative to real now, not the previous fire.
- Real payloads live in closed issues: #49, #75, #76, #87, #121, frigidaire#25, frigidaire#43.

## Rules

- No maintainer hardware. Land a change unconfirmed only if its worst case is "does not help on some model", never "existing behaviour breaks".
- Unique IDs, entity names, attribute keys and option keys are user-facing. Keep them.
- Every push to main auto-releases a patch bump. `manifest.json` and `requirements_test.txt` must pin the same published library version; a library release auto-opens a bump PR here.
- Commit messages: one subject line, no body, no trailers.
