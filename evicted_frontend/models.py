from django.db import models


class ParkingSubmission(models.Model):
    """Stores form submissions from the parking form."""
    carplate = models.CharField(max_length=20)
    name = models.CharField(max_length=255)
    time_parked = models.DateTimeField(help_text="Set when staff triggers workflow")
    time_car_left = models.DateTimeField(null=True, blank=True)
    phone = models.CharField(max_length=20)
    lot_number = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.carplate} - {self.lot_number}"


class WorkflowTrigger(models.Model):
    """Stores the last trigger time (used to pre-fill TimeParked on the form)."""
    triggered_at = models.DateTimeField(auto_now_add=True)
    lot_number = models.CharField(max_length=50, default='', blank=True)

    class Meta:
        ordering = ['-triggered_at']


class VehicleEntry(models.Model):
    """Tracks vehicle entries with carplate, type (ICE/EV), and time entered."""
    TYPE_CHOICES = [("ICE", "ICE"), ("EV", "EV")]

    carplate = models.CharField(max_length=20)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)  # ICE or EV
    time_entered = models.DateTimeField()

    class Meta:
        ordering = ["-time_entered"]
        verbose_name_plural = "Vehicle entries"

    def __str__(self):
        return f"{self.carplate} ({self.type})"
