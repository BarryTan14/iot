from django.contrib import admin
from .models import ParkingSubmission, WorkflowTrigger, VehicleEntry


@admin.register(ParkingSubmission)
class ParkingSubmissionAdmin(admin.ModelAdmin):
    list_display = ('carplate', 'name', 'lot_number', 'time_parked', 'phone', 'created_at')
    list_filter = ('lot_number',)
    search_fields = ('carplate', 'name', 'phone')


@admin.register(WorkflowTrigger)
class WorkflowTriggerAdmin(admin.ModelAdmin):
    list_display = ('triggered_at', 'lot_number')


@admin.register(VehicleEntry)
class VehicleEntryAdmin(admin.ModelAdmin):
    list_display = ('carplate', 'type', 'time_entered')
    list_filter = ('type',)
    search_fields = ('carplate',)
