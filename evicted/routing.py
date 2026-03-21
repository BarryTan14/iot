from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r"ws/qr-live/(?P<lot_number>[1-3])/$", consumers.QrLiveConsumer.as_asgi()),
    re_path(r"ws/qr-live/$", consumers.QrLiveConsumer.as_asgi()),
]
