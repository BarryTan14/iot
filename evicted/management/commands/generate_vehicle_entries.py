"""Generate random Car records for testing."""
import random
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from evicted.models import Car


class Command(BaseCommand):
    help = "Generate random Car records (Carplate, Type, Time entered)"

    def add_arguments(self, parser):
        parser.add_argument(
            "count",
            type=int,
            nargs="?",
            default=15,
            help="Number of records to create (default: 15)",
        )

    def handle(self, *args, **options):
        count = options["count"]
        plates = [
            "SBA 1234A", "SBB 5678B", "SBC 9012C", "SBD 3456D", "SBE 7890E",
            "SKB 1111F", "SKC 2222G", "SKD 3333H", "SKE 4444J", "SKF 5555K",
            "SGA 6666L", "SGB 7777M", "SGC 8888P", "SGD 9999R", "SGE 0000S",
        ]
        types = ["ICE", "EV"]

        base_time = timezone.now()
        letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
        created = 0
        for i in range(count):
            if i < len(plates):
                plate = plates[i]
            else:
                prefix = "".join(random.choices(letters, k=3))
                plate = f"{prefix} {random.randint(1000, 9999)}{random.choice(letters)}"
            vehicle_type = random.choice(types)
            hours_ago = random.randint(0, 72)
            time_entered = base_time - timedelta(hours=hours_ago, minutes=random.randint(0, 59))
            Car.objects.create(
                carplate=plate,
                type=vehicle_type,
                time_entered=time_entered,
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created} Car records."))
