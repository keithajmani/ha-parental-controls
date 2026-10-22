"""Shared pytest setup. The Home Assistant fixtures are enabled in test_integration.py only, so the engine tests
(test_engine.py) still run with plain unittest and without Home Assistant installed.

Importing this repo's custom_components here, before any Home Assistant test instance starts, makes Home Assistant
find this integration instead of the test kit's own sample custom_components folder."""
import importlib.util

if importlib.util.find_spec("homeassistant") is not None:
    import custom_components.parental_controls  # noqa: F401
