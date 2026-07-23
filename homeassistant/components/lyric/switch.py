"""Support for Honeywell Lyric switch platform."""

import asyncio
import logging
from typing import Any, override

from aiolyric.objects.device import LyricDevice
from aiolyric.objects.location import LyricLocation

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import LYRIC_EXCEPTIONS
from .coordinator import LyricConfigEntry, LyricDataUpdateCoordinator
from .entity import LyricDeviceEntity

_LOGGER = logging.getLogger(__name__)

LYRIC_HVAC_MODE_HEAT = "Heat"
LYRIC_HVAC_MODE_EMERGENCY_HEAT = "EmergencyHeat"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LyricConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Honeywell Lyric switch entities based on a config entry."""
    coordinator = entry.runtime_data

    async_add_entities(
        LyricEmergencyHeatSwitch(coordinator, location, device)
        for location in coordinator.data.locations
        for device in location.devices
        if LYRIC_HVAC_MODE_EMERGENCY_HEAT in device.allowed_modes
    )


class LyricEmergencyHeatSwitch(LyricDeviceEntity, SwitchEntity):
    """Switch entity for Honeywell Lyric emergency heat."""

    _attr_translation_key = "emergency_heat"

    def __init__(
        self,
        coordinator: LyricDataUpdateCoordinator,
        location: LyricLocation,
        device: LyricDevice,
    ) -> None:
        """Initialize the emergency heat switch."""
        super().__init__(
            coordinator,
            location,
            device,
            f"{device.mac_id}_emergency_heat",
        )
        # Tracks the mode to restore to when emergency heat is turned off.
        # Only valid for the lifetime of this entity instance.
        self._previous_mode: str | None = None

    @property
    @override
    def is_on(self) -> bool:
        """Return true if emergency heat is active.

        Some LCC devices (e.g. T9/T10) report `mode` as "Heat" even while
        emergency heat is active - the actual on/off state lives in the
        separate `emergencyHeatActive` field on changeableValues.
        """
        return bool(self.device.changeable_values.emergency_heat_active)

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn emergency heat on, remembering the current mode to restore later."""
        current_mode = self.device.changeable_values.mode
        if current_mode != LYRIC_HVAC_MODE_EMERGENCY_HEAT:
            self._previous_mode = current_mode

        _LOGGER.debug("Set emergency heat on")
        try:
            await self.coordinator.data.update_thermostat(
                self.location,
                self.device,
                mode=LYRIC_HVAC_MODE_EMERGENCY_HEAT,
                thermostat_setpoint_status=self.device.changeable_values.thermostat_setpoint_status,
            )
        except LYRIC_EXCEPTIONS as exception:
            raise HomeAssistantError(
                f"Failed to turn on emergency heat: {exception}"
            ) from exception
        # The Honeywell API can lag before a mode/state change is reflected
        # on a subsequent GET. See similar handling in
        # _async_set_hvac_mode_tcc in climate.py.
        await asyncio.sleep(3)
        await self.coordinator.async_refresh()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn emergency heat off, restoring the previous mode."""
        restore_mode = self._previous_mode or LYRIC_HVAC_MODE_HEAT

        _LOGGER.debug("Set emergency heat off, restoring mode: %s", restore_mode)
        try:
            await self.coordinator.data.update_thermostat(
                self.location,
                self.device,
                mode=restore_mode,
                thermostat_setpoint_status=self.device.changeable_values.thermostat_setpoint_status,
            )
        except LYRIC_EXCEPTIONS as exception:
            raise HomeAssistantError(
                f"Failed to turn off emergency heat: {exception}"
            ) from exception
        self._previous_mode = None
        await asyncio.sleep(3)
        await self.coordinator.async_refresh()
