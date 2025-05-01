# construction_api/urls.py
from django.urls import path
from . import views

app_name = "construction_api"

urlpatterns = [
    path(
        "profiles/<int:profile_id>/days/<int:day_number>/",
        views.DailyIceView.as_view(),
        name="daily_ice",
    ),
    path(
        "profiles/<int:profile_id>/overview/<int:day_number>/",
        views.CostOverviewView.as_view(),
        name="profile_cost_overview_day",
    ),
    path(
        "profiles/overview/<int:day_number>/",
        views.CostOverviewView.as_view(),
        name="overall_cost_overview_day",
    ),
    path(
        "profiles/overview/",
        views.CostOverviewView.as_view(),
        name="final_total_cost_overview",
    ),
]
