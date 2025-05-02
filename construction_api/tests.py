# construction_api/tests.py

import os
import tempfile
from io import StringIO

from django.core.management import call_command
from django.urls import reverse
from django.test import TestCase, TransactionTestCase
from rest_framework import status
from rest_framework.test import APITestCase

from .models import WallProfile, WallSection, DailyRecord, SimulationMetadata

# Constants
COST_PER_YARD = 1900
YARDS_PER_FOOT = 195
COST_PER_FOOT = YARDS_PER_FOOT * COST_PER_YARD
TARGET_HEIGHT = 30


# === Model Tests (Unchanged from previous version) ===
class ModelTests(TestCase):
    def test_create_wall_profile(self):
        profile = WallProfile.objects.create(original_index=1)
        self.assertEqual(WallProfile.objects.count(), 1)
        self.assertEqual(str(profile), "Profile 1")

    def test_create_wall_section(self):
        profile = WallProfile.objects.create(original_index=5)
        section = WallSection.objects.create(
            profile=profile, section_index=0, initial_height=20
        )
        section_complete = WallSection.objects.create(
            profile=profile,
            section_index=1,
            initial_height=30,
        )
        self.assertIn("Initial height 30", str(section_complete))

    def test_wall_section_unique_together(self):
        profile = WallProfile.objects.create(original_index=1)
        WallSection.objects.create(
            profile=profile, section_index=0, initial_height=10
        )
        with self.assertRaises(Exception):
            WallSection.objects.create(
                profile=profile, section_index=0, initial_height=15
            )

    def test_create_daily_record(self):
        profile = WallProfile.objects.create(original_index=1)
        record = DailyRecord.objects.create(
            profile=profile,
            day=1,
            is_overall=False,
            ice_yards_today=195,
            cost_today=COST_PER_FOOT,
            cumulative_cost=COST_PER_FOOT,
        )
        self.assertEqual(DailyRecord.objects.count(), 1)
        self.assertIn("Profile 1", str(record))
        overall_record = DailyRecord.objects.create(
            profile=None,
            day=1,
            is_overall=True,
            ice_yards_today=585,
            cost_today=COST_PER_FOOT * 3,
            cumulative_cost=COST_PER_FOOT * 3,
        )
        self.assertEqual(DailyRecord.objects.count(), 2)
        self.assertIn("Overall", str(overall_record))

    def test_create_simulation_metadata(self):
        # Note: teams_used removed from model
        meta = SimulationMetadata.objects.create(
            total_days=15, final_overall_cost=10000000
        )
        self.assertEqual(SimulationMetadata.objects.count(), 1)
        self.assertEqual(meta.total_days, 15)
        self.assertIn("15 days", str(meta))


