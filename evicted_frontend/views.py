import json
import re

from django.conf import settings
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.utils import timezone
from .models import ParkingSubmission, WorkflowTrigger
from .mqtt_client import publish_sms_event


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


def _qr_display_payload(request):
    """Build form_url, qr_page_url, and lot_urls for QR display (shared by API and page)."""
    base = request.build_absolute_uri("/").rstrip("/")
    form_url = request.build_absolute_uri("/form/")
    qr_page_url = base + "/qr/"
    lot_urls = {
        str(i): f"{form_url}?lot={i}" for i in range(1, 4)
    }
    return {
        "form_url": form_url,
        "qr_page_url": qr_page_url,
        "lot_urls": lot_urls,
    }


@require_GET
def qr_display_api(request):
    """
    API: Get URLs needed to display the parking form QR codes.
    Others can call this to get qr_page_url (open in browser/iframe) or form_url + lot_urls to render QR themselves.
    """
    payload = _qr_display_payload(request)
    return JsonResponse({"ok": True, **payload})


def qr_page(request):
    """Minimal page that only shows QR codes for the form (for kiosks/iframes)."""
    payload = _qr_display_payload(request)
    payload["lot_urls_json"] = json.dumps(payload["lot_urls"])
    return render(request, "evicted_frontend/qr_display.html", payload)


@require_http_methods(["GET", "POST"])
def trigger_workflow(request):
    """
    API: Trigger workflow (GET or POST) and return data to display the QR code.
    GET: Callable by anyone (e.g. links, other apps); no CSRF. Returns triggered_at + form_url, qr_page_url, lot_urls.
    POST: Same, for form submissions from the staff page.
    """
    if request.method == "GET":
        lot = request.GET.get("lot", "")
        WorkflowTrigger.objects.create(lot_number=lot)
        payload = _qr_display_payload(request)
        return JsonResponse({
            "ok": True,
            "triggered_at": timezone.now().isoformat(),
            **payload,
        })
    # POST
    return trigger_workflow_post(request)


@require_POST
def trigger_workflow_post(request):
    """API (POST): Record current time as TimeParked and return QR display data."""
    lot = request.POST.get("lot_number", "") or request.GET.get("lot", "")
    WorkflowTrigger.objects.create(lot_number=lot)
    payload = _qr_display_payload(request)
    return JsonResponse({
        "ok": True,
        "triggered_at": timezone.now().isoformat(),
        **payload,
    })


def trigger_workflow(request):
    """
    API: Trigger workflow (GET or POST) and return data to display the QR code.
    GET: Callable by anyone (e.g. links, other apps); no CSRF. Returns triggered_at + form_url, qr_page_url, lot_urls.
    POST: Same, for form submissions from the staff page.
    """
    if request.method == "GET":
        lot = request.GET.get("lot", "")
        WorkflowTrigger.objects.create(lot_number=lot)
        payload = _qr_display_payload(request)
        return JsonResponse({
            "ok": True,
            "triggered_at": timezone.now().isoformat(),
            **payload,
        })
    # POST
    return trigger_workflow_post(request)


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


def _parse_request_body(request):
    """Get JSON or form body. Returns (data dict, error str or None)."""
    content_type = (request.headers.get("Content-Type") or "").lower()
    if "application/json" in content_type:
        try:
            return json.loads(request.body or b"{}"), None
        except json.JSONDecodeError as e:
            return None, f"Invalid JSON: {e}"
    data = getattr(request, "POST", None) and request.POST.dict()
    if not data:
        data = getattr(request, "GET", None) and request.GET.dict()
    return data or {}, None


@require_POST
def queue_sms(request):
    """
    API: Queue an SMS by publishing an event to the MQTT broker.
    A subscriber consumes the message and calls an SMS API.

    Body (JSON or form): phone_number (required), message (optional), extra fields allowed.
    """
    data, err = _parse_request_body(request)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=400)
    if not data:
        data = {}

    phone_number = (data.get("phone_number") or "").strip()
    message = (data.get("message") or "You have a notification from Evicted service.").strip()

    if not phone_number:
        return JsonResponse(
            {"ok": False, "error": "phone_number is required."},
            status=400,
        )

    # Basic validation: digits, spaces, +, -
    if not re.match(r"^[\d\s+\-()]{10,20}$", phone_number):
        return JsonResponse(
            {"ok": False, "error": "phone_number must be 10–20 digits/symbols."},
            status=400,
        )

    extra = {k: v for k, v in data.items() if k not in ("phone_number", "message")}
    if publish_sms_event(phone_number, message, **extra):
        return JsonResponse({
            "ok": True,
            "queued": True,
            "phone_number": phone_number,
            "message": "SMS event published to broker.",
        })
    return JsonResponse(
        {"ok": False, "error": "Failed to publish to MQTT broker."},
        status=503,
    )
