"""API key entries: live updates from the event stream, the slow resync, and quota backoff."""

import frigidaire
import pytest
from frigidaire.testing import LEGACY_AC, with_reported
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

DOMAIN = "frigidaire"


@pytest.fixture
def auth_method() -> str:
    """Every test here runs against the API key method unless it says otherwise."""
    return "api_key"


def climate_state(hass: HomeAssistant) -> str:
    return hass.states.get(er.async_get(hass).async_get_entity_id("climate", DOMAIN, "AC-LEGACY-1")).state


def reauth_flows(hass: HomeAssistant) -> list[dict]:
    return [
        f for f in hass.config_entries.flow.async_progress_by_handler(DOMAIN) if f["context"]["source"] == SOURCE_REAUTH
    ]


# --- the stream ---


async def test_the_stream_runs_for_the_life_of_the_entry(hass: HomeAssistant, setup_entry, settle) -> None:
    entry, stub = await setup_entry([LEGACY_AC])

    coordinator = entry.runtime_data
    assert stub.listening
    assert coordinator.stream_connected

    assert await hass.config_entries.async_unload(entry.entry_id)
    await settle()

    assert not stub.listening
    assert not coordinator.stream_connected


@pytest.mark.parametrize("auth_method", ["password"])
async def test_password_entries_have_no_stream(hass: HomeAssistant, setup_entry) -> None:
    entry, stub = await setup_entry([LEGACY_AC])

    assert not stub.listening
    assert not entry.runtime_data.stream_connected


async def test_a_pushed_record_updates_entities_without_a_fetch(hass: HomeAssistant, setup_entry, settle) -> None:
    entry, stub = await setup_entry([LEGACY_AC])
    assert climate_state(hass) == "cool"

    await stub.push(with_reported(LEGACY_AC, mode="FANONLY"))
    await settle()

    assert climate_state(hass) == "fan_only"
    assert entry.runtime_data.data["AC-LEGACY-1"].mode is frigidaire.Mode.FAN
    assert (stub.fetch_count, stub.record_fetch_count) == (1, 0)


async def test_pushed_records_go_through_the_ingest_helper(hass: HomeAssistant, setup_entry, settle) -> None:
    """The compressor estimate follows pushes as it follows fetches."""
    entry, stub = await setup_entry([LEGACY_AC], options={"AC-LEGACY-1": {"compressor": True}})
    coordinator = entry.runtime_data
    assert coordinator.compressor_estimate("AC-LEGACY-1") is True  # 75 °F room, 72 °F target, cooling

    await stub.push(with_reported(LEGACY_AC, mode="OFF"))
    await settle()

    assert coordinator.compressor_estimate("AC-LEGACY-1") is False


async def test_each_reconnect_triggers_one_full_resync(hass: HomeAssistant, setup_entry, settle) -> None:
    entry, stub = await setup_entry([LEGACY_AC])
    # The stream's first connection follows setup's own fetch, so it costs nothing extra.
    assert stub.fetch_count == 1
    # A change the stream missed while it was down.
    stub.records["AC-LEGACY-1"]["properties"]["reported"]["mode"] = "FANONLY"

    await stub.reconnect()
    await settle()

    assert stub.fetch_count == 2
    assert entry.runtime_data.stream_connected
    assert climate_state(hass) == "fan_only"


async def test_a_rejected_stream_starts_reauth(hass: HomeAssistant, frigidaire_stub, add_entry, method, settle) -> None:
    stub = frigidaire_stub([LEGACY_AC])
    stub.listen_error = frigidaire.AuthenticationError("Rejected", status_code=401)
    entry = add_entry(data=method.entry_data)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle()

    flows = reauth_flows(hass)
    assert len(flows) == 1
    assert flows[0]["context"]["entry_id"] == entry.entry_id


