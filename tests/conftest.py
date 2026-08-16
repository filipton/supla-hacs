"""Shared test setup.

pytest-homeassistant-custom-component blocks real sockets by default, but every
test here drives the SUPLA server over a real loopback connection, so they are
re-enabled for the whole suite.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _allow_loopback_sockets(socket_enabled):
    yield
