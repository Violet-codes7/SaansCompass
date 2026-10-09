"""Personas: who the user is, which activities they do, and how hard they breathe.

A persona is just a set of activities, a day window and an effort level, so a
new persona is a new entry here plus its Cedar policies. The thresholds and
schedules below are our own heuristics, not an official order.
"""
from dataclasses import dataclass, field

# Approximate breathing rate in m³ of air per hour for each effort level.
VENTILATION_M3_PER_HOUR = {
    "rest": 0.5,
    "light": 1.0,
    "moderate": 1.6,
    "heavy": 3.0,
}


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


PERSONAS = {
    "school": Persona(
        id="school",
        label="School coordinator or parent",
        question="Should outdoor assembly, PE and recess happen today?",
        start_hour=7,
        end_hour=15,
        effort="light",
        sensitive=True,
        go_max=100,
        limit_max=200,
        flex_activity="outdoor_pe",
        flex_prefers="cleanest",
        commute_hour=7,
        activities=(
            Activity("school_commute", "Morning commute", 7, 30, "light", movable=False),
            Activity("outdoor_assembly", "Outdoor assembly", 8, 20, "light"),
            Activity("outdoor_recess", "Outdoor recess", 11, 30, "moderate"),
            Activity("outdoor_pe", "Outdoor PE / sports", 12, 40, "heavy"),
            Activity("physical_classes_primary", "Fully in-person classes, up to Class V", outdoor=False),
            Activity("physical_classes_senior", "Fully in-person classes, Class VI to IX and XI", outdoor=False),
        ),
        verdict_labels={"go": "Go outdoors", "limit": "Limit outdoor time", "stay_in": "Keep activities indoors"},
    ),
    "rider": Persona(
        id="rider",
        label="Delivery or gig rider",
        question="How exposed will I be on today's shift, and which hours are worst?",
        start_hour=11,
        end_hour=21,
        effort="moderate",
        sensitive=False,
        go_max=200,
        limit_max=300,
        flex_activity="rest_break",
        flex_prefers="worst",
        commute_hour=11,
        activities=(
            Activity("outdoor_shift", "Riding shift on a two-wheeler", outdoor=True),
            Activity("rest_break", "Main rest break", 15, 60, "rest", ruled=False),
            Activity("drive_bs3_petrol_bs4_diesel_car", "Deliveries in a BS-III petrol or BS-IV (or older) diesel car", outdoor=False),
            Activity("drive_bs4_diesel_lgv_outside", "Light goods vehicle, BS-IV or older diesel, registered outside Delhi", outdoor=False),
            Activity("drive_bs4_diesel_mgv", "Medium goods vehicle, BS-IV or older diesel", outdoor=False),
        ),
        verdict_labels={"go": "Normal shift", "limit": "Take breaks indoors", "stay_in": "Cut outdoor hours"},
        whole_window_exposure=True,
    ),
    "older": Persona(
        id="older",
        label="Older adult or person with breathing trouble",
        question="Is it safe to walk or go out today?",
        start_hour=6,
        end_hour=21,
        effort="light",
        sensitive=True,
        go_max=100,
        limit_max=200,
        flex_activity="outdoor_walk",
        flex_prefers="cleanest",
        commute_hour=None,
        activities=(
            Activity("outdoor_walk", "Walk outside", 7, 30, "light"),
            Activity("outdoor_errands", "Errands on foot", 17, 45, "light"),
        ),
        verdict_labels={"go": "Fine to go out", "limit": "Go out briefly", "stay_in": "Stay in"},
    ),
    "worker": Persona(
        id="worker",
        label="Outdoor or construction worker",
        question="How much will I breathe in on today's shift, and when should I rest?",
        start_hour=8,
        end_hour=18,
        effort="moderate",
        sensitive=False,
        go_max=150,
        limit_max=250,
        flex_activity="work_break",
        flex_prefers="worst",
        commute_hour=8,
        activities=(
            Activity("outdoor_work_shift", "Outdoor work shift", outdoor=True),
            Activity("work_break", "Main rest break", 13, 60, "rest", ruled=False),
            Activity("dusty_construction_work", "Dusty construction work (digging, demolition, masonry, tile cutting, road work)"),
            Activity("other_construction_work", "Less dusty construction work (finishing, electrical, plumbing)"),
        ),
        verdict_labels={"go": "Normal shift", "limit": "Mask up and rest indoors", "stay_in": "Cut outdoor hours"},
        whole_window_exposure=True,
    ),
    "commuter": Persona(
        id="commuter",
        label="Office commuter",
        question="How should I get to work today, and is a walk at lunch a good idea?",
        start_hour=8,
        end_hour=20,
        effort="light",
        sensitive=False,
        go_max=150,
        limit_max=250,
        flex_activity="lunch_walk",
        flex_prefers="cleanest",
        commute_hour=9,
        activities=(
            Activity("morning_commute", "Morning commute", 9, 45, "light", movable=False),
            Activity("lunch_walk", "Walk at lunch", 13, 20, "light"),
            Activity("evening_commute", "Evening commute", 18, 45, "light", movable=False),
            Activity("office_attendance", "Going in to the office (not working from home)", outdoor=False),
            Activity("drive_private_car", "Driving your own car (BS-VI petrol or newer)", outdoor=False),
            Activity("drive_bs3_petrol_bs4_diesel_car", "Driving a BS-III petrol or BS-IV (or older) diesel car", outdoor=False),
        ),
        verdict_labels={"go": "Normal day", "limit": "Keep outdoor time short", "stay_in": "Stay inside where you can"},
    ),
    "athlete": Persona(
        id="athlete",
        label="Runner or athlete",
        question="When is the safest time to train outdoors today?",
        start_hour=5,
        end_hour=21,
        effort="heavy",
        sensitive=False,
        go_max=100,
        limit_max=150,
        flex_activity="outdoor_training",
        flex_prefers="cleanest",
        commute_hour=None,
        activities=(
            Activity("warm_up_walk", "Warm-up walk", 6, 15, "light"),
            Activity("outdoor_training", "Outdoor run or training", 6, 60, "heavy"),
        ),
        verdict_labels={"go": "Train outdoors", "limit": "Go easy or train indoors", "stay_in": "Train indoors today"},
    ),
}


def get_persona(persona_id):
    try:
        return PERSONAS[persona_id]
    except KeyError:
        raise ValueError(f"persona must be one of {', '.join(PERSONAS)}") from None
