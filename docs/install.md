# Installing Parental Controls

Status: Stage 1 (core control) can be installed by hand for testing. HACS install comes in Stage 4.

## Requirements

- Home Assistant 2025.x or later.
- A supported router. UniFi first: a UniFi gateway running the UniFi Network application, with
  - a group per child, and a blocking rule per child group (UniFi "Objects");
  - for per-device controls, a blocking rule per device (until the integration can create them);
  - a local, view-only UniFi admin for device status and speeds.
- HACS, for the one-click install.

## Install with HACS (custom repository)

1. HACS → ⋮ (top right) → Custom repositories → add `https://github.com/keithajmani/ha-parental-controls`,
   type **Integration**.
2. Find "Parental Controls" in HACS → Download → restart Home Assistant.
3. Continue from step 3 of the manual install below.

## Manual install (Stage 1, for testing)

1. Copy the folder `custom_components/parental_controls` from this repo into your Home Assistant config folder as
   `/config/custom_components/parental_controls` (for example by dragging it into Studio Code Server or Samba).
2. Restart Home Assistant.
3. Optional, for a safe first try: Settings → Devices & services → Helpers → Create helper → Toggle, named
   e.g. "Parental Controls test block". It stands in for a router switch.
4. Settings → Devices & services → Add integration → Parental Controls. Enter the child's name and pick the block
   switch (the test toggle, or the router's switch for the child's group).
5. The child appears as a device "<Child> Parental Controls" with its status sensor, Block / Allow / Pause buttons,
   pause length, bedtime switch and bedtime times. The card comes in Stage 3; until then use the entities or the
   `parental_controls.block`, `.allow` and `.pause` actions.

To remove: delete the integration entry, then the folder, then restart.

## Steps once it's in HACS (planned)

1. HACS → Integrations → Custom repositories → add the GitHub URL → install "Parental Controls" → restart.
2. Settings → Devices & services → Add integration → Parental Controls.
3. Pick the router and sign in with the view-only account.
4. Add a child: name, router group, optional bedtime times.
5. Optional: search devices (e.g. `*kobo*`), pick them, choose the child and whether each gets its own block control.
6. Add the card to a dashboard view: `type: custom:parental-controls-card`, `child: riley`. One view per child.

## Removing it

Remove the integration from Settings → Devices & services; its entities, saved state and card registration go with it.
The router's groups and rules are left untouched.
