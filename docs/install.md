# Installing Parental Controls

Status: Stage 3 (core control, device lists, dashboard card), v0.6.1. Installable as a HACS custom repository.

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

## Manual install

1. Copy the folder `custom_components/parental_controls` from this repo into your Home Assistant config folder as
   `/config/custom_components/parental_controls` (for example by dragging it into Studio Code Server or Samba).
2. Restart Home Assistant.
3. Optional, for a safe first try: Settings → Devices & services → Helpers → Create helper → Toggle, named
   e.g. "Parental Controls test block". It stands in for a router switch.
4. Settings → Devices & services → Add integration → Parental Controls. Enter the child's name and pick the block
   switch (the test toggle, or the router's switch for the child's group).
5. The child appears as a device "<Child> Parental Controls" with its status sensor, Block / Allow / Pause buttons,
   pause length, bedtime switch and bedtime times. Add the card to a dashboard ([The card](#the-card)), or use the
   entities or the `parental_controls.block`, `.allow` and `.pause` actions directly.

### Device lists (optional, UniFi)

6. Add hub (Add entry) → Parental Controls → **Connect a router**, once for the whole household. Pick the router type
   (UniFi for now), then enter the console's address and a local UniFi admin with the **View Only** role. The UniFi
   site is picked automatically; you are only asked if the console manages more than one.
7. On each child: Configure → **Block switch and router group** → pick the child's UniFi group and its block switch.
   The router is asked what the switch's rule blocks: a green note confirms "this switch blocks the group …"; a red one
   says which group (or single device) it blocks instead and what rule to add on the router. To keep a switch the
   router doesn't confirm (a test toggle, say), submit again unchanged. The same check runs when you add a child.
8. Configure → **Add devices**: search (e.g. `*kobo*`) and tick devices. Results are listed under two headings,
   **Can be blocked** and **Status & traffic only** (see [How devices are controlled](#how-devices-are-controlled)).
   Each line shows the device's name, online or offline, and why it's under its heading. MAC addresses are left out,
   except to tell apart two devices with the same name.
   Nothing is ticked to start with, and a device may be picked by two children. A device's own block switch is found
   on the router and saved with it; there's nothing more to choose. The **?** at the top of these setup screens opens
   [How devices are controlled](#how-devices-are-controlled) below.

   For a router type that can't say what a switch's rule targets, a **Device blocking** step follows instead, with a
   picker limited to that router integration's switches, marked "not confirmed".
9. Configure → **Devices (N)** lists the picked devices under the same two headings. Untick one to remove it from the
   child's screen and from Home Assistant.

   Rules are also followed automatically: when the router integration adds, removes, enables or disables a switch,
   each picked device's own rule is looked up again (once things have been quiet for 10 seconds) and the device moves
   between Can be blocked and Status & traffic only by itself. Only Parental Controls' own settings change; no switch is
   turned on or off. The same check also runs once a minute after Home Assistant starts, for rules made while it was
   down or on an older version. Submitting Configure → Devices does it by hand.

### How devices are controlled

(This is the page the **?** at the top of the setup screens opens.)

When you pick devices, each one lands under one of two headings, and its line says why:

- **Can be blocked · <child>'s group**: the device is in the child's router group. The child's Block, Pause and
  Bedtime cover it, and the card shows it as Blocked whenever the child is.
- **Can be blocked · own block rule**: the device is outside the child's group but has its own rule on the router that
  turns its internet off, and Home Assistant has an enabled switch for that rule. The card gives it its own block
  button. The child's Block, Pause and Bedtime don't touch it, which suits a device shared by two children.
- **Status & traffic only**: everything else. The card shows its status and traffic, with no block button.

A device in the child's group that also has its own rule is listed with the group, and its own switch is saved too.

#### Why is a device "Status & traffic only", and how do I change that?

- **There is no rule for it on the router.** On UniFi: Settings → Policy Engine → add an object that targets this
  device (Clients), set to No Internet (Secure → Turn off internet). The UniFi Network integration then shows it as a
  switch, and within about 10 seconds the device moves to Can be blocked by itself, with its block button on the card.
  (If it doesn't, open Configure → Devices and Submit.)
- **Its rule only limits speed or prioritises.** Only rules that turn internet off count. Add a No Internet object
  for it (above).
- **The line says "rule has no switch in HA".** The rule is on the router, but Home Assistant has no switch for it, or
  the switch is disabled. Reload the UniFi Network integration (Settings → Devices & services → UniFi Network → ⋮ →
  Reload), or enable the rule's switch on the entity's page; the device then moves to Can be blocked by itself.
- **It's in another child's group.** That child's Block, Pause and Bedtime cover it; this child's can't. To control it
  from this child's screen too, give it its own No Internet rule (above).
- **The rule targets a group, not the device.** Rules for another group don't count for this child; only a rule for
  this one device, or the child's own group, does.

Each picked device becomes its own device in Home Assistant, connected via the child's device, with:
**Online** (connectivity; changes only when the device comes or goes at a check), **Blocking** ("Follows <child>",
"Own block rule" or "Status & traffic only") and, only with its own rule, **Blocked**. There are no speed
entities, to keep the recorder quiet. Deleting a picked device from its device page takes it off the child too.
The "<device> blocked" switches of v0.4 are gone: the card's per-device button switches the router's rule directly.

### The router entry

On the router entry, ⋮ → **Reconfigure** changes the router type, address, username or password (leave the password
empty to keep it). The new details are tested before they're saved; changing the router type re-checks every child's
group and device rules and lists anything that no longer matches. If the saved login stops working, Home Assistant
shows a **Re-authenticate** prompt for it. Router entries from before v0.5 have no stored type and count as UniFi.

If a child's block switch (or a device's own block switch) goes missing or unavailable for 5 minutes, Home Assistant
shows a notice under **Settings → Repairs** explaining what to fix; it clears itself when the switch is back.

Device status is fetched only when asked (opening Devices on the card, which turns Live on for up to 5 minutes, or
Check) and the device list is not written to Home Assistant's history.

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
button, Pause (or Allow for, when blocked) with 15 / 30 / 60 and a Custom slider, and Devices.

Devices is closed to start with; tap the heading or its arrow to open or close it. Opening it turns **Live** on: the
list refreshes every 5 s and Live switches itself off after 5 minutes (or when you close Devices, or tap Live).
After that the list stays as it was, with "Checked <time>" underneath; tap **Check** for one more refresh, or Live
again. Each row shows the device's status, access point and signal, and its download and upload speeds.

Devices in the child's group read red **Blocked** whenever the child is blocked (Block, Pause or Bedtime); devices
outside it keep their real state; a device that isn't connected reads **Offline** with when it was last seen. A device
with its own block rule gets a block / allow button. Its row turns red (or back) as soon as the router confirms a tap,
usually within a second, with no spinner in between; a second tap while it waits is ignored. If the router doesn't
confirm within 10 seconds, a short message says so and what is still true ("It's still online.").

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

### The NextDNS apps card (optional)

Block or allow apps on a NextDNS profile with `custom:parental-controls-apps-card`. It uses Home Assistant's own
NextDNS integration and works without a router. Setup, options and limits: [nextdns-card.md](nextdns-card.md).

## Removing it

Remove the integration from Settings → Devices & services; its entities, saved state and card registration go with it.
The router's groups and rules are left untouched.
