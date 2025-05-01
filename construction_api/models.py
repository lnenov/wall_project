from django.db import models

class WallProfile(models.Model):
    """Represents a single wall profile (a line from the input file)."""
    original_index = models.PositiveIntegerField(unique=True, help_text="1-based index from the input file")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Profile {self.original_index}"

class WallSection(models.Model):
    """Represents a single section of a wall profile."""
    profile = models.ForeignKey(WallProfile, related_name='sections', on_delete=models.CASCADE)
    section_index = models.PositiveIntegerField(help_text="0-based index within the profile")
    initial_height = models.IntegerField()
    current_height = models.IntegerField()
    is_complete = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('profile', 'section_index')
        ordering = ['profile__original_index', 'section_index']

    def __str__(self):
        target_height = 30
        status = "Complete" if self.is_complete else f"{self.current_height}/{target_height}"
        return f"Profile {self.profile.original_index} Section {self.section_index} ({status})"

class DailyRecord(models.Model):
    """Stores the calculated results for a specific day, either per profile or overall."""
    profile = models.ForeignKey(WallProfile, on_delete=models.CASCADE, null=True, blank=True, help_text="Null if this is an overall record")
    day = models.PositiveIntegerField(db_index=True)
    is_overall = models.BooleanField(default=False, db_index=True)

    ice_yards_today = models.PositiveIntegerField(default=0)
    cost_today = models.BigIntegerField(default=0)
    cumulative_cost = models.BigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('day', 'profile', 'is_overall')
        ordering = ['day', 'is_overall', 'profile__original_index']
        indexes = [
            models.Index(fields=['day', 'is_overall']),
        ]

    def __str__(self):
        if self.is_overall:
            return f"Day {self.day} (Overall) - Cost: {self.cost_today}, Ice: {self.ice_yards_today}, Cumulative: {self.cumulative_cost}"
        else:
            profile_idx = self.profile.original_index if self.profile else 'N/A'
            return f"Day {self.day} (Profile {profile_idx}) - Cost: {self.cost_today}, Ice: {self.ice_yards_today}, Cumulative: {self.cumulative_cost}"

class SimulationMetadata(models.Model):
    """Stores metadata about the last simulation run."""
    # teams_used field removed
    total_days = models.PositiveIntegerField()
    final_overall_cost = models.BigIntegerField()
    simulation_start_time = models.DateTimeField(auto_now_add=True)
    simulation_end_time = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Simulation run at {self.simulation_start_time} ({self.total_days} days)"
