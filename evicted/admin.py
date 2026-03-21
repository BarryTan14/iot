from django.contrib import admin
from .models import EVLot, Car, ParkingLot


@admin.register(EVLot)
class EVLotAdmin(admin.ModelAdmin):
    list_display = ("carplate", "name", "lot_number", "time_parked", "time_left", "phone", "created_at")
    list_filter = ("lot_number",)
    search_fields = ("carplate", "name", "phone")


@admin.register(Car)
class CarAdmin(admin.ModelAdmin):
    list_display = ("carplate", "type", "time_entered")
    list_filter = ("type",)
    search_fields = ("carplate",)


@admin.register(ParkingLot)
class ParkingLotAdmin(admin.ModelAdmin):
    list_display = ("lot_number", "occupied")
    list_editable = ("occupied",)

