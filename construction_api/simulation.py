import itertools
import logging
import time
from multiprocessing import (
    Process,
    Manager,
    Event,
    Semaphore,
)

import pandas as pd

from construction_api.models import WallSection

logger = logging.getLogger(__name__)

# Constants
COST_PER_YARD = 1900
YARDS_PER_FOOT = 195
COST_PER_FOOT = YARDS_PER_FOOT * COST_PER_YARD
TARGET_HEIGHT = 30


def simulate_full_workforce():
    work_done = []
    sections = WallSection.objects.all()
    for section in sections:
        for day in range(1, TARGET_HEIGHT + 1 - section.initial_height):
            work_done.append(
                {
                    "day": day,
                    "profile_id": section.profile_id,
                    "sections_worked": 1,
                }
            )

    return daily_records_data_from_work_done(work_done)


def simulate_partial_workforce(team_count):
    manager = Manager()
    shared_data = manager.dict()
    shared_data["pending_jobs"] = manager.list()
    shared_data["work_done"] = manager.list()

    # Flatten jobs with initial heights
    sections = WallSection.objects.all()
    for section in sections:
        shared_data["pending_jobs"].append(
            (section.profile_id, section.id, section.initial_height)
        )

    # Create synchronization primitives
    day_event = Event()

    # Start workers
    processes = []
    for tid in range(team_count):
        p = Process(
            target=partial_workforce_worker,
            args=(tid, shared_data, day_event),
        )
        p.start()
        processes.append(p)

    # Advance the simulation until all jobs are done
    active_workers = team_count

    while active_workers > 0:
        # Signal workers to start new day
        day_event.set()

        # Wait for all workers to complete the day
        time.sleep(0.1)  # Minimal sleep just to yield CPU

        # Check if workers are still active
        active_workers = sum(1 for p in processes if p.is_alive())

    for p in processes:
        p.join()

    return daily_records_data_from_work_done(itertools.chain(*shared_data["work_done"]))


def partial_workforce_worker(team_id, shared_data, day_event):
    """Worker simulates one team doing exactly one section per day."""
    personal_queue = []
    work_done = []
    current_day = 0

    while True:
        # Wait for new day signal
        day_event.wait()
        current_day += 1

        # If no job, pull one from global pool
        if not personal_queue:
            try:
                # Get exclusive access to shared data
                job = shared_data["pending_jobs"].pop(0)
                personal_queue.append(job)
            except IndexError:
                # No job left in pool
                logger.info(f"Team-{team_id}: relieved")
                # Get exclusive access to shared data
                shared_data["work_done"].append(work_done)
                break

        if personal_queue:
            profile_id, section_id, current_height = personal_queue.pop(0)

            if current_height < TARGET_HEIGHT:
                current_height += 1
                work_done.append(
                    {
                        "day": current_day,
                        "profile_id": profile_id,
                        "sections_worked": 1,
                    }
                )

                if current_height == TARGET_HEIGHT:
                    logger.info(
                        f"Team-{team_id}: completed profile {profile_id}, section {section_id} on day {current_day}"
                    )
                else:
                    # Still not done, add back to own queue
                    logger.debug(
                        f"Team-{team_id}: got profile {profile_id}, section {section_id} to {current_height} on day {current_day}"
                    )
                    personal_queue.append((profile_id, section_id, current_height))

        # Reset event for next day
        day_event.clear()


def daily_records_data_from_work_done(work_done):
    work_done_df = pd.DataFrame(work_done)
    work_done_df["sections_worked"] = 1

    daily_records_data = []
    if not work_done_df.empty:
        work_done_df = work_done_df.groupby(["day", "profile_id"]).count().reset_index()
        for profile_id in work_done_df.profile_id.unique():
            sub = work_done_df[work_done_df.profile_id == profile_id]
            for day in sorted(sub.day.unique()):
                ice_yards_today = (
                    sub[sub.day == day].sections_worked.sum() * YARDS_PER_FOOT
                )
                daily_records_data.append(
                    {
                        "cumulative_cost": sub[sub.day <= day].sections_worked.sum() * COST_PER_FOOT,
                        "ice_yards_today": ice_yards_today,
                        "cost_today": ice_yards_today * COST_PER_YARD,
                        "profile_id": profile_id,
                        "day": day,
                        "is_overall": False,
                    }
                )
        for day in work_done_df.day.unique():
            ice_yards_today = (
                work_done_df[work_done_df.day == day].sections_worked.sum() * YARDS_PER_FOOT
            )
            daily_records_data.append(
                {
                    "cumulative_cost": work_done_df[
                        work_done_df.day <= day
                    ].sections_worked.sum() * COST_PER_FOOT,
                    "ice_yards_today": ice_yards_today,
                    "cost_today": ice_yards_today * COST_PER_YARD,
                    "profile_id": None,
                    "day": day,
                    "is_overall": True,
                }
            )

    return daily_records_data
