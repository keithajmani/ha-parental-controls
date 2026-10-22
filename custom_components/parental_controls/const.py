"""Constants for Parental Controls."""
DOMAIN = "parental_controls"

CONF_CHILD_NAME = "child_name"
CONF_BLOCK_ENTITY = "block_entity"     # the router's block switch for the child's group (switch or input_boolean)

DEFAULT_PAUSE_MINUTES = 15
MIN_PAUSE_MINUTES = 1
MAX_PAUSE_MINUTES = 240
TICK_SECONDS = 30                      # bedtime starts/ends are applied within this many seconds

STORAGE_VERSION = 1
