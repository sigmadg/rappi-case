from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("acciones/telegram-forzar/", views.telegram_force_alert, name="telegram_force_alert"),
    path("pipeline/", views.pipeline_view, name="pipeline"),
    path("datos/", views.datos_view, name="datos"),
    path("calibracion/", views.calibracion_view, name="calibracion"),
    path("figuras/", views.figuras_view, name="figuras"),
    path("m1-figure/<str:name>", views.figure_serve, name="m1_figure"),
    path("api/resumen.json", views.api_resumen_json, name="api_resumen"),
    path("monitor/", views.monitor_view, name="monitor"),
    path("api/monitor.json", views.api_monitor_json, name="api_monitor"),
]
