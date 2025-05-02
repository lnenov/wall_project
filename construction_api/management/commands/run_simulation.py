import logging
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from construction_api.models import (
    WallProfile,
    WallSection,
    DailyRecord,
    SimulationMetadata,
)
from construction_api.simulation import (
    TARGET_HEIGHT,
    simulate_full_workforce,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Clears previous data, runs the single-threaded wall construction simulation, "
        "and stores results in the database."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "config_file", type=str, help="Path to the input config file."
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

        try:
            # Main Simulation Loop (Single-Threaded)
            daily_records_data = simulate_full_workforce()
            daily_records_to_create = [DailyRecord(**r) for r in daily_records_data]
            DailyRecord.objects.bulk_create(daily_records_to_create)

            simulation_end_time = timezone.now()
            final_day = max(
                [daily_record_data["day"] for daily_record_data in daily_records_data],
                default=0,
            )
            final_cost = max(
                [
                    daily_record_data["cumulative_cost"]
                    for daily_record_data in daily_records_data
                ],
                default=0,
            )

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
