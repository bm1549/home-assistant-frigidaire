"""Test config: make the HA-free auth_store module importable without Home Assistant.

The integration package (config_flow, __init__) imports `homeassistant`, which is
not installed in this dev environment. `auth_store` deliberately imports only the
stdlib, so we add its directory to sys.path and import it directly.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "frigidaire"))
