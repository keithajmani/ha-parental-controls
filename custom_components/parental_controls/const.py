"""Constants for Parental Controls."""
DOMAIN = "parental_controls"

CONF_CHILD_NAME = "child_name"
CONF_BLOCK_ENTITY = "block_entity"     # the router's block switch for the child's group (switch or input_boolean)

DEFAULT_PAUSE_MINUTES = 15
MIN_PAUSE_MINUTES = 1
MAX_PAUSE_MINUTES = 240
TICK_SECONDS = 30                      # bedtime starts/ends are applied within this many seconds

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
CONF_DEVICES = "devices"               # {mac: {"name": str, "block_entity": str | None}} extra / controllable devices
CONF_PATTERN = "pattern"
CONF_PICKED = "picked"

LIVE_INTERVAL = 5                      # seconds between refreshes while Live is on
LIVE_TIMEOUT = 300                     # Live switches itself off after this many seconds
