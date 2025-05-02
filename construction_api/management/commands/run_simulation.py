import logging
import os
import time
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction, models
from django.db.models import F  # For atomic updates
from django.utils import timezone

from construction_api.models import (
    WallProfile,
    WallSection,
    DailyRecord,
    SimulationMetadata,
)

# Constants
COST_PER_YARD = 1900
YARDS_PER_FOOT = 195
COST_PER_FOOT = YARDS_PER_FOOT * COST_PER_YARD
TARGET_HEIGHT = 30
# LOG_FILE_NAME = "construction_log.txt" # Logging to console primarily now

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Clears previous data, runs the single-threaded wall construction simulation, "
        "and stores results in the database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "config_file", type=str,
            help="Path to the input config file."
        )

    @transaction.atomic
    def clear_and_load_data(self, config_file):
        self.stdout.write("Clearing previous simulation data...")
        DailyRecord.objects.all().delete()
        SimulationMetadata.objects.all().delete()
        WallSection.objects.all().delete()
        WallProfile.objects.all().delete()
        self.stdout.write("Previous data cleared.")

        self.stdout.write(f"Loading data from {config_file}...")
        profiles_to_create = []
        sections_to_create = []
        profile_index_counter = 0

        try:
            with open(config_file, "r") as f:
                for line in f:
                    profile_index_counter += 1
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        heights = [int(h) for h in line.split()]
                    except ValueError:
                        raise ValueError(
                            f"Non-integer height found in profile line {profile_index_counter}"
                        )

                    if not all(0 <= h <= TARGET_HEIGHT for h in heights):
                        raise ValueError(
                            f"Invalid height (0-{TARGET_HEIGHT}) in profile {profile_index_counter}"
                        )
                    if len(heights) > 2000:
                        raise ValueError(
                            f"Profile {profile_index_counter} exceeds 2000 sections"
                        )

                    profile_instance = WallProfile(original_index=profile_index_counter)
                    profiles_to_create.append(profile_instance)

                    for section_idx, height in enumerate(heights):
                        sections_to_create.append(
                            WallSection(
                                profile=profile_instance,
                                section_index=section_idx,
                                initial_height=height,
                                current_height=height,
                                is_complete=(height >= TARGET_HEIGHT),
                            )
                        )

            if not profiles_to_create:
                self.stdout.write("Config file is empty or contains no valid profiles.")

            created_profiles = WallProfile.objects.bulk_create(profiles_to_create)
            self.stdout.write(f"Created {len(created_profiles)} WallProfile records.")

            profile_map = {p.original_index: p.pk for p in created_profiles}

            for section in sections_to_create:
                profile_pk = profile_map.get(section.profile.original_index)
                if profile_pk:
                    section.profile_id = profile_pk
                    del section.profile.original_index
                else:
                    raise RuntimeError(
                        f"Could not map profile PK for profile index {section.profile.original_index}"
                    )

            WallSection.objects.bulk_create(sections_to_create)
            self.stdout.write(f"Created {len(sections_to_create)} WallSection records.")
            self.stdout.write("Data loading complete.")

        except FileNotFoundError:
            raise CommandError(f"Configuration file not found at: {config_file}")
        except ValueError as e:
            raise CommandError(f"Error processing configuration file: {e}")
        except Exception as e:
            logger.exception("Unexpected error during data loading")
            raise CommandError(f"An unexpected error occurred during loading: {e}")

    def handle(self, *args, **options):
        config_file = options["config_file"]

        # --- Clear and Load Data ---
        try:
            self.clear_and_load_data(config_file)
        except CommandError as e:
            self.stderr.write(self.style.ERROR(str(e)))
            return

        self.stdout.write(self.style.SUCCESS("Starting single-threaded simulation..."))
        start_time = time.time()

        # --- Main Simulation Loop (Single-Threaded) ---
        day = 0
        cumulative_cost_overall = 0
        cumulative_cost_per_profile = defaultdict(int)  # Store by profile PK

        try:
            while True:
                day += 1
                self.stdout.write(f"Simulating Day {day}...")

                # 1. Identify sections to work on (all incomplete ones)
                sections_to_update = WallSection.objects.filter(is_complete=False)
                if not sections_to_update.exists():
                    self.stdout.write(
                        self.style.SUCCESS(f"Day {day}: All sections completed!")
                    )
                    day -= 1  # Simulation finished on the previous day
                    break

                # Get PKs before update for efficient processing
                section_pks_worked_today = list(
                    sections_to_update.values_list("pk", flat=True)
                )
                if (
                    not section_pks_worked_today
                ):  # Should be caught by exists() but double check
                    self.stdout.write(
                        self.style.WARNING(
                            f"Day {day}: No sections found to update, but exists() was true? Finishing."
                        )
                    )
                    day -= 1
                    break

                # 2. Perform the update (+1 foot for all active sections)
                # Use F() expression for atomic increment across all selected sections
                updated_count = sections_to_update.update(
                    current_height=F("current_height") + 1
                )
                logger.debug(
                    f"Day {day}: Attempted to update {len(section_pks_worked_today)} sections, DB reported {updated_count} updated."
                )
                if updated_count != len(section_pks_worked_today):
                    logger.warning(
                        f"Day {day}: Mismatch in expected vs actual updated sections ({len(section_pks_worked_today)} vs {updated_count})."
                    )

                # 3. Mark newly completed sections
                newly_completed_pks = list(
                    WallSection.objects.filter(
                        pk__in=section_pks_worked_today,
                        current_height__gte=TARGET_HEIGHT,
                        is_complete=False,  # Only mark those not already marked
                    ).values_list("pk", flat=True)
                )

                if newly_completed_pks:
                    WallSection.objects.filter(pk__in=newly_completed_pks).update(
                        is_complete=True
                    )
                    logger.debug(
                        f"Day {day}: Marked {len(newly_completed_pks)} sections as complete."
                    )

                # 4. Calculate and Store Daily Results
                # We need profile IDs for sections worked today to aggregate costs/ice
                # Fetch profile PKs for sections that were worked (identified by their PKs)
                worked_sections_data = WallSection.objects.filter(
                    pk__in=section_pks_worked_today
                ).values(
                    "pk", "profile_id"
                )  # Get profile_id associated with each worked section

                feet_added_per_profile_pk = defaultdict(int)
                for section_data in worked_sections_data:
                    # Each worked section added 1 foot
                    feet_added_per_profile_pk[section_data["profile_id"]] += 1

                daily_records_to_create = []
                day_overall_ice = 0
                day_overall_cost = 0

                # Records per profile
                for p_pk, feet_added in feet_added_per_profile_pk.items():
                    if feet_added == 0:
                        continue  # Skip profiles where no sections were worked (shouldn't happen here)

                    ice_today = feet_added * YARDS_PER_FOOT
                    cost_today = feet_added * COST_PER_FOOT

                    cumulative_cost_per_profile[p_pk] += (
                        cost_today  # Update cumulative for this profile PK
                    )
                    day_overall_ice += ice_today
                    day_overall_cost += cost_today

                    daily_records_to_create.append(
                        DailyRecord(
                            profile_id=p_pk,
                            day=day,
                            is_overall=False,
                            ice_yards_today=ice_today,
                            cost_today=cost_today,
                            cumulative_cost=cumulative_cost_per_profile[p_pk],
                        )
                    )

                # Overall record for the day
                cumulative_cost_overall += day_overall_cost
                if (
                    day_overall_cost > 0 or day_overall_ice > 0
                ):  # Only create overall if work was done
                    daily_records_to_create.append(
                        DailyRecord(
                            profile_id=None,
                            day=day,
                            is_overall=True,
                            ice_yards_today=day_overall_ice,
                            cost_today=day_overall_cost,
                            cumulative_cost=cumulative_cost_overall,
                        )
                    )

                # Bulk create records
                if daily_records_to_create:
                    DailyRecord.objects.bulk_create(daily_records_to_create)

            # --- End of Simulation Loop ---

            simulation_end_time = timezone.now()
            final_cost = cumulative_cost_overall
            final_day = day  # Last day recorded

            # Save metadata
            SimulationMetadata.objects.create(
                total_days=final_day,
                final_overall_cost=final_cost,
                simulation_end_time=simulation_end_time,
            )

            end_time = time.time()
            self.stdout.write("-" * 20)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Simulation finished successfully after {final_day} days."
                )
            )
            self.stdout.write(self.style.SUCCESS(f"Final overall cost: {final_cost}"))
            self.stdout.write(
                self.style.SUCCESS(
                    f"Total simulation time: {end_time - start_time:.2f} seconds"
                )
            )
            self.stdout.write(
                self.style.SUCCESS("Results saved to database and available via API.")
            )
            self.stdout.write("-" * 20)

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nSimulation interrupted by user."))
            # Data up to the last fully completed day should be saved due to loop structure.
        except Exception as e:
            logger.exception("Unhandled exception in main simulation loop.")
            self.stderr.write(
                self.style.ERROR(f"\nUnexpected error in simulation loop: {e}")
            )
            # Potentially partial data saved.