# === Management Command Tests (Simplified) ===
class RunSimulationCommandTests(
    TransactionTestCase
):  # Use TransactionTestCase for command tests
    def setUp(self):
        self.temp_config_file = tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".txt"
        )

    def tearDown(self):
        os.unlink(self.temp_config_file.name)

    def call_simulation_command(self, *args, **options):
        """Helper method to call the command and capture output."""
        out = StringIO()
        err = StringIO()
        # Provide default path to temp file if not specified
        if not args:
            args = [self.temp_config_file.name]

        call_command("run_simulation", *args, stdout=out, stderr=err, **options)
        return out.getvalue(), err.getvalue()

    def test_command_clears_previous_data(self):
        p = WallProfile.objects.create(original_index=99)
        WallSection.objects.create(
            profile=p, section_index=0, initial_height=10
        )
        DailyRecord.objects.create(
            profile=p, day=1, cost_today=100, cumulative_cost=100
        )
        SimulationMetadata.objects.create(total_days=1, final_overall_cost=100)

        self.temp_config_file.write("\n")
        self.temp_config_file.flush()
        stdout, stderr = self.call_simulation_command()

        self.assertIn("Clearing previous simulation data...", stdout)
        self.assertFalse(WallProfile.objects.exists())
        self.assertFalse(WallSection.objects.exists())
        self.assertFalse(DailyRecord.objects.exists())
        # Metadata for the *new* (empty) run will be created
        self.assertEqual(SimulationMetadata.objects.count(), 1)
        meta = SimulationMetadata.objects.first()
        self.assertEqual(meta.total_days, 0)
        self.assertEqual(meta.final_overall_cost, 0)

    def test_command_loads_data_correctly(self):
        config_content = "10 20\n30\n"
        self.temp_config_file.write(config_content)
        self.temp_config_file.flush()
        stdout, stderr = self.call_simulation_command()

        self.assertEqual(WallProfile.objects.count(), 2)
        self.assertEqual(WallSection.objects.count(), 3)
        p1 = WallProfile.objects.get(original_index=1)
        p2 = WallProfile.objects.get(original_index=2)
        s1_1 = WallSection.objects.get(profile=p1, section_index=0)
        s2_1 = WallSection.objects.get(profile=p2, section_index=0)
        self.assertEqual(s1_1.initial_height, 10)
        self.assertEqual(s2_1.initial_height, 30)

    def test_command_simulation_produces_results(self):
        # Test that running the simulation creates DailyRecord and Metadata
        # Simple case: two sections needing 1 day each
        config_content = "29\n29\n"
        self.temp_config_file.write(config_content)
        self.temp_config_file.flush()
        stdout, stderr = self.call_simulation_command()

        self.assertTrue(DailyRecord.objects.exists())
        self.assertTrue(SimulationMetadata.objects.exists())
        meta = SimulationMetadata.objects.first()
        self.assertEqual(meta.total_days, 1)  # Should take exactly 1 day
        self.assertEqual(
            meta.final_overall_cost, 2 * COST_PER_FOOT
        )  # 2 sections * 1 foot * cost/foot

        # Verify specific daily records
        self.assertEqual(
            DailyRecord.objects.count(), 3
        )  # 2 profile records + 1 overall for Day 1
        dr_overall = DailyRecord.objects.get(day=1, is_overall=True)
        self.assertEqual(dr_overall.ice_yards_today, 2 * YARDS_PER_FOOT)
        self.assertEqual(dr_overall.cost_today, 2 * COST_PER_FOOT)
        self.assertEqual(dr_overall.cumulative_cost, 2 * COST_PER_FOOT)

    def test_command_invalid_config_file_path(self):
        stdout, stderr = self.call_simulation_command("non_existent_file.txt")
        self.assertIn("Configuration file not found", stderr)

    def test_command_invalid_config_file_content_height(self):
        self.temp_config_file.write("10 40\n")
        self.temp_config_file.flush()
        stdout, stderr = self.call_simulation_command()
        self.assertIn("Invalid height", stderr)


