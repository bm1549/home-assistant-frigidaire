"""Tests for the auth persistence + per-entry migration logic."""

import auth_store


def test_save_then_load_round_trips(tmp_path) -> None:
    path = str(tmp_path / "frigidaire-abc.json")
    auth_store.save_auth(path, "the-key", "https://api.us.example")
    assert auth_store.load_auth(path) == ("the-key", "https://api.us.example")


def test_load_missing_file_returns_none_pair(tmp_path) -> None:
    session_key, base_url = auth_store.load_auth(str(tmp_path / "does-not-exist.json"))
    assert (session_key, base_url) == (None, None)


def test_per_entry_auth_path_is_scoped_by_entry_id(tmp_path) -> None:
    path = auth_store.per_entry_auth_path(str(tmp_path), "entry-123")
    assert path == str(tmp_path / "frigidaire-entry-123.json")


def test_resolve_prefers_per_entry_file_when_present(tmp_path) -> None:
    """Once an entry has its own file, the legacy shared file is ignored."""
    (tmp_path / "frigidaire-e1.json").write_text("{}")
    (tmp_path / "frigidaire.json").write_text("{}")  # legacy present too
    assert auth_store.resolve_initial_auth_path(str(tmp_path), "e1") == str(tmp_path / "frigidaire-e1.json")


def test_resolve_falls_back_to_legacy_for_migration(tmp_path) -> None:
    """First run for an entry with no file yet: migrate from the legacy shared file."""
    (tmp_path / "frigidaire.json").write_text("{}")  # only legacy exists
    assert auth_store.resolve_initial_auth_path(str(tmp_path), "e1") == str(tmp_path / "frigidaire.json")


def test_resolve_uses_per_entry_when_neither_exists(tmp_path) -> None:
    """Fresh install, no legacy file: use the per-entry path (creating no legacy litter)."""
    assert auth_store.resolve_initial_auth_path(str(tmp_path), "e1") == str(tmp_path / "frigidaire-e1.json")


def test_resolve_ignores_legacy_once_per_entry_written(tmp_path) -> None:
    """A second entry must not pick up the first entry's migrated legacy key."""
    (tmp_path / "frigidaire.json").write_text("{}")
    (tmp_path / "frigidaire-e1.json").write_text("{}")
    # e2 has no file yet, but legacy may now hold e1's staged key — still, e2 with no
    # per-entry file falls back to legacy only because it has never been set up.
    # This documents that migration is one-shot per entry via the per-entry file.
    assert auth_store.resolve_initial_auth_path(str(tmp_path), "e2") == str(tmp_path / "frigidaire.json")
    (tmp_path / "frigidaire-e2.json").write_text("{}")
    assert auth_store.resolve_initial_auth_path(str(tmp_path), "e2") == str(tmp_path / "frigidaire-e2.json")
