# Installing Parental Controls

Status: Stage 3 (core control, device lists, dashboard card). Installable as a HACS custom repository.

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

### Device lists (optional, UniFi)

6. Add hub (Add entry) → Parental Controls → **Connect a router**, once for the whole household. Pick the router type
   (UniFi for now), then enter the console's address and a local UniFi admin with the **View Only** role. The UniFi
   site is picked automatically; you are only asked if the console manages more than one.
7. On each child: Configure → **Block switch and router group** → pick the child's UniFi group. Its devices now
   appear in the child's **Devices** sensor after **Check devices** (or while **Live devices** is on).
8. Configure → **Add devices**: search (e.g. `*kobo*`), pick devices, and optionally give each one its own block
   switch. A device outside the child's group is listed on the child's screen; a device inside it can be blocked
   on its own while the rest of the group stays online. Each device with a block switch gets a
   "<device> blocked" switch on the child.

Device status is fetched only when asked (Check devices, or Live for up to 5 minutes) and the device list is not
written to Home Assistant's history.

### The card

The integration serves its own card and adds it to the dashboard resources automatically (and updates the entry on each
version). Only if your dashboards are in YAML mode, add `/parental_controls/parental-controls-card.js` as a resource of
type module yourself. Edit a dashboard → Add card → search
"Parental Controls", pick the child, or in YAML:

```yaml
type: custom:parental-controls-card
entity: sensor.riley_parental_controls_internet   # the child's Internet sensor
# title: Riley's Internet      (optional; default "<Child>'s Internet", empty string to hide)
# max_minutes: 60              (optional; the Custom slider's maximum)
```

One card per child, typically one dashboard view (tab) per child. The card shows the status with a Block / Allow
button, Pause (or Allow for, when blocked) with 15 / 30 / 60 and a Custom slider, and Devices (tap to show;
opening it runs a check; Live refreshes every 5 s). A device with its own block switch gets a block / allow button.
After an update, refresh the browser (or the app) once so it loads the new card.

To remove: delete the integration entries, then the folder, then restart.

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
