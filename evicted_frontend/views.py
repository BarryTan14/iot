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


LOT_NUMBERS = [1, 2, 3]


def _qr_display_payload(request):
    """Build form_url, qr_page_url, lot_urls, and lot-specific live URLs for QR display."""
    base = request.build_absolute_uri("/").rstrip("/")
    form_url = request.build_absolute_uri("/form/")
    qr_page_url = base + "/qr/"
    qr_live_url = base + "/qr/live/"
    lot_urls = {str(i): f"{form_url}?lot={i}" for i in LOT_NUMBERS}
    qr_live_url_by_lot = {str(i): f"{base}/qr/live/{i}/" for i in LOT_NUMBERS}
    return {
        "form_url": form_url,
        "qr_page_url": qr_page_url,
        "qr_live_url": qr_live_url,
        "lot_urls": lot_urls,
        "qr_live_url_by_lot": qr_live_url_by_lot,
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


def qr_live(request, lot_number=None):
    """
    Live display page: polls the API and shows QR code(s) when the workflow was recently triggered.
    - /qr/live/ : show all lots (1, 2, 3).
    - /qr/live/<lot_number>/ : show only that lot (e.g. for a kiosk dedicated to lot 2).
    Resets to "Waiting for trigger…" when a form is submitted (after someone scans and submits).
    Optional query: ?minutes=10 (how long to show QR after trigger before considering expired).
    """
    base = request.build_absolute_uri("/").rstrip("/")
    api_base = base + "/api"
    lot_number = int(lot_number) if lot_number is not None and str(lot_number).isdigit() else None
    if lot_number is not None and lot_number not in LOT_NUMBERS:
        lot_number = None
    lot_numbers = [lot_number] if lot_number else LOT_NUMBERS
    return render(request, "evicted_frontend/qr_live.html", {
        "api_qr_status": api_base + "/qr-status/",
        "poll_interval_ms": 3000,
        "recent_minutes": int(request.GET.get("minutes", "10")) or 10,
        "lot_number": lot_number,
        "lot_numbers": lot_numbers,
        "lot_numbers_json": json.dumps(lot_numbers),
        "page_lot_json": json.dumps(lot_number),
    })


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


def _triggered_lot_from_trigger(trigger):
    """Return the triggered lot as int (1–3) or None if not set/invalid."""
    if not trigger or not trigger.lot_number:
        return None
    raw = str(trigger.lot_number).strip()
    if raw and raw.isdigit():
        n = int(raw)
        if n in LOT_NUMBERS:
            return n
    return None


@require_GET
def qr_status(request):
    """
    API: Whether the live page should show QR codes. Used by /qr/live/ to poll.
    show_qr is True only if there was a recent trigger AND no form submission since that trigger.
    triggered_lot: when the trigger had ?lot=1 (or 2/3), only the matching /qr/live/<n>/ page may show QR.
    When someone submits the form (after scanning), show_qr becomes False so the live page resets.
    """
    recent_minutes = int(request.GET.get("minutes", "10")) or 10
    trigger = WorkflowTrigger.objects.first()
    submission = ParkingSubmission.objects.first()
    payload = _qr_display_payload(request)
    if not trigger:
        return JsonResponse({"show_qr": False, "triggered_at": None, "triggered_lot": None, **payload})
    triggered_at = trigger.triggered_at
    triggered_lot = _triggered_lot_from_trigger(trigger)
    submitted_after_trigger = (
        submission is not None and submission.created_at > triggered_at
    )
    cutoff = timezone.now() - timezone.timedelta(minutes=recent_minutes)
    trigger_recent = triggered_at >= cutoff
    show_qr = trigger_recent and not submitted_after_trigger
    response = {
        "show_qr": show_qr,
        "triggered_at": triggered_at.isoformat(),
        "triggered_lot": triggered_lot,
        "recent_minutes": recent_minutes,
        **payload,
    }
    return JsonResponse(response)


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
