"""The sign-in methods, in setup-menu order.

Each method is one module exposing the same names: ``METHOD``, ``BETA``, ``RESYNC_INTERVAL``,
``SCHEMA``, ``REAUTH_SCHEMA``, ``DESCRIPTION_PLACEHOLDERS`` (for its setup form),
``RATE_LIMIT_ERRORS`` (its own errors that mean "wait and retry"), ``async_validate``,
``create_backend`` and ``async_remove``.
Shared code reaches a method only through this dictionary, so adding or removing one is a
module plus a line here.
"""

from __future__ import annotations

from types import ModuleType

from . import api_key, password

METHODS: dict[str, ModuleType] = {
    password.METHOD: password,
    api_key.METHOD: api_key,
}
