import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)

QR_LOT_GROUP_PREFIX = "qr_lot_"


def qr_lot_group_name(lot_number):
    """Group name for WebSocket clients watching this lot. lot_number is int 1-3 or None for 'all'."""
    if lot_number is None:
        return QR_LOT_GROUP_PREFIX + "all"
    return QR_LOT_GROUP_PREFIX + str(lot_number)


class QrLiveConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for /ws/qr-live/<lot_number>/. Clients join a lot-specific group and receive show_qr messages."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lot_number = None
        self.room_group_name = None

    async def connect(self):
        self.lot_number = self.scope.get("url_route", {}).get("kwargs", {}).get("lot_number")
        self.room_group_name = qr_lot_group_name(self.lot_number)
        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if self.room_group_name:
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def qr_trigger(self, event):
        """Send the trigger payload to the WebSocket (called from channel layer)."""
        await self.send(text_data=json.dumps(event.get("payload", {})))

    async def capacity_update(self, event):
        """Send capacity status update to the WebSocket (called from channel layer)."""
        await self.send(text_data=json.dumps(event.get("payload", {})))
