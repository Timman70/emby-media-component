# Custom Emby Component - Modified by timcloud

import logging
import aiohttp
from datetime import timedelta

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
)
from homeassistant.components.media_player.const import MediaPlayerState
from homeassistant.const import CONF_URL
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, CONF_API_KEY

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=30)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    host = entry.data["host"]
    port = entry.data["port"]
    url = f"http://{host}:{port}"
    api_key = entry.data[CONF_API_KEY]

    session = aiohttp.ClientSession()
    coordinator = EmbyDataCoordinator(hass, session, url, api_key)
    await coordinator.async_config_entry_first_refresh()

    entities = []
    for client_id, session_data in coordinator.data.items():
        entities.append(EmbyClientPlayer(session_data, coordinator, client_id, url, api_key))

    async_add_entities(entities, True)


class EmbyDataCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, session, url, api_key):
        self.session = session
        self.url = url
        self.api_key = api_key
        super().__init__(
            hass,
            _LOGGER,
            name="Emby Sessions",
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self):
        try:
            headers = {"X-Emby-Token": self.api_key}
            async with self.session.get(f"{self.url}/emby/Sessions", headers=headers) as resp:
                if resp.status != 200:
                    raise UpdateFailed(f"HTTP {resp.status}")
                sessions = await resp.json()

            all_clients = {}
            for s in sessions:
                _LOGGER.debug("Session received: %s", s)
                client_id = s.get("InternalDeviceId") or s.get("Id") or s.get("DeviceName")
                if client_id:
                    all_clients[str(client_id)] = s
            return all_clients
        except Exception as e:
            raise UpdateFailed(f"Error fetching Emby sessions: {e}")


class EmbyClientPlayer(MediaPlayerEntity):
    _attr_supported_features = (
        MediaPlayerEntityFeature.PAUSE |
        MediaPlayerEntityFeature.STOP |
        MediaPlayerEntityFeature.PLAY
    )

    def __init__(self, session_data, coordinator, client_id, url, api_key):
        self._session = session_data
        self._coordinator = coordinator
        self._client_id = client_id
        self._url = url
        self._api_key = api_key

        user = session_data.get("UserName", "")
        device = session_data.get("DeviceName") or session_data.get("Client") or "Emby Client"
        self._attr_name = f"{user} - {device}".strip(" -")
        self._attr_unique_id = f"emby_{client_id}"

    @property
    def state(self):
        playstate = self._session.get("PlayState", {})
        if playstate.get("IsPaused"):
            return MediaPlayerState.PAUSED
        if playstate.get("IsPlaying"):
            return MediaPlayerState.PLAYING
        return MediaPlayerState.IDLE

    @property
    def media_title(self):
        return self._session.get("NowPlayingItem", {}).get("Name", "")

    @property
    def media_image_url(self):
        item = self._session.get("NowPlayingItem")
        if not item:
            return None
        item_id = item.get("Id")
        return f"{self._url}/Items/{item_id}/Images/Primary?api_key={self._api_key}"

    async def async_media_pause(self):
        await self._send_command("Pause")

    async def async_media_play(self):
        await self._send_command("Unpause")

    async def async_media_stop(self):
        await self._send_command("Stop")

    async def _send_command(self, command):
        session_id = self._session.get("Id")
        if not session_id:
            _LOGGER.warning("No session ID found for client %s; cannot send command.", self._attr_name)
            return
        endpoint = f"{self._url}/emby/Sessions/{session_id}/Command?Command={command}"
        headers = {"X-Emby-Token": self._api_key}
        async with aiohttp.ClientSession() as session:
            async with session.post(endpoint, headers=headers) as resp:
                if resp.status != 204:
                    _LOGGER.warning("Command %s failed with status %s", command, resp.status)

    async def async_update(self):
        await self._coordinator.async_request_refresh()
        self._session = self._coordinator.data.get(self._client_id, {})