# === API View Tests (Mostly unchanged, just ensure setUpTestData matches expectations) ===
class APIViewTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        """Set up deterministic data based on single-threaded logic."""
        # Input:
        # P1: 28 29 -> Finishes Day 2 (needs 2, 1 days)
        # P2: 29    -> Finishes Day 1 (needs 1 day)
        cls.p1 = WallProfile.objects.create(original_index=1)
        cls.p2 = WallProfile.objects.create(original_index=2)
        cls.s1_1 = WallSection.objects.create(
            profile=cls.p1, section_index=0, initial_height=28
        )
        cls.s1_2 = WallSection.objects.create(
            profile=cls.p1, section_index=1, initial_height=29
        )
        cls.s2_1 = WallSection.objects.create(
            profile=cls.p2, section_index=0, initial_height=29
        )

        # Expected Daily Records (Simulated Manually)
        # Day 1: All 3 sections work
        cost_d1_p1 = 2 * COST_PER_FOOT
        cost_d1_p2 = 1 * COST_PER_FOOT
        cost_d1_ov = 3 * COST_PER_FOOT
        cls.dr_p1_d1 = DailyRecord.objects.create(
            profile=cls.p1,
            day=1,
            is_overall=False,
            ice_yards_today=2 * YARDS_PER_FOOT,
            cost_today=cost_d1_p1,
            cumulative_cost=cost_d1_p1,
        )
        cls.dr_p2_d1 = DailyRecord.objects.create(
            profile=cls.p2,
            day=1,
            is_overall=False,
            ice_yards_today=1 * YARDS_PER_FOOT,
            cost_today=cost_d1_p2,
            cumulative_cost=cost_d1_p2,
        )
        cls.dr_ov_d1 = DailyRecord.objects.create(
            profile=None,
            day=1,
            is_overall=True,
            ice_yards_today=3 * YARDS_PER_FOOT,
            cost_today=cost_d1_ov,
            cumulative_cost=cost_d1_ov,
        )

        # Day 2: Only section s1_1 works (s1_2 and s2_1 finished after day 1)
        cost_d2_p1 = 1 * COST_PER_FOOT
        cost_d2_ov = 1 * COST_PER_FOOT
        cls.dr_p1_d2 = DailyRecord.objects.create(
            profile=cls.p1,
            day=2,
            is_overall=False,
            ice_yards_today=1 * YARDS_PER_FOOT,
            cost_today=cost_d2_p1,
            cumulative_cost=cost_d1_p1 + cost_d2_p1,
        )
        # No record for P2 on Day 2
        cls.dr_ov_d2 = DailyRecord.objects.create(
            profile=None,
            day=2,
            is_overall=True,
            ice_yards_today=1 * YARDS_PER_FOOT,
            cost_today=cost_d2_ov,
            cumulative_cost=cost_d1_ov + cost_d2_ov,
        )

        # Metadata
        cls.final_cost = cost_d1_ov + cost_d2_ov
        cls.meta = SimulationMetadata.objects.create(
            total_days=2, final_overall_cost=cls.final_cost
        )

    def test_daily_ice_view_success(self):
        url = reverse(
            "construction_api:daily_ice", kwargs={"profile_id": 1, "day_number": 1}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data, {"day": 1, "ice_amount": 2 * YARDS_PER_FOOT}
        )  # P1 worked 2 sections

        url = reverse(
            "construction_api:daily_ice", kwargs={"profile_id": 1, "day_number": 2}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data, {"day": 2, "ice_amount": 1 * YARDS_PER_FOOT}
        )  # P1 worked 1 section

    def test_daily_ice_view_no_work_on_day(self):
        # Profile 2 did no work on Day 2
        url = reverse(
            "construction_api:daily_ice", kwargs={"profile_id": 2, "day_number": 2}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"day": 2, "ice_amount": 0})

    def test_daily_ice_view_profile_not_found(self):
        url = reverse(
            "construction_api:daily_ice", kwargs={"profile_id": 999, "day_number": 1}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_daily_ice_view_day_out_of_range(self):
        url = reverse(
            "construction_api:daily_ice", kwargs={"profile_id": 1, "day_number": 3}
        )  # Day 3 is beyond simulated days
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("must be between 1 and 2", response.data["error"])

    def test_cost_overview_profile_day_success(self):
        # Cumulative cost for Profile 1 up to Day 2
        url = reverse(
            "construction_api:profile_cost_overview_day",
            kwargs={"profile_id": 1, "day_number": 2},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data, {"day": 2, "cost": self.dr_p1_d2.cumulative_cost}
        )

    def test_cost_overview_profile_day_no_record_returns_latest(self):
        # Profile 2 had no record on Day 2, should return cost from Day 1
        url = reverse(
            "construction_api:profile_cost_overview_day",
            kwargs={"profile_id": 2, "day_number": 2},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Cost should be the cumulative cost from the latest record for P2 on or before Day 2 (which is Day 1)
        self.assertEqual(
            response.data, {"day": 2, "cost": self.dr_p2_d1.cumulative_cost}
        )

    def test_cost_overview_overall_day_success(self):
        url = reverse(
            "construction_api:overall_cost_overview_day", kwargs={"day_number": 2}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data, {"day": 2, "cost": self.dr_ov_d2.cumulative_cost}
        )

    def test_cost_overview_final_total_success(self):
        url = reverse("construction_api:final_total_cost_overview")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {"day": None, "cost": self.final_cost})

    def test_cost_overview_day_out_of_range(self):
        url = reverse(
            "construction_api:overall_cost_overview_day", kwargs={"day_number": 3}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("beyond the last simulated day (2)", response.data["error"])

    def test_views_simulation_not_run(self):
        # Temporarily clear data
        DailyRecord.objects.all().delete()
        SimulationMetadata.objects.all().delete()
        # Verify check_if_results_exist returns False
        self.assertFalse(DailyRecord.objects.exists())  # Direct check

        url = reverse("construction_api:final_total_cost_overview")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
