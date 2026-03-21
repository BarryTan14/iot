"""Seed the database with demo EV lots, cars, and parking lots."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from evicted.models import Car, EVLot, ParkingLot


class Command(BaseCommand):
    help = "Seed demo data for EVLot, Car, and ParkingLot tables"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing EVLot, Car, and ParkingLot records before seeding.",
        )

    def handle(self, *args, **options):
        if options.get("reset"):
            EVLot.objects.all().delete()
            Car.objects.all().delete()
            ParkingLot.objects.all().delete()
            self.stdout.write(self.style.WARNING("Cleared existing EVLot, Car, and ParkingLot data."))

        now = timezone.now()

        # Create three parking lots (1, 2, 3), default unoccupied
        lots = []
        for n in [1, 2, 3]:
            pl, _ = ParkingLot.objects.get_or_create(lot_number=str(n), defaults={"occupied": False})
            lots.append(pl)

        # Seed some cars (mix of ICE and EV)
        demo_cars = [
            ("SBA 1234A", "EV", now - timedelta(hours=1)),
            ("SKB 5678B", "ICE", now - timedelta(hours=2)),
            ("SGC 9012C", "ICE", now - timedelta(hours=3)),
        ]

        cars = []
        for plate, car_type, entered in demo_cars:
            car, _ = Car.objects.get_or_create(
                carplate=plate,
                defaults={"type": car_type, "time_entered": entered},
            )
            cars.append(car)

        # Seed EV lots: 3 occupied lots linked to above cars
        ev_lots = [
            dict(
                carplate="SBA 1234A",
                name="Alice EV",
                phone="+65 9000 0001",
                lot_number="1",
                time_parked=now - timedelta(minutes=50),
            ),
            dict(
                carplate="SKB 5678B",
                name="Bob ICE",
                phone="+65 9000 0002",
                lot_number="2",
                time_parked=now - timedelta(hours=1, minutes=30),
            ),
            dict(
                carplate="SGC 9012C",
                name="Charlie ICE",
                phone="+65 9000 0003",
                lot_number="3",
                time_parked=now - timedelta(hours=2, minutes=15),
            ),
        ]

        created_ev = 0
        for data in ev_lots:
            ev, created = EVLot.objects.get_or_create(
                carplate=data["carplate"],
                lot_number=data["lot_number"],
                time_parked=data["time_parked"],
                defaults={
                    "name": data["name"],
                    "phone": data["phone"],
                },
            )
            if created:
                created_ev += 1
            # Mark corresponding parking lot as occupied
            ParkingLot.objects.update_or_create(
                lot_number=data["lot_number"],
                defaults={"occupied": True},
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(lots)} ParkingLots, {len(cars)} Cars, and {created_ev} EVLots (demo data)."
            )
        )

