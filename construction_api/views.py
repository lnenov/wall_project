import logging

from django.db.models import Max
from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import WallProfile, DailyRecord, SimulationMetadata

logger = logging.getLogger(__name__)


class DailyIceView(APIView):
    """
    API endpoint for daily ice usage per profile (original_index).
    GET /api/profiles/{profile_id}/days/{day_number}/
    """

    def get(self, request, profile_id, day_number, format=None):
        logger.debug(f"API DailyIceView: profile={profile_id}, day={day_number}")

        try:
            p_original_index = int(profile_id)
            day = int(day_number)
        except ValueError:
            logger.warning(
                f"Invalid integer format for profile_id or day_number: p={profile_id}, d={day_number}"
            )
            return Response(
                {
                    "error": "Profile ID (original index) and Day Number must be integers."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            profile = WallProfile.objects.get(original_index=p_original_index)
            record = DailyRecord.objects.get(profile=profile, day=day, is_overall=False)
            ice_amount = record.ice_yards_today
            logger.debug(
                f"Found daily record for Profile Original Index {p_original_index} Day {day}. Ice: {ice_amount}"
            )
        except WallProfile.DoesNotExist:
            logger.warning(f"Profile with original index {p_original_index} not found.")
            raise Http404(f"Profile with ID {p_original_index} not found.")
        except DailyRecord.DoesNotExist:
            logger.warning(
                f"No daily record found for Profile Original Index {p_original_index}, Day {day}"
            )
            max_day_obj = DailyRecord.objects.aggregate(Max("day"))
            max_simulated_day = (
                max_day_obj["day__max"] if max_day_obj["day__max"] else 0
            )
            if day <= 0 or (
                max_simulated_day > 0 and day > max_simulated_day
            ):  # Check only if records exist
                return Response(
                    {
                        "error": f"Day number must be between 1 and {max_simulated_day} (inclusive)."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            else:
                ice_amount = 0

        return Response(
            {"day": day, "ice_amount": ice_amount}, status=status.HTTP_200_OK
        )


class CostOverviewView(APIView):
    """
    API endpoint for construction cost overview. Profile ID is original_index.
    GET /api/profiles/overview/
    GET /api/profiles/overview/{day_number}/
    GET /api/profiles/{profile_id}/overview/{day_number}/
    """

    def get(self, request, profile_id=None, day_number=None, format=None):
        logger.debug(f"API CostOverviewView: profile={profile_id}, day={day_number}")

        p_original_index = None
        day = None
        profile_instance = None

        if profile_id is not None:
            try:
                p_original_index = int(profile_id)
            except ValueError:
                logger.warning(f"Invalid integer format for profile_id: {profile_id}")
                return Response(
                    {"error": "Profile ID (original index) must be an integer."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                profile_instance = WallProfile.objects.get(
                    original_index=p_original_index
                )
            except WallProfile.DoesNotExist:
                logger.warning(
                    f"Profile with original index {p_original_index} not found."
                )
                raise Http404(f"Profile with ID {p_original_index} not found.")

        if day_number is not None:
            try:
                day = int(day_number)
            except ValueError:
                logger.warning(f"Invalid integer format for day_number: {day_number}")
                return Response(
                    {"error": "Day Number must be an integer."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            else:
                if day <= 0:
                    return Response(
                        {"error": "Day number must be positive."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        cost = 0
        response_day = day

        try:
            if p_original_index is not None and day is not None:
                # Cumulative cost for specific profile up to specific day
                record = DailyRecord.objects.get(
                    profile=profile_instance, day=day, is_overall=False
                )
                cost = record.cumulative_cost
                logger.debug(
                    f"Found cumulative cost {cost} for Profile Original Index {p_original_index} Day {day}"
                )

            elif p_original_index is None and day is not None:
                # Overall cumulative cost up to specific day
                record = DailyRecord.objects.get(
                    profile__isnull=True, day=day, is_overall=True
                )
                cost = record.cumulative_cost
                logger.debug(f"Found overall cumulative cost {cost} for Day {day}")

            elif p_original_index is None and day is None:
                # Final total cost overall (fetch from metadata)
                metadata = SimulationMetadata.objects.order_by(
                    "-simulation_start_time"
                ).first()
                if metadata:
                    cost = metadata.final_overall_cost
                    response_day = None
                    logger.debug(f"Found final overall cost {cost} from metadata")
                else:
                    logger.error("No SimulationMetadata found for final cost query.")
                    return Response(
                        {
                            "error": "Final cost unavailable. No simulation metadata found."
                        },
                        status=status.HTTP_503_SERVICE_UNAVAILABLE,
                    )
            else:
                logger.error(
                    f"Invalid parameter combination for CostOverviewView: profile={profile_id}, day={day_number}"
                )
                return Response(
                    {"error": "Invalid request parameters combination."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except DailyRecord.DoesNotExist:
            logger.warning(
                f"DailyRecord not found for query: profile_original_index={p_original_index}, day={day}, is_overall={p_original_index is None}"
            )
            max_day_obj = DailyRecord.objects.aggregate(Max("day"))
            max_simulated_day = (
                max_day_obj["day__max"] if max_day_obj["day__max"] else 0
            )
            if day is not None and max_simulated_day > 0 and day > max_simulated_day:
                return Response(
                    {
                        "error": f"Requested day {day} is beyond the last simulated day ({max_simulated_day})."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            else:
                latest_record = None
                if (
                    p_original_index is not None and day is not None
                ):  # Cumulative for profile
                    latest_record = (
                        DailyRecord.objects.filter(
                            profile=profile_instance, day__lte=day, is_overall=False
                        )
                        .order_by("-day")
                        .first()
                    )
                elif p_original_index is None and day is not None:  # Cumulative overall
                    latest_record = (
                        DailyRecord.objects.filter(
                            profile__isnull=True, day__lte=day, is_overall=True
                        )
                        .order_by("-day")
                        .first()
                    )
                cost = latest_record.cumulative_cost if latest_record else 0
                logger.debug(
                    f"Record not found for exact day {day}, returning latest cumulative cost: {cost}"
                )

        return Response(
            {"day": response_day, "cost": int(cost)}, status=status.HTTP_200_OK
        )
