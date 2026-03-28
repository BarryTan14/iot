import json
import logging
import re
from urllib.parse import quote

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from .models import EVLot, Car, ParkingLot
from .mqtt_client import publish_sms_event, publish_trigger_event
from .sms_client import send_sms
from .consumers import qr_lot_group_name

logger = logging.getLogger(__name__)


def _get_database_name():
    """Return 'supabase' if using PostgreSQL, otherwise 'sqlite'."""
    engine = settings.DATABASES.get("default", {}).get("ENGINE", "")
    return "supabase" if "postgresql" in engine else "sqlite"


def index(request):
    """Main page: trigger workflow button + QR code for form + EV Lots, Cars, and Parking lots tables."""
    form_url = request.build_absolute_uri("/form/")
    ev_lots = EVLot.objects.all()[:50]
    cars = Car.objects.all()[:50]
    # Ensure lots 1–3 exist for display; show all parking lots ordered by lot_number
    for n in LOT_NUMBERS:
        ParkingLot.objects.get_or_create(lot_number=str(n), defaults={"occupied": False})
    parking_lots = ParkingLot.objects.all().order_by("lot_number")
    return render(request, "evicted/index.html", {
        "form_url": form_url,
        "ev_lots": ev_lots,
        "cars": cars,
        "parking_lots": parking_lots,
    })


