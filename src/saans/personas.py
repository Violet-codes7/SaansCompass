"""Personas: who the user is, which activities they do, and how hard they breathe.

A persona is just a set of activities, a day window and an effort level, so a
new persona is a new entry in config/personas.json plus its Cedar policies.
The thresholds and schedules there are our own heuristics, not an official
order.
"""
from dataclasses import dataclass, field

from . import settings

_CONFIG = settings.load("personas")
# Approximate breathing rate in m³ of air per hour for each effort level.
VENTILATION_M3_PER_HOUR = _CONFIG["ventilation_m3_per_hour"]


@dataclass(frozen=True)
class Activity:
    id: str
    label: str
    # Hour of day (IST) the activity normally starts; None for rule-only items
    # such as "physical classes" that have no single time.
    hour: int | None = None
    minutes: int = 0
    effort: str = "light"
    outdoor: bool = True
    movable: bool = True  # False for things like the commute that cannot move indoors
    ruled: bool = True  # False for things GRAP has nothing to say about (a rest break)


@dataclass(frozen=True)
class Persona:
    id: str
    label: str
    question: str
    start_hour: int
    end_hour: int  # exclusive; smaller than start_hour means the window crosses midnight
    effort: str
    sensitive: bool
    go_max: int  # best-window AQI at or below this is "Go"
    limit_max: int  # at or below this is "Limit", above is "Stay in"
    flex_activity: str  # the activity whose time we suggest moving
    # "cleanest": suggest the cleanest hours for the flexible activity (it is outdoors).
    # "worst": suggest the dirtiest hours (the activity is a break off the road).
    flex_prefers: str
    commute_hour: int | None
    activities: tuple = field(default_factory=tuple)
    verdict_labels: dict = field(default_factory=dict)
    # Counts the whole window as exposure (for riders on shift) instead of
    # only the timed activities.
    whole_window_exposure: bool = False
    # What each hour's verdict means for this persona, shown hour by hour.
    hour_advice: dict = field(default_factory=dict)

    def hours(self):
        """Hours of day in the persona's window, in order, wrapping past midnight."""
        if self.end_hour > self.start_hour:
            return list(range(self.start_hour, self.end_hour))
        return list(range(self.start_hour, 24)) + list(range(0, self.end_hour))

    def activity(self, activity_id):
        for a in self.activities:
            if a.id == activity_id:
                return a
        raise KeyError(activity_id)


def _persona(raw):
    return Persona(**{**raw, "activities": tuple(Activity(**a) for a in raw["activities"])})


PERSONAS = {p["id"]: _persona(p) for p in _CONFIG["personas"]}


def get_persona(persona_id):
    try:
        return PERSONAS[persona_id]
    except KeyError:
        raise ValueError(f"persona must be one of {', '.join(PERSONAS)}") from None
