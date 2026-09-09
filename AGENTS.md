# Working in this repo

Paired with bm1549/frigidaire. The library owns the appliance model: enums, `Appliance` accessors, `set_*` command sequencing, typed errors, session store, and `frigidaire.testing`. This repo is Home Assistant glue only. Device knowledge goes in the library, not here.

## Setup and checks

```
uv venv --python 3.14 .venv && uv pip install -r requirements_test.txt
.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Against an unreleased library: `uv pip install -e ../frigidaire`, then deselect `tests/test_requirements.py::test_installed_frigidaire_matches_manifest_pin`.

## Tests

- `setup_entry` fixture: records in, `(entry, stub)` out. `stub` is `frigidaire.testing.FakeFrigidaire`; assert sent commands on `stub.commands`, parsed data on `entry.runtime_data.data[appliance_id]`.
- Sample records: `LEGACY_AC` (uppercase firmware), `TELICA_AC` (lowercase), `DEHUMIDIFIER`, adjusted with `with_reported`.
- Poll: `async_fire_time_changed(now + 31s)` then `async_block_till_done(wait_background_tasks=True)`. Each fire is relative to real now, not the previous fire.
- Real payloads live in closed issues: #49, #75, #76, #87, #121, frigidaire#25, frigidaire#43.

## Rules

- No maintainer hardware. Land a change unconfirmed only if its worst case is "does not help on some model", never "existing behaviour breaks".
- Unique IDs, entity names, attribute keys and option keys are user-facing. Keep them.
- Every push to main auto-releases a patch bump. `manifest.json` and `requirements_test.txt` must pin the same published library version; a library release auto-opens a bump PR here.
- Commit messages: one subject line, no body, no trailers.