async def test_a_stream_that_gives_up_is_restarted_later(
    hass: HomeAssistant, frigidaire_stub, add_entry, method, settle, poll, caplog: pytest.LogCaptureFixture
) -> None:
    stub = frigidaire_stub([LEGACY_AC])
    stub.listen_error = frigidaire.FrigidaireException("The live update stream ended")
    entry = add_entry(data=method.entry_data)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle()
    assert not stub.listening
    assert "Live updates stopped" in caplog.text
    assert reauth_flows(hass) == []

    stub.listen_error = None
    await poll(seconds=61)

    assert stub.listening
    assert entry.runtime_data.stream_connected


async def test_unloading_cancels_a_pending_stream_restart(
    hass: HomeAssistant, frigidaire_stub, add_entry, method, settle, poll
) -> None:
    stub = frigidaire_stub([LEGACY_AC])
    stub.listen_error = frigidaire.FrigidaireException("The live update stream ended")
    entry = add_entry(data=method.entry_data)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await settle()

    assert await hass.config_entries.async_unload(entry.entry_id)
    stub.listen_error = None
    await poll(seconds=61)

    assert not stub.listening


# --- the resync ---


async def test_api_key_entries_resync_every_five_minutes(hass: HomeAssistant, setup_entry, poll) -> None:
    _entry, stub = await setup_entry([LEGACY_AC])

    await poll(seconds=31)
    assert stub.fetch_count == 1

    await poll(seconds=301)
    assert stub.fetch_count == 2


@pytest.mark.parametrize("auth_method", ["password"])
async def test_password_entries_still_poll_every_30_seconds(hass: HomeAssistant, setup_entry, poll) -> None:
    _entry, stub = await setup_entry([LEGACY_AC])

    await poll(seconds=31)

    assert stub.fetch_count == 2


# --- quota ---


async def test_quota_exceeded_backs_off_for_the_retry_after_hint(
    hass: HomeAssistant, setup_entry, poll, caplog: pytest.LogCaptureFixture
) -> None:
    entry, stub = await setup_entry([LEGACY_AC])
    stub.error = frigidaire.QuotaExceededError("Quota used up", retry_after=3600, status_code=429)

    await poll()
    assert stub.fetch_count == 2
    assert "Rate limited by Frigidaire (status=429)" in caplog.text
    stub.error = None

    # Well past the normal backoff, still inside the server's hint.
    await poll(seconds=1800)
    assert stub.fetch_count == 2

    await poll(seconds=3601)
    assert stub.fetch_count == 3
    assert entry.runtime_data.last_update_success
    assert entry.state is ConfigEntryState.LOADED

    # Back to the normal interval afterwards.
    await poll(seconds=3601 + 301)
    assert stub.fetch_count == 4


async def test_a_push_during_a_quota_backoff_does_not_cut_it_short(hass: HomeAssistant, setup_entry, poll) -> None:
    """A push reschedules the resync; it must not reschedule it at the normal 5 minutes."""
    _entry, stub = await setup_entry([LEGACY_AC])
    stub.error = frigidaire.QuotaExceededError("Quota used up", retry_after=3600, status_code=429)
    await poll()
    stub.error = None

    await stub.push(with_reported(LEGACY_AC, mode="FANONLY"))
    await poll(seconds=400)

    assert stub.fetch_count == 2
    assert climate_state(hass) == "fan_only"


async def test_a_reconnect_during_a_quota_backoff_waits_for_it(hass: HomeAssistant, setup_entry, poll, settle) -> None:
    _entry, stub = await setup_entry([LEGACY_AC])
    stub.error = frigidaire.QuotaExceededError("Quota used up", retry_after=3600, status_code=429)
    await poll()
    stub.error = None

    await stub.reconnect()
    await settle()
    assert stub.fetch_count == 2

    await poll(seconds=3601)
    assert stub.fetch_count == 3


async def test_quota_exceeded_without_a_hint_uses_the_normal_backoff(hass: HomeAssistant, setup_entry, poll) -> None:
    _entry, stub = await setup_entry([LEGACY_AC])
    stub.error = frigidaire.QuotaExceededError("Quota used up", status_code=429)

    await poll()
    stub.error = None
    await poll(seconds=500)
    assert stub.fetch_count == 2

    await poll(seconds=601)
    assert stub.fetch_count == 3
