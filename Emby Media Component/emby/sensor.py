# Custom Emby Component - Modified by timcloud

import logging
import aiohttp
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_URL, CONF_API_KEY, CONF_USER_ID

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=5)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    host = entry.data["host"]
    port = entry.data["port"]
    url = f"http://{host}:{port}"
    api_key = entry.data[CONF_API_KEY]
    user_id = entry.data[CONF_USER_ID]

    session = aiohttp.ClientSession()
    coordinator = EmbyRecentGroupedCoordinator(hass, session, url, api_key, user_id)
    await coordinator.async_config_entry_first_refresh()

    sensors = [
        EmbyGroupedMediaSensor(coordinator, "Movie"),
        EmbyGroupedMediaSensor(coordinator, "Episode"),
        EmbyGroupedMediaSensor(coordinator, "Series")
    ]

    async_add_entities(sensors, True)

class EmbyRecentGroupedCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, session, url, api_key, user_id):
        self.session = session
        self.url = url
        self.api_key = api_key
        self.user_id = user_id
        super().__init__(
            hass,
            _LOGGER,
            name="Emby Recent Media (Grouped)",
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self):
        try:
            headers = {"X-Emby-Token": self.api_key}
            params = {
                "Limit": 10,
                "Fields": "PrimaryImageAspectRatio,DateCreated,ParentId,SeriesId,ParentIndexNumber",
            }
            async with self.session.get(
                f"{self.url}/emby/Users/{self.user_id}/Items/Latest",
                headers=headers,
                params=params
            ) as resp:
                if resp.status != 200:
                    raise UpdateFailed(f"HTTP {resp.status}")
                items = await resp.json()
                _LOGGER.debug("Fetched recent items: %s", items)
                return items
        except Exception as e:
            raise UpdateFailed(f"Error fetching Emby recent items: {e}")

class EmbyGroupedMediaSensor(SensorEntity):
    def __init__(self, coordinator, media_type):
        self._coordinator = coordinator
        self._media_type = media_type
        self._attr_name = f"Emby Latest {media_type}s"
        self._attr_unique_id = f"emby_latest_{media_type.lower()}"

    @property
    def state(self):
        item = self._get_latest_item()
        return item.get("Name") if item else "None"

    @property
    def extra_state_attributes(self):
        item = self._get_latest_item()
        if not item:
            return {}
        return {
            "release_date": item.get("PremiereDate"),
            "type": item.get("Type"),
            "library": item.get("CollectionType", "Unknown"),
            "poster_url": self._build_poster_url(item),
        }

    def _get_latest_item(self):
        items = [
            i for i in self._coordinator.data if i.get("Type") == self._media_type
        ]
        return items[0] if items else {}

    def _build_poster_url(self, item):
        base_url = self._coordinator.url
        item_id = item.get("Id")
        token = self._coordinator.api_key
        return f"{base_url}/Items/{item_id}/Images/Primary?api_key={token}"

    async def async_update(self):
        await self._coordinator.async_request_refresh()
