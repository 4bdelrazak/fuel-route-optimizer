from django.urls import path

from routes.views import OptimizeRouteView

app_name = "routes"

urlpatterns = [
    path("optimize/", OptimizeRouteView.as_view(), name="optimize"),
]
