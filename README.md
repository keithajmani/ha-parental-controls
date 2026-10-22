# Parental Controls for Home Assistant

Block, pause and schedule each child's internet on your home router from one Home Assistant screen per child.
Optional per-device controls and device status (UniFi first).

> **Early draft — not ready for general use.** This is Stage 1 of 4: the core control works and is tested, but
> there is no dashboard card yet, device control is not built, and the setup may change without a migration path.

Status: **Stage 1** — per-child block / pause / allow-for / bedtime, set up from the UI, with tests.
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
