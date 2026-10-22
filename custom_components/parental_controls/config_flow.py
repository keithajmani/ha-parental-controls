"""Setup: one entry per child. Name and the router's block switch for the child's group."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import CONF_BLOCK_ENTITY, CONF_CHILD_NAME, DOMAIN

# any on/off entity works as a block switch: a router integration's switch, or an input_boolean for testing
BLOCK_SELECTOR = selector.EntitySelector(selector.EntitySelectorConfig(domain=["switch", "input_boolean"]))


class ParentalControlsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_CHILD_NAME].strip()
            await self.async_set_unique_id(slugify(name))
            self._abort_if_unique_id_configured()
            used = {e.data.get(CONF_BLOCK_ENTITY) for e in self._async_current_entries()}
            if user_input[CONF_BLOCK_ENTITY] in used:
                errors[CONF_BLOCK_ENTITY] = "switch_in_use"
            else:
                return self.async_create_entry(title=name, data={CONF_CHILD_NAME: name,
                                                                 CONF_BLOCK_ENTITY: user_input[CONF_BLOCK_ENTITY]})
        return self.async_show_form(step_id="user", errors=errors, data_schema=vol.Schema({
            vol.Required(CONF_CHILD_NAME): str,
            vol.Required(CONF_BLOCK_ENTITY): BLOCK_SELECTOR,
        }))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ParentalControlsOptionsFlow()


class ParentalControlsOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_BLOCK_ENTITY, self.config_entry.data[CONF_BLOCK_ENTITY])
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Required(CONF_BLOCK_ENTITY, default=current): BLOCK_SELECTOR,
        }))
