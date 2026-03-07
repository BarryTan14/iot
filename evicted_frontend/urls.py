from django.urls import path
from . import views

app_name = 'evicted_frontend'

urlpatterns = [
    path("", views.index, name="index"),
    path("form/", views.form_page, name="form"),
    path("form/<str:lot_number>/", views.form_page, name="form_with_lot"),
    path("success/", views.success, name="success"),
    path("api/trigger-workflow/", views.trigger_workflow, name="trigger_workflow"),
    path("api/qr-display/", views.qr_display_api, name="qr_display_api"),
    path("qr/", views.qr_page, name="qr_page"),
    path("qr/live/", views.qr_live, name="qr_live"),
    path("api/last-trigger/", views.last_trigger, name="last_trigger"),
    path("api/submit-form/", views.submit_form, name="submit_form"),
    path("api/queue-sms/", views.queue_sms, name="queue_sms"),
]
