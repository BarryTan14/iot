from django.db import models


class EVLot(models.Model):
    """EV Lots: carplate, name, time parked, time left, phone, lot number."""
    carplate = models.CharField(max_length=20)
    name = models.CharField(max_length=255)
    time_parked = models.DateTimeField(help_text="When the car was parked")
    time_left = models.DateTimeField(null=True, blank=True, help_text="When the car left (null if still parked)")
    phone = models.CharField(max_length=20)
    lot_number = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "evicted_frontend_evlot"
        ordering = ["-created_at"]
        verbose_name = "EV Lot"
        verbose_name_plural = "EV Lots"

    def __str__(self):
        return f"{self.carplate} - Lot {self.lot_number}"


class Car(models.Model):
    """Cars: carplate, type (ICE or EV), time entered."""
    TYPE_CHOICES = [("ICE", "ICE"), ("EV", "EV")]

    carplate = models.CharField(max_length=20)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    time_entered = models.DateTimeField()
    time_left = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "evicted_frontend_car"
        ordering = ["-time_entered"]
        verbose_name = "Car"
        verbose_name_plural = "Cars"

    def __str__(self):
        return f"{self.carplate} ({self.type})"


class ParkingLot(models.Model):
    """Parking lots: lot_number and occupied status. Updated when QR form is submitted or car leaves."""
    lot_number = models.CharField(max_length=50, unique=True)
    occupied = models.BooleanField(default=False)

    class Meta:
        db_table = "evicted_frontend_parkinglot"
        ordering = ["lot_number"]
        verbose_name = "Parking lot"
        verbose_name_plural = "Parking lots"

    def __str__(self):
        return f"Lot {self.lot_number} ({'occupied' if self.occupied else 'free'})"



