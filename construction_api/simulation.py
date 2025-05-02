import logging

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
