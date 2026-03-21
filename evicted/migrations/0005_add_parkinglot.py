# Migration: add ParkingLot model (lot_number, occupied)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("evicted", "0004_remove_old_tables"),
    ]

    operations = [
        migrations.CreateModel(
            name="ParkingLot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("lot_number", models.CharField(max_length=50, unique=True)),
                ("occupied", models.BooleanField(default=False)),
            ],
            options={
                "verbose_name": "Parking lot",
                "verbose_name_plural": "Parking lots",
                "ordering": ["lot_number"],
            },
        ),
    ]
