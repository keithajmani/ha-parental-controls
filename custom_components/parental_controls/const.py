"""Constants for Parental Controls."""
from datetime import timedelta

DOMAIN = "parental_controls"

CONF_CHILD_NAME = "child_name"
CONF_BLOCK_ENTITY = "block_entity"     # the router's block switch for the child's group (switch or input_boolean)

DEFAULT_PAUSE_MINUTES = 15
MIN_PAUSE_MINUTES = 1
MAX_PAUSE_MINUTES = 240
TICK_SECONDS = 30                      # bedtime starts/ends are applied within this many seconds
SWITCH_GRACE = timedelta(minutes=5)    # a block switch must be missing/unavailable this long before a Repairs issue

STORAGE_VERSION = 1

# entry kinds: one "router" entry (UniFi login) and one "child" entry per child
CONF_KIND = "kind"
KIND_CHILD = "child"
KIND_ROUTER = "router"
CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SITE = "site"
CONF_ROUTER_GROUP = "router_group"     # the child's group on the router (its members are listed under Devices)
CONF_DEVICES = "devices"               # {mac: {"name": str, "block_entity": str | None, "confirmed": bool}} picked devices
CONF_PATTERN = "pattern"

LIVE_INTERVAL = 5                      # seconds between refreshes while Live is on
LIVE_TIMEOUT = 300                     # Live switches itself off after this many seconds
CONF_VENDOR = "vendor"                 # router type (provider.ROUTER_TYPES); missing on old entries = UniFi
