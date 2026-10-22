# Parental Controls for Home Assistant

Block, pause and schedule each child's internet on your home router from one Home Assistant screen per child.
Optional per-device controls and device status (UniFi first).

> **Early draft — not ready for general use.** Stage 3 of 4: core control, device lists and the dashboard card work
> and are tested, but the setup may still change without a migration path.

Status: **Stage 3** — per-child block / pause / allow-for / bedtime, UniFi device lists with per-device blocks, and a dashboard card (`custom:parental-controls-card`).
Install by hand or as a HACS custom repository: see [docs/install.md](docs/install.md).

- Design: [docs/design.md](docs/design.md)
- Install (planned): [docs/install.md](docs/install.md)
- Rules engine: `custom_components/parental_controls/engine.py` (pure Python, no Home Assistant imports)
- Router interface: `custom_components/parental_controls/provider.py`

Tests:

```
python3 -m unittest discover -s tests -p "test_engine.py" -v     # rules only, any Python 3.10+
python3.13 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest                                        # everything, inside a Home Assistant test instance
```
