# Installing Parental Controls

Status: Stage 3 (core control, device lists, dashboard card), v0.5.2. Installable as a HACS custom repository.

## Requirements

- Home Assistant 2025.x or later.
- A supported router. UniFi first: a UniFi gateway running the UniFi Network application, with
  - a group per child, and a blocking rule per child group (a Policy Engine object for the group, set to No Internet);
  - for a device blocked on its own, a Policy Engine object for that device, set to No Internet (until the
    integration can create them);
  - a local, view-only UniFi admin for device status and speeds.
- HACS, for the one-click install.
- **No other HACS components are needed.** The cards are built into the integration and use only Home Assistant's own
  building blocks: no Mushroom, button-card, card-mod or similar. The integration registers its card itself.
- A switch that blocks each child on the router. For UniFi, the built-in **UniFi Network** integration (no HACS)
  provides one per UniFi group or client rule.

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
7. On each child: Configure → **Block switch and router group** → pick the child's UniFi group and its block switch.
   The router is asked what the switch's rule blocks: a green note confirms "this switch blocks the group …"; a red one
   says which group (or single device) it blocks instead and what rule to add on the router. To keep a switch the
   router doesn't confirm (a test toggle, say), submit again unchanged. The same check runs when you add a child.
8. Configure → **Add devices**: search (e.g. `*kobo*`) and tick devices. Results are listed under headings: the
   child's group first, then each other group (with a note that the child's Block, Pause and Bedtime won't reach
   those), then devices in no group. Nothing is ticked to start with, and a device may be picked by two children.
9. **Device blocking** follows and shows how each picked device will be controlled:
   - in the child's group: Block, Pause and Bedtime cover it;
   - its own block rule: when the router has a rule that turns off internet for that one device, its switch is
     filled in (only switches whose rule targets that device are offered). Clear it to keep the device for status
     and statistics only;
   - status and statistics only: no block rule for this device on the router. Add one on the router (UniFi: a Policy
     Engine object for that device, set to No Internet), then open Configure → **Devices** and Submit; it appears.

   For a router type that can't say what a switch's rule targets, each device gets a picker limited to that router
   integration's switches, marked "not confirmed".
10. Configure → **Devices (N)** lists the picked devices under the same headings ("Own block rule" and "Status and
   statistics only" too). Untick one to remove it from the child's screen and from Home Assistant.

Each picked device becomes its own device in Home Assistant, connected via the child's device, with:
**Online** (connectivity; changes only when the device comes or goes at a check), **Blocking** ("Follows <child>",
"Own block rule" or "Status and statistics only") and, only with its own rule, **Blocked**. There are no speed
entities, to keep the recorder quiet. Deleting a picked device from its device page takes it off the child too.
The "<device> blocked" switches of v0.4 are gone: the card's per-device button switches the router's rule directly.

### The router entry

On the router entry, ⋮ → **Reconfigure** changes the router type, address, username or password (leave the password
empty to keep it). The new details are tested before they're saved; changing the router type re-checks every child's
group and device rules and lists anything that no longer matches. If the saved login stops working, Home Assistant
shows a **Re-authenticate** prompt for it. Router entries from before v0.5 have no stored type and count as UniFi.

If a child's block switch (or a device's own block switch) goes missing or unavailable for 5 minutes, Home Assistant
shows a notice under **Settings → Repairs** explaining what to fix; it clears itself when the switch is back.

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
# show_bedtime: false          (optional; true adds a collapsible Bedtime section at the bottom)
```

One card per child, typically one dashboard view (tab) per child. The card shows the status with a Block / Allow
button, Pause (or Allow for, when blocked) with 15 / 30 / 60 and a Custom slider, and Devices (tap the heading or its arrow to open or close;
opening it runs a check; Live refreshes every 5 s). Devices in the child's group read red **Blocked** whenever the
child is blocked (Block, Pause or Bedtime); devices outside it keep their real state with a small **Stats only** tag; a
device that isn't connected reads **Offline** with when it was last seen. A device with its own block rule gets a
block / allow button.
Tap the Bedtime pill in the status box (the one with the small arrow) to change that child's bedtime: on/off and the
three times, in a pop-up. After an update, refresh the browser (or the app) once so it loads the new card.

### The settings card

```yaml
type: custom:parental-controls-settings-card
# entities: [sensor.riley_parental_controls_internet]   (optional; default: every child)
# title: Bedtime                                         (optional)
# step: 15                                               (optional; minutes per - / + press)
```

One card for the whole household: per child, Bedtime on/off and the three times (Sun-Thu off at, Fri & Sat off at,
Back on at) with - / + buttons. The same settings stay available on each child's device page.

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
