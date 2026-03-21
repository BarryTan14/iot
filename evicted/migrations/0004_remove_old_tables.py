# Migration: delete ParkingSubmission and VehicleEntry (replaced by EVLot and Car)

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("evicted", "0003_add_evlot_and_car"),
    ]

    operations = [
        migrations.DeleteModel(name="ParkingSubmission"),
        migrations.DeleteModel(name="VehicleEntry"),
    ]
