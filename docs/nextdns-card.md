# NextDNS apps card

An optional card that blocks or allows apps (Instagram, YouTube, Roblox, ...) and categories (Porn, Gambling, ...)
on a NextDNS profile, from a Home Assistant dashboard. Tap an app to block it; tap again to allow it.

It uses the switches that Home Assistant's own **NextDNS** integration makes. It adds no entities, settings or
background work of its own, and it doesn't need a router or any children set up in Parental Controls.

## Requirements

- Home Assistant's built-in **NextDNS** integration (Settings → Devices & services → Add integration → NextDNS),
  with the profile you want to control. Each NextDNS profile shows up as a device, for example "Home - Kids".
- Parental Controls installed (see [install.md](install.md)), with at least one entry. If you only want this card,
  add the integration and pick **Only the NextDNS apps card**. If you've already added a child or a router, the card
  is there already.

## Where things are set

There are two levels, in two different places:

| What | Where |
|---|---|
| Which apps **can** appear | Home Assistant's **NextDNS** integration: turn the app's switch on (below). A switch turned off there can't appear on any card. |
| Which of those **this card** shows, and its title | The card's own settings (edit the dashboard, then the card). Untick an app to hide it from this card. |

The card can only narrow down; it can't show an app whose switch is turned off. With every app ticked (the
default), the card follows Home Assistant: turn on a switch and its app appears, in a new group if needed. Once you
untick something, the card keeps the list you picked, and apps you turn on later need ticking in.

The Parental Controls integration's own settings (Settings → Devices & services → Parental Controls) have nothing
for this card.

The card is its own file, `/parental_controls/nextdns-apps-card.js`, which the integration adds to your dashboard
resources by itself. Only with dashboards in YAML mode, add it yourself as a resource of type module.

## Turn on the apps you want

The NextDNS integration makes one switch per app and category for each profile, and **Home Assistant turns all of
them off (disabled) to begin with**, whatever is on your NextDNS list. The card only shows the switches you turn on.

1. Settings → Devices & services → NextDNS → open the profile's device (or use the link in the card's settings).
2. Select the line that says how many entities are not shown, to list the hidden ones.
3. Select an app (for example "Block TikTok"), open its settings (the cog), turn on **Enabled** and save.
4. Home Assistant reloads NextDNS about 30 seconds later, and the app appears on the card as **Allowed**.

What this does, and doesn't do:

- Turning a switch on in Home Assistant **doesn't block anything** or change your NextDNS account. It only lets Home
  Assistant show and control that app.
- You don't need to add the app on the NextDNS website first. The first time you block it from the card, NextDNS
  adds it to the profile's list.
- Allowing it later switches it off on NextDNS but leaves it on the list.
- An app you add on the NextDNS website stays hidden in Home Assistant until you turn its switch on there.

## Add the card

Edit a dashboard → Add card → **Parental Controls NextDNS apps**. In the card's settings:

- **NextDNS profile**: the profile to control.
- **Title**: optional. The default is the profile's name as Home Assistant shows it (the NextDNS device's name; rename
  the device to change it everywhere).
- One tick list per group, of the apps turned on in Home Assistant. Untick any you don't want on this card.
  With everything ticked, apps you turn on later appear by themselves.

Or in YAML:

```yaml
type: custom:parental-controls-apps-card
profile: 0123456789abcdef0123456789abcdef   # the profile's device id (the editor fills it in)
# title: Kids' apps                          (optional; default: the profile's name)
# apps: [instagram, youtube, roblox]         (optional; default: every app switch turned on in HA)
# icons: { roblox: "mdi:cube-outline" }      (optional; per-app icon)
```

App ids are the NextDNS ones: `instagram`, `snapchat`, `facebook`, `reddit`, `tiktok`, `twitter` (X), `youtube`,
`disneyplus`, `primevideo`, `xboxlive`, `playstation_network`, `porn`, `gambling` and so on. They're the switch's
name in Home Assistant without "Block".

## What you see

Apps appear in groups, each in its own box, two to a row: **Social**, **Messaging**, **Streaming**, **Games**,
**More** (ChatGPT, Amazon, eBay, Tinder) and **Categories**. A group with nothing in it is left out.

| Look | Means |
|---|---|
| Red, "Blocked" | NextDNS blocks it for this profile |
| Green, "Allowed" | Not blocked |
| Grey, "Unavailable" | Home Assistant can't reach NextDNS right now |
| "Blocking…" / "Allowing…" | Sent, waiting for NextDNS. If nothing comes back in 10 seconds, the card says so and shows what is still true. |

Apps without a brand icon in Home Assistant's icon set (TikTok, Telegram, Discord and others) get a plain icon.
Use `icons` to pick your own.

## Good to know

- **Changes made on the NextDNS website** take up to a minute to show here (the NextDNS integration checks every
  minute). Changes made from Home Assistant show straight away.
- **Recreation Time** on NextDNS isn't shown. During a recreation window an app can say Blocked while it works.
- **One profile per card.** For a second profile (for example a parents' one), add a second card.
- Blocking happens at NextDNS, so it covers the devices that use that profile, wherever they are. It's separate
  from the router blocking in the rest of Parental Controls.

## Removing it

Delete the card from the dashboard. If you added **Only the NextDNS apps card**, delete that entry too. The NextDNS
switches and your NextDNS settings stay as they are.
