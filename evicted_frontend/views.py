from django.conf import settings
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from .models import ParkingSubmission, WorkflowTrigger


def _get_database_name():
    """Return 'supabase' if using PostgreSQL, otherwise 'sqlite'."""
    engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
    return "supabase" if "postgresql" in engine else "sqlite"


def index(request):
    """Main page: trigger workflow button + QR code for form."""
    form_url = request.build_absolute_uri("/form/")
    submissions = ParkingSubmission.objects.all()[:50]
    return render(request, "evicted_frontend/index.html", {
        "form_url": form_url,
        "submissions": submissions,
    })


def form_page(request, lot_number=""):
    """Form page. Lot number can come from URL path or query ?lot=."""
    lot = request.GET.get("lot", lot_number) or ""
    return render(request, "evicted_frontend/form.html", {"lot_number": lot})


def success(request):
    """Success page after form submission."""
    database = request.GET.get("database", "unknown")
    return render(request, "evicted_frontend/success.html", {"database": database})


@require_POST
def trigger_workflow(request):
    """API: Record current time as TimeParked (for testing)."""
    lot = request.POST.get("lot_number", "") or request.GET.get("lot", "")
    WorkflowTrigger.objects.create(lot_number=lot)
    return JsonResponse({"ok": True, "triggered_at": timezone.now().isoformat()})


@require_GET
def last_trigger(request):
    """API: Get the most recent trigger time for pre-filling TimeParked."""
    trigger = WorkflowTrigger.objects.first()
    if not trigger:
        return JsonResponse({"triggered_at": None})
    return JsonResponse({"triggered_at": trigger.triggered_at.isoformat()})


@require_POST
def submit_form(request):
    """API: Submit the parking form."""
    try:
        carplate = request.POST.get("carplate", "").strip()
        name = request.POST.get("name", "").strip()
        time_parked_str = request.POST.get("time_parked", "").strip()
        time_car_left_str = request.POST.get("time_car_left", "").strip()
        phone = request.POST.get("phone", "").strip()
        lot_number = request.POST.get("lot_number", "").strip()

        if not all([carplate, name, phone, lot_number]):
            return JsonResponse(
                {"ok": False, "error": "Carplate, Name, Phone and Lot number are required."},
                status=400,
            )

        from django.utils.dateparse import parse_datetime, parse_date
        time_parked = None
        if time_parked_str:
            time_parked = parse_datetime(time_parked_str) or parse_date(time_parked_str)
        if not time_parked:
            trigger = WorkflowTrigger.objects.first()
            time_parked = trigger.triggered_at if trigger else timezone.now()
        else:
            if timezone.is_naive(time_parked):
                time_parked = timezone.make_aware(time_parked)

        time_car_left = None
        if time_car_left_str:
            time_car_left = parse_datetime(time_car_left_str) or parse_date(time_car_left_str)
            if time_car_left and timezone.is_naive(time_car_left):
                time_car_left = timezone.make_aware(time_car_left)

        ParkingSubmission.objects.create(
            carplate=carplate,
            name=name,
            time_parked=time_parked,
            time_car_left=time_car_left,
            phone=phone,
            lot_number=lot_number,
        )
        db = _get_database_name()
        return JsonResponse({
            "ok": True,
            "redirect": f"/success/?database={db}",
            "database": db,
            "message": f"Data saved to {db}."
        })
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=500)