def dashboard(request):
    """Dashboard: carpark visual, gantry chart, and analytics."""
    from datetime import timezone as dt_timezone
    from django.db.models import ExpressionWrapper, F, DurationField, Q

    # ── Setup ────────────────────────────────────────────────────────────────
    for n in LOT_NUMBERS:
        ParkingLot.objects.get_or_create(lot_number=str(n), defaults={"occupied": False})
    parking_lots = ParkingLot.objects.all().order_by("lot_number")

    enriched_lots = []
    for lot in parking_lots:
        occupant = (
            EVLot.objects.filter(lot_number=lot.lot_number, time_left__isnull=True)
            .order_by("-created_at").first()
        )
        car_type = None
        if occupant:
            car = Car.objects.filter(carplate__iexact=occupant.carplate).order_by("-time_entered").first()
            car_type = car.type if car else "EV"
        enriched_lots.append({"lot": lot, "occupant": occupant, "car_type": car_type})

    gantry_entries = Car.objects.all().order_by("-time_entered")[:20]
    occupied_count = sum(1 for item in enriched_lots if item["lot"].occupied)
    ice_in_ev_count = sum(1 for item in enriched_lots if item["car_type"] == "ICE")

    local_tz = timezone.get_current_timezone()
    now_utc = timezone.now()
    now_local = now_utc.astimezone(local_tz)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start_local.astimezone(dt_timezone.utc)

    # ── Hourly gantry chart + EV/ICE split ───────────────────────────────────
    cars_today = list(Car.objects.filter(time_entered__gte=today_start_utc))
    hourly_counts = [0] * 24
    hourly_ev    = [0] * 24
    hourly_ice   = [0] * 24
    for c in cars_today:
        h = c.time_entered.astimezone(local_tz).hour
        hourly_counts[h] += 1
        if c.type == "EV":
            hourly_ev[h] += 1
        else:
            hourly_ice[h] += 1

    # ── 1. Dwell time distribution ───────────────────────────────────────────
    def _fmt_secs(s):
        h, r = divmod(int(s), 3600)
        m = r // 60
        return f"{h}h {m}m" if h else f"{m}m"

    completed = list(
        Car.objects.filter(time_left__isnull=False)
        .annotate(dur=ExpressionWrapper(F("time_left") - F("time_entered"), output_field=DurationField()))
    )
    dur_secs = sorted(c.dur.total_seconds() for c in completed if c.dur.total_seconds() >= 0)
    if dur_secs:
        n = len(dur_secs)
        dwell_avg    = _fmt_secs(sum(dur_secs) / n)
        dwell_median = _fmt_secs(dur_secs[n // 2] if n % 2 else (dur_secs[n//2 - 1] + dur_secs[n//2]) / 2)
        overstay_count = sum(1 for s in dur_secs if s > 4 * 3600)
    else:
        dwell_avg = dwell_median = "N/A"
        overstay_count = 0

    # ── 3. Per-lot utilisation ────────────────────────────────────────────────
    elapsed_today_secs = (now_utc - today_start_utc).total_seconds()
    lot_utilisation = {}
    for lot_num in LOT_NUMBERS:
        records = EVLot.objects.filter(
            lot_number=str(lot_num),
            time_parked__lt=now_utc,
        ).filter(Q(time_left__isnull=True) | Q(time_left__gt=today_start_utc))
        occ_secs = 0.0
        for r in records:
            start = max(r.time_parked, today_start_utc)
            end   = min(r.time_left if r.time_left else now_utc, now_utc)
            if end > start:
                occ_secs += (end - start).total_seconds()
        lot_utilisation[str(lot_num)] = min(
            round(occ_secs / elapsed_today_secs * 100, 1) if elapsed_today_secs > 0 else 0.0,
            100.0,
        )

    # ── 5. ICE pressure — minutes today all lots were simultaneously full ─────
    evlots_today = list(EVLot.objects.filter(
        time_parked__lt=now_utc,
    ).filter(Q(time_left__isnull=True) | Q(time_left__gt=today_start_utc)))

    boundary_times = sorted({today_start_utc, now_utc} | {
        t
        for ev in evlots_today
        for t in (
            max(ev.time_parked, today_start_utc),
            min(ev.time_left if ev.time_left else now_utc, now_utc),
        )
    })
    full_capacity_secs = 0.0
    for i in range(len(boundary_times) - 1):
        mid = boundary_times[i] + (boundary_times[i + 1] - boundary_times[i]) / 2
        occupied_lots = {
            str(ev.lot_number)
            for ev in evlots_today
            if max(ev.time_parked, today_start_utc) <= mid < (ev.time_left if ev.time_left else now_utc)
        }
        if len(occupied_lots) >= len(LOT_NUMBERS):
            full_capacity_secs += (boundary_times[i + 1] - boundary_times[i]).total_seconds()
    ice_pressure_mins = round(full_capacity_secs / 60)

    return render(request, "evicted/dashboard.html", {
        # existing
        "enriched_lots": enriched_lots,
        "gantry_entries": gantry_entries,
        "occupied_count": occupied_count,
        "free_count": len(enriched_lots) - occupied_count,
        "ice_in_ev_count": ice_in_ev_count,
        "total_lots": len(enriched_lots),
        "hourly_counts_json": json.dumps(hourly_counts),
        "chart_date": now_local.strftime("%B %d, %Y"),
        "total_today": sum(hourly_counts),
        # new
        "hourly_ev_json":  json.dumps(hourly_ev),
        "hourly_ice_json": json.dumps(hourly_ice),
        "dwell_avg": dwell_avg,
        "dwell_median": dwell_median,
        "overstay_count": overstay_count,
        "lot_utilisation": lot_utilisation,
        "ice_pressure_mins": ice_pressure_mins,
    })


def form_page(request, lot_number=""):
    """Form page. Lot number can come from URL path or query ?lot=."""
    lot = request.GET.get("lot", lot_number) or ""
    return render(request, "evicted/form.html", {"lot_number": lot})


def success(request):
    """Success page after form submission."""
    database = request.GET.get("database", "unknown")
    return render(request, "evicted/success.html", {"database": database})


LOT_NUMBERS = [1, 2, 3]


def _qr_display_payload(request):
    """Build form_url, qr_page_url, lot_urls, and lot-specific live URLs for QR display."""
    base = request.build_absolute_uri("/").rstrip("/")
    form_url = request.build_absolute_uri("/form/")
    qr_page_url = base + "/qr/"
    qr_live_url = base + "/qr/live/"
    # Use path-based URLs so form opens with lot in URL and lot number is non-editable
    lot_urls = {str(i): f"{base}/form/{i}/" for i in LOT_NUMBERS}
    qr_live_url_by_lot = {str(i): f"{base}/qr/live/{i}/" for i in LOT_NUMBERS}
    return {
        "form_url": form_url,
        "qr_page_url": qr_page_url,
        "qr_live_url": qr_live_url,
        "lot_urls": lot_urls,
        "qr_live_url_by_lot": qr_live_url_by_lot,
    }


def _lot_urls_with_triggered_at(lot_urls, triggered_at_iso):
    """Return a copy of lot_urls with triggered_at query param appended to each URL (for QR code when car entered)."""
    if not triggered_at_iso:
        return lot_urls
    encoded = quote(triggered_at_iso, safe="")
    return {
        k: v + ("&" if "?" in v else "?") + f"triggered_at={encoded}"
        for k, v in lot_urls.items()
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
    return render(request, "evicted/qr_display.html", payload)


def qr_live(request, lot_number=None):
    """
    Live display page: polls the API and shows QR code(s) when the workflow was recently triggered.
    - /qr/live/ : show all lots (1, 2, 3).
    - /qr/live/<lot_number>/ : show only that lot (e.g. for a kiosk dedicated to lot 2).
    Resets to "Waiting for trigger…" when a form is submitted (after someone scans and submits).
    Timer duration comes from settings.QR_LIVE_WARNING_SECONDS (env QR_LIVE_WARNING_SECONDS). Optional override: ?warning_seconds=N.
    """
    base = request.build_absolute_uri("/").rstrip("/")
    api_base = base + "/api"
    lot_number = int(lot_number) if lot_number is not None and str(lot_number).isdigit() else None
    if lot_number is not None and lot_number not in LOT_NUMBERS:
        lot_number = None
    lot_numbers = [lot_number] if lot_number else LOT_NUMBERS
    warning_seconds = int(
        request.GET.get("warning_seconds") or settings.QR_LIVE_WARNING_SECONDS
    ) or settings.QR_LIVE_WARNING_SECONDS
    timer_initial = f"{warning_seconds // 60}:{warning_seconds % 60:02d}"
    scheme = "wss" if request.is_secure() else "ws"
    host = request.get_host()
    if lot_number:
        ws_path = f"/ws/qr-live/{lot_number}/"
    else:
        ws_path = "/ws/qr-live/"
    ws_url = f"{scheme}://{host}{ws_path}"
    carpark = _carpark_status()
    lot_occupied = carpark["lots_occupied"].get(str(lot_number), False) if lot_number else False
    qr_live_config = {
        "api_alert_no_submission": api_base + "/alert-no-submission/",
        "api_carpark_status": api_base + "/carpark-status/",
        "warning_seconds": warning_seconds,
        "timer_initial": timer_initial,
        "lot_numbers": lot_numbers,
        "page_lot": lot_number,
        "ws_url": ws_url,
    }
    return render(request, "evicted/qr_live.html", {
        "qr_live_config": qr_live_config,
        "timer_initial": timer_initial,
        "lot_number": lot_number,
        "lot_numbers": lot_numbers,
        "carpark": carpark,
        "lot_occupied": lot_occupied,
    })


def _parse_trigger_body(request):
    """Parse trigger-workflow body. Returns (data dict, error str or None)."""
    data, err = _parse_request_body(request)
    if err:
        return None, err
    if not data:
        data = {}
    params = {**request.GET.dict(), **data}
    if request.POST:
        params.update(request.POST.dict())
    return params, None


@require_http_methods(["GET", "POST"])
@csrf_exempt
def trigger_workflow(request):
    """
    API: Single endpoint for car entered/left. Use POST with body for external callers.

    POST body (JSON or form):
      - parking_lot (required): lot number, e.g. 1, 2, 3 (or use lot_number / lot)
      - action (required): "entered" | "left" — show or hide QR
      - timestamp (optional): ISO datetime; default now

    Response: ok, and for "entered": triggered_at, form_url, lot_urls; for "left": time_car_left, etc.
    WebSocket: show_qr true on entered, show_qr false on left (and hide on all lots live page too).
    """
    if request.method == "GET":
        # Backward compat: ?lot=1 = entered, ?lot=1&car_left=true = left
        lot = request.GET.get("lot") or request.GET.get("lot_number") or ""
        show_qr = (request.GET.get("show_qr") or "").strip().lower()
        car_left = (request.GET.get("car_left") or "").strip().lower()
        is_left = show_qr == "false" or car_left in ("1", "true")
        if is_left:
            lot = (lot or "").strip()
            if not lot or lot not in (str(n) for n in LOT_NUMBERS):
                return JsonResponse({"ok": False, "error": "Valid lot number is required for action 'left'."}, status=400)
            if _is_lot_occupied(lot):
                ok, data, status = _handle_car_left(lot, request.GET.get("time_car_left"))
                if not ok:
                    return JsonResponse({**data, "ok": False}, status=status)
                return JsonResponse(data)
            _send_qr_trigger_websocket(lot, {"show_qr": False})
            return JsonResponse({"ok": True, "message": "QR hidden.", "lot_number": lot})
        payload = _qr_display_payload(request)
        triggered_at = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        payload["lot_urls"] = _lot_urls_with_triggered_at(payload["lot_urls"], triggered_at)
        triggered_lot = int(lot) if lot and str(lot).strip().isdigit() and int(lot) in LOT_NUMBERS else None
        ws_payload = {"show_qr": True, "triggered_at": triggered_at, "triggered_lot": triggered_lot, **payload}
        _send_qr_trigger_websocket(lot, ws_payload)
        return JsonResponse({"ok": True, "triggered_at": triggered_at, **payload})

    # POST: body with parking_lot + action (action optional for backward compat: default "entered")
    params, err = _parse_trigger_body(request)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=400)
    lot = (params.get("parking_lot") or params.get("lot_number") or params.get("lot"))
    if lot is not None: 
        lot = str(lot).strip()
    else:
        lot = ""
    action = (params.get("action") or "").strip().lower() or "entered"
    timestamp_raw = (params.get("timestamp") or "").strip() or None

    if action not in ("entered", "left"):
        return JsonResponse({"ok": False, "error": "action must be 'entered' or 'left'."}, status=400)
    if not lot and action == "left":
        return JsonResponse({"ok": False, "error": "parking_lot (or lot_number / lot) is required when action is 'left'."}, status=400)

    if action == "left":
        if not lot or lot not in (str(n) for n in LOT_NUMBERS):
            return JsonResponse({"ok": False, "error": "Valid parking_lot (1, 2, or 3) is required for action 'left'."}, status=400)
        if _is_lot_occupied(lot):
            ok, data, status = _handle_car_left(lot, timestamp_raw)
            if not ok:
                return JsonResponse({**data, "ok": False}, status=status)
            return JsonResponse(data)
        _send_qr_trigger_websocket(lot, {"show_qr": False})
        return JsonResponse({"ok": True, "message": "QR hidden.", "lot_number": lot})

    # action == "entered" — only send WebSocket to frontend; no WorkflowTrigger DB write
    payload = _qr_display_payload(request)
    if timestamp_raw:
        from django.utils.dateparse import parse_datetime
        triggered_dt = parse_datetime(timestamp_raw)
        if triggered_dt:
            if timezone.is_naive(triggered_dt):
                triggered_dt = timezone.make_aware(triggered_dt)
            from datetime import timezone as dt_timezone
            triggered_at = triggered_dt.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            triggered_at = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        triggered_at = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    payload["lot_urls"] = _lot_urls_with_triggered_at(payload["lot_urls"], triggered_at)
    triggered_lot = int(lot) if lot.strip().isdigit() and int(lot) in LOT_NUMBERS else None
    ws_payload = {"show_qr": True, "triggered_at": triggered_at, "triggered_lot": triggered_lot, **payload}
    _send_qr_trigger_websocket(lot, ws_payload)
    return JsonResponse({"ok": True, "triggered_at": triggered_at, **payload})


def _check_on_trigger_lot(lot_number):
    """
    Called when trigger_lot (trigger_workflow) is invoked. Ensures ParkingLot exists
    for the given lot and returns current occupied status (for logging or downstream use).
    """
    if not lot_number or not str(lot_number).strip():
        return None
    lot_str = str(lot_number).strip()
    if lot_str not in (str(n) for n in LOT_NUMBERS):
        return None
    parking_lot, _ = ParkingLot.objects.get_or_create(
        lot_number=lot_str,
        defaults={"occupied": False},
    )
    return {"lot_number": lot_str, "occupied": parking_lot.occupied}


def _send_sms_to_phone(phone_number: str, message: str) -> bool:
    """
    Send an SMS to the given phone number.
    First try direct send via Twilio (sms_client). If that is not configured,
    fall back to publishing an event to the MQTT broker.
    """
    # Try direct SMS (Twilio)
    ok = send_sms(phone_number, message)
    if ok:
        return True
    # Fallback: publish to MQTT so an external subscriber can send the SMS
    return publish_sms_event(phone_number, message)


def _check_full_lots_and_notify_longest_ice():
    """
    After trigger_lot: if all lots are filled, check for ICE cars. If any ICE car is parked,
    find the one parked the longest, get their phone from EV Lots, and send an SMS to that number.
    """
    # 1. Check if all lots (1, 2, 3) are occupied
    for n in LOT_NUMBERS:
        pl = ParkingLot.objects.filter(lot_number=str(n)).first()
        if not pl or not pl.occupied:
            return
    # 2. Get current occupant per lot (most recent EVLot for that lot with time_left null)
    current_occupants = []
    for n in LOT_NUMBERS:
        ev_lot = (
            EVLot.objects.filter(lot_number=str(n), time_left__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if ev_lot:
            current_occupants.append(ev_lot)
    # 3. Filter to those whose carplate is ICE in Car table
    ice_occupants = []
    for ev_lot in current_occupants:
        if Car.objects.filter(carplate__iexact=ev_lot.carplate, type="ICE").exists():
            ice_occupants.append(ev_lot)
    if not ice_occupants:
        return
    # 4. Among ICE cars, the one parked longest has the earliest time_parked
    longest_parked = min(ice_occupants, key=lambda o: o.time_parked)
    phone = (longest_parked.phone or "").strip()
    if not phone:
        return
    # 5. Send SMS to that phone number
    message = (
        "Your vehicle has been parked in an EV lot for the longest time among ICE vehicles. "
        "Please move your car to allow EV charging. Thank you."
    )
    _send_sms_to_phone(phone, message)


def _notify_longest_parked_ice_to_move_for_ev():
    """
    Find ICE cars currently parked in the lots (EVLot with time_left null).
    If any exist, get the one parked the longest, retrieve their phone from EV Lots, and send an SMS
    asking them to move for the incoming EV.
    Returns True if an SMS was sent, False otherwise.
    """
    current_occupants = []
    for n in LOT_NUMBERS:
        ev_lot = (
            EVLot.objects.filter(lot_number=str(n), time_left__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if ev_lot:
            current_occupants.append(ev_lot)
    ice_occupants = [
        ev_lot for ev_lot in current_occupants
        if Car.objects.filter(carplate__iexact=ev_lot.carplate, type="ICE").exists()
    ]
    if not ice_occupants:
        return False
    longest_parked = min(ice_occupants, key=lambda o: o.time_parked)
    phone = (longest_parked.phone or "").strip()
    if not phone:
        return False
    message = (
        "An EV car has arrived and needs to park. Please move your vehicle so the EV can use the charging lot. Thank you."
    )
    _send_sms_to_phone(phone, message)
    return True


def _send_qr_trigger_websocket(lot_str, payload):
    """Send payload to WebSocket group for this lot so the live page shows/hides the QR.
    When payload has show_qr=False, also sends to the 'all' group so /qr/live/ (all lots) hides the QR."""
    try:
        triggered_lot = None
        if lot_str and str(lot_str).strip().isdigit():
            n = int(str(lot_str).strip())
            if n in LOT_NUMBERS:
                triggered_lot = n
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        message = {"type": "qr_trigger", "payload": payload}
        # Always send to the lot-specific group
        group = qr_lot_group_name(triggered_lot)
        async_to_sync(channel_layer.group_send)(group, message)
        # When hiding QR, also notify the "all lots" live page so it hides too
        if payload.get("show_qr") is False:
            all_group = qr_lot_group_name(None)
            if all_group != group:
                async_to_sync(channel_layer.group_send)(all_group, message)
    except Exception:
        pass


def _is_lot_occupied(lot_number):
    """True if the lot has a current occupant (EVLot with time_left null)."""
    if not lot_number or str(lot_number).strip() not in (str(n) for n in LOT_NUMBERS):
        return False
    return EVLot.objects.filter(lot_number=str(lot_number).strip(), time_left__isnull=True).exists()


def _handle_car_left(lot_number, time_car_left_str=None):
    """
    Record that the car left the lot: set EVLot.time_left, set ParkingLot.occupied=False,
    and send WebSocket show_qr=False so the live QR display hides.
    Returns (ok: bool, data: dict, status: int). On failure data has "error" key.
    Call only when the lot is occupied; otherwise use _send_qr_trigger_websocket alone.
    """
    lot_number = (lot_number or "").strip()
    if not lot_number:
        return False, {"error": "lot_number is required."}, 400
    if lot_number not in (str(n) for n in LOT_NUMBERS):
        return False, {"error": "Invalid lot_number."}, 400
    ev_lot = EVLot.objects.filter(lot_number=lot_number).order_by("-created_at").first()
    if not ev_lot:
        return False, {"error": "No EV lot record found for that lot_number."}, 404
    if time_car_left_str:
        from django.utils.dateparse import parse_datetime, parse_date
        time_left = parse_datetime(time_car_left_str) or parse_date(time_car_left_str)
        if not time_left:
            return False, {"error": "Invalid time_car_left."}, 400
        if timezone.is_naive(time_left):
            time_left = timezone.make_aware(time_left)
    else:
        time_left = timezone.now()
    ev_lot.time_left = time_left
    ev_lot.save(update_fields=["time_left"])
    ParkingLot.objects.filter(lot_number=lot_number).update(occupied=False)
    _send_qr_trigger_websocket(lot_number, {"show_qr": False})
    _send_capacity_update_websocket()
    return True, {
        "ok": True,
        "id": ev_lot.pk,
        "lot_number": ev_lot.lot_number,
        "time_car_left": ev_lot.time_left.isoformat(),
    }, 200





def _carpark_status():
    """Return current lot occupancy, per-lot status, and whether ICE cars are allowed.
    ICE is allowed when there is at least one free lot."""
    lots = ParkingLot.objects.all()
    total_lots = len(lots)
    occupied_lots = sum(1 for l in lots if l.occupied)
    free_lots = total_lots - occupied_lots
    ice_allowed = free_lots > 0
    lots_occupied = {str(l.lot_number): l.occupied for l in lots}
    return {
        "occupied_lots": occupied_lots,
        "total_lots": total_lots,
        "free_lots": free_lots,
        "ice_allowed": ice_allowed,
        "lots_occupied": lots_occupied,
    }


def _send_capacity_update_websocket():
    """Broadcast current carpark capacity status to all lot WebSocket groups."""
    try:
        status = _carpark_status()
        channel_layer = get_channel_layer()
        if not channel_layer:
            return
        message = {"type": "capacity_update", "payload": {"type": "capacity_update", **status}}
        for lot in LOT_NUMBERS:
            async_to_sync(channel_layer.group_send)(qr_lot_group_name(lot), message)
    except Exception:
        pass


@require_GET
def carpark_status_api(request):
    """API: Current carpark occupancy and whether ICE cars are allowed in EV lots."""
    return JsonResponse({"ok": True, **_carpark_status()})




@csrf_exempt
@require_POST
def alert_no_submission(request):
    """
    API: Called by the live page when the timer expires without a form submission (default 10 seconds).
    Publishes a no_submission event to the MQTT queue (e.g. to send staff an SMS).
    Body (JSON): triggered_at (ISO string), lot_number (int or string).
    """
    data, err = _parse_request_body(request)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=400)
    triggered_at_str = (data.get("triggered_at") or "").strip()
    lot_number = data.get("lot_number")
    if not triggered_at_str or lot_number is None:
        return JsonResponse(
            {"ok": False, "error": "triggered_at and lot_number are required."},
            status=400,
        )
    lot_number = str(lot_number).strip()
    if lot_number not in (str(n) for n in LOT_NUMBERS):
        return JsonResponse({"ok": False, "error": "Invalid lot_number."}, status=400)
    from django.utils.dateparse import parse_datetime
    triggered_at = parse_datetime(triggered_at_str)
    if not triggered_at:
        return JsonResponse({"ok": False, "error": "Invalid triggered_at."}, status=400)
    if timezone.is_naive(triggered_at):
        triggered_at = timezone.make_aware(triggered_at)
    # If a form was submitted for this lot after triggered_at, don't send alert
    ev_lot = EVLot.objects.filter(
        lot_number=lot_number,
        created_at__gt=triggered_at,
    ).first()
    if ev_lot:
        return JsonResponse({"ok": True, "already_submitted": True})
    msg = f"Lot {lot_number}: Form not submitted within the time limit."
    if publish_trigger_event("no_submission", lot_number, triggered_at.isoformat(), msg):
        return JsonResponse({"ok": True, "published": True})
    return JsonResponse({"ok": False, "error": "Failed to publish to MQTT."}, status=503)


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

        # Validate carplate exists in Cars (case-insensitive) on submit
        if not Car.objects.filter(carplate__iexact=carplate).exists():
            return JsonResponse(
                {"ok": False, "error": "Car plate not found. Please check and try again."},
                status=400,
            )

        from django.utils.dateparse import parse_datetime, parse_date
        time_parked = None
        if time_parked_str:
            time_parked = parse_datetime(time_parked_str) or parse_date(time_parked_str)
        if not time_parked:
            time_parked = timezone.now()
        else:
            if timezone.is_naive(time_parked):
                time_parked = timezone.make_aware(time_parked)

        time_left = None
        if time_car_left_str:
            time_left = parse_datetime(time_car_left_str) or parse_date(time_car_left_str)
            if time_left and timezone.is_naive(time_left):
                time_left = timezone.make_aware(time_left)

        ev_lot = EVLot.objects.create(
            carplate=carplate,
            name=name,
            time_parked=time_parked,
            time_left=time_left,
            phone=phone,
            lot_number=lot_number,
        )
        msg = f"Form submitted for lot {lot_number}."
        publish_trigger_event(
            "form_submitted",
            lot_number,
            ev_lot.created_at.isoformat(),
            msg,
        )
        _send_qr_trigger_websocket(lot_number, {"show_qr": False})
        # Update Parking lot: set occupied=True for this lot
        ParkingLot.objects.update_or_create(
            lot_number=lot_number,
            defaults={"occupied": True},
        )
        _send_capacity_update_websocket()
        db = _get_database_name()
        return JsonResponse({
            "ok": True,
            "redirect": f"/success/?database={db}",
            "database": db,
            "message": f"Data saved to {db}."
        })
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=500)


@csrf_exempt
@require_POST
def create_car(request):
    """
    API: Create or update a record in the Cars table.
    Body (JSON or form):
      - carplate (required)
      - type (required for action "entered", "ICE" or "EV")
      - action (optional): "entered" (default) | "left"
      - time_entered (ISO datetime, optional; default now) — used when action is "entered"
      - time_left (ISO datetime, optional; default now) — used when action is "left"

    action "entered": creates a new Car record.
    action "left": sets time_left on the most recent Car record for that carplate where time_left is null.
    """
    from django.utils.dateparse import parse_datetime, parse_date

    data, err = _parse_request_body(request)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=400)
    if not data:
        data = {}

    carplate = (data.get("carplate") or "").strip()
    if not carplate:
        return JsonResponse({"ok": False, "error": "carplate is required."}, status=400)

    action = (data.get("action") or "entered").strip().lower()
    if action not in ("entered", "left"):
        return JsonResponse({"ok": False, "error": "action must be 'entered' or 'left'."}, status=400)

    if action == "left":
        time_left_str = (data.get("time_left") or "").strip()
        if time_left_str:
            time_left = parse_datetime(time_left_str) or parse_date(time_left_str)
            if not time_left:
                return JsonResponse({"ok": False, "error": "Invalid time_left."}, status=400)
            if timezone.is_naive(time_left):
                time_left = timezone.make_aware(time_left)
        else:
            time_left = timezone.now()
        car = Car.objects.filter(carplate__iexact=carplate, time_left__isnull=True).order_by("-time_entered").first()
        if not car:
            return JsonResponse({"ok": False, "error": "No active Car record found for that carplate."}, status=404)
        car.time_left = time_left
        car.save(update_fields=["time_left"])
        return JsonResponse({
            "ok": True,
            "id": car.pk,
            "carplate": car.carplate,
            "type": car.type,
            "time_entered": car.time_entered.isoformat(),
            "time_left": car.time_left.isoformat(),
        })

    # action == "entered"
    car_type = (data.get("type") or "").strip().upper()
    if car_type not in ("ICE", "EV"):
        return JsonResponse({"ok": False, "error": "type must be ICE or EV."}, status=400)
    time_entered_str = (data.get("time_entered") or "").strip()
    if time_entered_str:
        time_entered = parse_datetime(time_entered_str) or parse_date(time_entered_str)
        if not time_entered:
            return JsonResponse({"ok": False, "error": "Invalid time_entered."}, status=400)
        if timezone.is_naive(time_entered):
            time_entered = timezone.make_aware(time_entered)
    else:
        time_entered = timezone.now()
    car = Car.objects.create(carplate=carplate, type=car_type, time_entered=time_entered)

    # When an EV car enters the gantry: if any ICE cars are currently parked in the lots,
    # find the one parked longest and send them an SMS to move for the EV.
    sms_queued = False
    if car_type == "EV":
        try:
            sms_queued = _notify_longest_parked_ice_to_move_for_ev()
            if sms_queued:
                logger.info("EV entered gantry: queued SMS to longest-parked ICE driver (carplate %s)", car.carplate)
            else:
                logger.info("EV entered gantry: no ICE cars currently parked, no SMS sent")
        except Exception as e:
            logger.exception("EV entered gantry: failed to notify ICE driver: %s", e)

    return JsonResponse({
        "ok": True,
        "id": car.pk,
        "carplate": car.carplate,
        "type": car.type,
        "time_entered": car.time_entered.isoformat(),
        "sms_queued": sms_queued,
    }, status=201)


@require_GET
def check_carplate(request):
    """API: Check if a carplate exists in Cars (case-insensitive)."""
    carplate = (request.GET.get("carplate") or "").strip()
    if not carplate:
        return JsonResponse({"ok": False, "exists": False, "error": "carplate is required."}, status=400)
    exists = Car.objects.filter(carplate__iexact=carplate).exists()
    return JsonResponse({"ok": True, "exists": exists})


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


@csrf_exempt
@require_POST
def update_time_car_left(request):
    """
    API: Update time_car_left for a parking submission by lot number.
    Body (JSON or form): lot_number (required), time_car_left (ISO datetime, optional; default now).
    Updates the most recent submission for that lot and sends WebSocket to hide the QR (same as trigger_workflow with car_left=true).
    """
    data, err = _parse_request_body(request)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=400)
    if not data:
        data = {}
    lot_number = data.get("lot_number") or data.get("lot") or ""
    time_car_left_str = (data.get("time_car_left") or "").strip() or None
    ok, result, status = _handle_car_left(lot_number, time_car_left_str)
    if not ok:
        return JsonResponse({**result, "ok": False}, status=status)
    return JsonResponse(result)
