from django.urls import path
from . import views

app_name = 'evicted_frontend'

urlpatterns = [
    path("", views.index, name="index"),
    path("form/", views.form_page, name="form"),
    path("form/<str:lot_number>/", views.form_page, name="form_with_lot"),
    path("success/", views.success, name="success"),
    path("api/trigger-workflow/", views.trigger_workflow, name="trigger_workflow"),
    path("api/last-trigger/", views.last_trigger, name="last_trigger"),
    path("api/submit-form/", views.submit_form, name="submit_form"),
]
