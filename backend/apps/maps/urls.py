from django.urls import path

from . import views

urlpatterns = [
    path("map/", views.MapView.as_view(), name="map"),
    path("map/config/", views.MapConfigView.as_view(), name="map-config"),
    path("map/search/", views.SearchView.as_view(), name="map-search"),
]
