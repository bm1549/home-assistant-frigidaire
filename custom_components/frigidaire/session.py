"""Where each config entry keeps its Frigidaire session.

Each entry has its own file so multiple accounts do not clobber each other's sessions,
which forced re-authentication and tripped Frigidaire's active-session cap (cas_3403).
The config flow runs before an entry id exists and uses the legacy shared file; setup
migrates from it once.
"""

from __future__ import annotations

import os

from frigidaire import JsonFileSessionStore

LEGACY_SESSION_FILE = "frigidaire.json"


def session_store(config_dir: str, entry_id: str | None) -> JsonFileSessionStore:
    name = f"frigidaire-{entry_id}.json" if entry_id else LEGACY_SESSION_FILE
    return JsonFileSessionStore(os.path.join(config_dir, name))


def initial_session(config_dir: str, entry_id: str) -> tuple[str | None, str | None]:
    """The entry's own session, falling back to the legacy shared file for a one-time migration."""
    session_key, regional_base_url = session_store(config_dir, entry_id).load()
    if session_key is None:
        session_key, regional_base_url = session_store(config_dir, None).load()
    return session_key, regional_base_url
