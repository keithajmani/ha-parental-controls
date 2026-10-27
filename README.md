# Parental Controls for Home Assistant

Block, pause and schedule each child's internet on your home router from one Home Assistant screen per child.
Optional per-device controls and device status (UniFi first).
Optional NextDNS card to block or allow apps per NextDNS profile.

> **Early draft — not ready for general use.** Stage 3 of 4: core control, device lists and the dashboard card work
> and are tested, but the setup may still change without a migration path.

Status: **Stage 3, v0.6.0** — per-child block / pause / allow-for / bedtime, UniFi device lists with per-device blocks found from the router's own rules, a dashboard card (`custom:parental-controls-card`), and an optional NextDNS apps card (`custom:parental-controls-apps-card`).
Install by hand or as a HACS custom repository: see [docs/install.md](docs/install.md).

- Design: [docs/design.md](docs/design.md)
- Install and use: [docs/install.md](docs/install.md)
- Optional NextDNS apps card: [docs/nextdns-card.md](docs/nextdns-card.md)
- Rules engine: `custom_components/parental_controls/engine.py` (pure Python, no Home Assistant imports)
- Router interface: `custom_components/parental_controls/provider.py`

Tests:

```
python3 -m unittest discover -s tests -p "test_engine.py" -v     # rules only, any Python 3.10+
python3.13 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest                                        # everything, inside a Home Assistant test instance
```
