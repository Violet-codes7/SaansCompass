"""A person's own profile: age, health, work, travel and hours.

It lives only in the page's URL and the request. Nothing here is stored, and
it is never written to logs. Thresholds and tips are our own public-health
heuristics, labelled as such on the page: not medical advice.
"""
from dataclasses import dataclass, replace

CONDITIONS = {
    "asthma": "Asthma",
    "copd": "COPD or other lung disease",
    "heart": "Heart disease or high blood pressure",
    "diabetes": "Diabetes or another long-term illness",
    "pregnant": "Pregnant",
}
# Conditions that make the lungs or heart react sooner to polluted air.
HEART_LUNG = {"asthma", "copd", "heart"}

COMMUTE_MODES = {
    "walk": "On foot",
    "cycle": "Bicycle",
    "two_wheeler": "Two-wheeler",
    "auto": "Auto-rickshaw",
    "bus": "Bus",
    "metro": "Metro",
    "car": "Car or cab",
    "none": "I mostly stay home",
}

# What the person does, mapped to the persona whose activities and rules fit.
WORK = {
    "school": "Student, parent or school staff",
    "rider": "Delivery or gig rider",
    "worker": "Outdoor or construction worker",
    "commuter": "Office worker who commutes",
    "older": "Retired or mostly at home",
    "athlete": "Runner or athlete",
}

TIPS = {
    "asthma": "Keep your reliever inhaler with you and use your preventer as prescribed. Cough, wheeze or a tight chest is a sign to go indoors.",
    "copd": "Keep outdoor time short on poor-air days and follow your action plan. Breathlessness that is worse than usual needs a doctor.",
    "heart": "Polluted air strains the heart. Avoid hard effort outdoors and get chest pain or palpitations checked at once.",
    "diabetes": "Long-term illness makes you more sensitive to polluted air. Keep exertion outdoors light and stay hydrated.",
    "pregnant": "Polluted air matters more during pregnancy. Prefer indoor exercise on poor-air days and keep windows shut at peak hours.",
    "child": "Children breathe faster for their size, so they take in more pollution. Move play indoors when the air is poor.",
    "older": "After 60 the lungs and heart react sooner to polluted air. Walk at the cleanest hour and keep it gentle.",
}

COMMUTE_TIPS = {
    "walk": "Walk on side streets away from heavy traffic where you can.",
    "cycle": "Cycle on quieter roads, and a well-fitted N95 helps on busy ones.",
    "two_wheeler": "A well-fitted N95 under the helmet cuts what you breathe in traffic.",
    "auto": "Autos are open to traffic fumes; an N95 helps on long rides.",
    "bus": "Wait for the bus away from the kerb when you can.",
    "metro": "The metro is one of the cleaner ways to travel; keep the walk to the station short.",
    "car": "Keep windows up and the air on recirculate in heavy traffic.",
    "none": None,
}


@dataclass(frozen=True)
class Profile:
    work: str
    age: int | None = None
    conditions: tuple = ()
    commute: str | None = None
    start_hour: int | None = None
    end_hour: int | None = None
    mask: bool = False

    @property
    def child(self):
        return self.age is not None and self.age < 14

    @property
    def older(self):
        return self.age is not None and self.age >= 60

    @property
    def sensitive(self):
        """In a group GRAP's Stage IV citizen charter names."""
        return self.child or self.older or bool(self.conditions)

    def threshold_shift(self):
        """How much lower the Go and Limit AQI thresholds sit for this person."""
        if set(self.conditions) & HEART_LUNG:
            return 100
        if self.sensitive:
            return 50
        return 0

    def reasons(self):
        out = []
        if self.child:
            out.append("child")
        if self.older:
            out.append("over 60")
        out += [CONDITIONS[c].split(" or ")[0].lower() for c in self.conditions]
        return out

    def tips(self):
        keys = list(self.conditions)
        if self.child:
            keys.append("child")
        if self.older:
            keys.append("older")
        return [TIPS[k] for k in keys]

    def summary(self):
        """Profile facts for the page and the AI, without anything identifying."""
        return {
            "work": WORK[self.work],
            "age": self.age,
            "conditions": [CONDITIONS[c] for c in self.conditions],
            "commute": COMMUTE_MODES.get(self.commute) if self.commute else None,
            "hours": (f"{self.start_hour:02d}:00-{self.end_hour:02d}:00"
                      if self.start_hour is not None and self.end_hour is not None else None),
            "has_n95_mask": self.mask,
            "sensitive_group": self.sensitive,
        }

    def apply(self, persona):
        """The persona with this person's hours and thresholds."""
        shift = self.threshold_shift()
        changes = {}
        if shift:
            changes["go_max"] = max(50, persona.go_max - shift)
            changes["limit_max"] = max(changes["go_max"] + 50, persona.limit_max - shift)
            changes["sensitive"] = True
        if self.start_hour is not None and self.end_hour is not None:
            changes["start_hour"] = self.start_hour
            changes["end_hour"] = self.end_hour
            if persona.commute_hour is not None:
                changes["commute_hour"] = self.start_hour
        return replace(persona, **changes) if changes else persona


def _hour(raw, name):
    if raw in (None, ""):
        return None
    try:
        value = int(str(raw).split(":")[0])
    except ValueError:
        raise ValueError(f"{name} must be an hour from 0 to 23") from None
    if not 0 <= value <= 23:
        raise ValueError(f"{name} must be an hour from 0 to 23")
    return value


def parse_profile(args, persona_id):
    """Build a Profile from query arguments, or None when none were given.
    Raises ValueError with a user-facing message for bad input."""
    keys = ("age", "cond", "commute", "start", "end", "mask")
    if not any(args.get(k) for k in keys):
        return None
    age = args.get("age")
    if age not in (None, ""):
        try:
            age = int(age)
        except ValueError:
            raise ValueError("age must be a whole number") from None
        if not 1 <= age <= 110:
            raise ValueError("age must be between 1 and 110")
    else:
        age = None
    raw_conditions = args.getlist("cond") if hasattr(args, "getlist") else args.get("cond") or []
    if isinstance(raw_conditions, str):
        raw_conditions = [raw_conditions]
    conditions = []
    for c in raw_conditions:
        for part in str(c).split(","):
            part = part.strip()
            if not part or part == "none":
                continue
            if part not in CONDITIONS:
                raise ValueError(f"condition must be one of {', '.join(CONDITIONS)}")
            if part not in conditions:
                conditions.append(part)
    commute = args.get("commute") or None
    if commute and commute not in COMMUTE_MODES:
        raise ValueError(f"commute must be one of {', '.join(COMMUTE_MODES)}")
    start, end = _hour(args.get("start"), "start"), _hour(args.get("end"), "end")
    if (start is None) != (end is None):
        raise ValueError("give both a start and an end hour, or neither")
    if start is not None and start == end:
        raise ValueError("start and end hour must differ")
    return Profile(
        work=persona_id,
        age=age,
        conditions=tuple(conditions),
        commute=commute,
        start_hour=start,
        end_hour=end,
        mask=str(args.get("mask", "")).lower() in ("1", "on", "yes", "true"),
    )
