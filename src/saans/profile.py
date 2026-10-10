"""A person's own profile: age, health, work, travel and hours.

It lives only in the page's URL and the request. Nothing here is stored, and
it is never written to logs. Thresholds and tips are our own public-health
heuristics, labelled as such on the page: not medical advice.
"""
from dataclasses import dataclass, replace

from . import settings


@dataclass(frozen=True)
class Condition:
    label: str  # as shown on the form
    short: str  # as used in a sentence ("because of: asthma, smoking")
    group: str
    shift: int  # how many AQI points lower the Go and Limit thresholds sit
    charter: bool  # in a group GRAP's Stage IV citizen charter names
    why: str  # what polluted air does to someone with it
    tip: str
    watch: str  # signs that mean go indoors or get help


_CONFIG = settings.load("profile")

# GRAP's Stage IV charter names children, pregnant women, the elderly, and
# people with respiratory, cardiovascular, cerebrovascular or other chronic
# diseases ("charter": true). Other conditions still lower the thresholds.
CONDITION_INFO = {k: Condition(**c) for k, c in _CONFIG["conditions"].items()}
CONDITIONS = {k: c.label for k, c in CONDITION_INFO.items()}
CONDITION_GROUPS = {}
for _id, _c in CONDITION_INFO.items():
    CONDITION_GROUPS.setdefault(_c.group, []).append(_id)
# Conditions that make the lungs or heart react sooner to polluted air.
HEART_LUNG = {k for k, c in CONDITION_INFO.items() if c.shift == 100}

COMMUTE_MODES = _CONFIG["commute_modes"]

# What the person does, mapped to the persona whose activities and rules fit.
WORK = _CONFIG["work"]

AGE_INFO = _CONFIG["age_info"]

COMMUTE_TIPS = _CONFIG["commute_tips"]
VEHICLES = _CONFIG["vehicles"]
VEHICLE_LABELS = _CONFIG["vehicle_labels"]
COMMUTE_ACTIVITIES = set(_CONFIG["commute_activities"])
# Activities that are about driving a particular vehicle.
VEHICLE_ACTIVITIES = {v["activity"] for v in VEHICLES.values() if v["activity"]}


@dataclass(frozen=True)
class Profile:
    work: str
    age: int | None = None
    conditions: tuple = ()
    commute: str | None = None
    start_hour: int | None = None
    end_hour: int | None = None
    mask: bool = False
    job: str | None = None  # what they do, in their own words
    about: str | None = None  # "About me" from a saved profile, for the AI only
    vehicle: str | None = None  # a key of VEHICLES, or None when not given

    @property
    def child(self):
        return self.age is not None and self.age < AGE_INFO["child"]["under"]

    @property
    def older(self):
        return self.age is not None and self.age >= AGE_INFO["older"]["from"]

    @property
    def sensitive(self):
        """In a group GRAP's Stage IV citizen charter names."""
        return self.child or self.older or any(CONDITION_INFO[c].charter for c in self.conditions)

    def threshold_shift(self):
        """How much lower the Go and Limit AQI thresholds sit for this person."""
        shift = max((CONDITION_INFO[c].shift for c in self.conditions), default=0)
        if self.child or self.older:
            shift = max(shift, AGE_INFO["shift"])
        return shift

    def reasons(self):
        out = []
        if self.child:
            out.append("child")
        if self.older:
            out.append(f"over {AGE_INFO['older']['from']}")
        out += [CONDITION_INFO[c].short for c in self.conditions]
        return out

    def tips(self):
        out = [CONDITION_INFO[c].tip for c in self.conditions]
        if self.child:
            out.append(AGE_INFO["child"]["tip"])
        if self.older:
            out.append(AGE_INFO["older"]["tip"])
        return out

    def health(self):
        """What the page's "Your health" panel says, condition by condition."""
        items = []
        if self.child:
            items.append({"title": f"Age {self.age}: a child", **{k: AGE_INFO["child"][k] for k in ("why", "tip", "watch")}})
        if self.older:
            items.append({"title": f"Age {self.age}: over {AGE_INFO['older']['from']}",
                          **{k: AGE_INFO["older"][k] for k in ("why", "tip", "watch")}})
        for c in self.conditions:
            info = CONDITION_INFO[c]
            items.append({"title": info.label, "why": info.why, "tip": info.tip, "watch": info.watch})
        shift = self.threshold_shift()
        level = "highest" if shift >= 100 else "higher" if shift or items else "usual"
        return {"level": level, "shift": shift, "charter": self.sensitive, "details": items,
                "condition_names": [CONDITION_INFO[c].short for c in self.conditions]}

    def summary(self):
        """Profile facts for the page and the AI, without anything identifying."""
        return {
            "work": WORK[self.work],
            "own_words": self.job,
            "about_me": self.about,
            "age": self.age,
            "conditions": [CONDITIONS[c] for c in self.conditions],
            "commute": COMMUTE_MODES.get(self.commute) if self.commute else None,
            "vehicle": VEHICLES[self.vehicle]["label"] if self.vehicle else None,
            "hours": (f"{self.start_hour:02d}:00-{self.end_hour:02d}:00"
                      if self.start_hour is not None and self.end_hour is not None else None),
            "has_n95_mask": self.mask,
            "sensitive_group": self.sensitive,
            "sensitivity": self.health()["level"],
        }

    def apply(self, persona, modes=()):
        """The persona with this person's hours, thresholds, vehicle and way of travelling."""
        shift = self.threshold_shift()
        changes = {}
        if shift:
            changes["go_max"] = max(50, persona.go_max - shift)
            changes["limit_max"] = max(changes["go_max"] + 50, persona.limit_max - shift)
        if self.sensitive:
            changes["sensitive"] = True
        if self.start_hour is not None and self.end_hour is not None:
            changes["start_hour"] = self.start_hour
            changes["end_hour"] = self.end_hour
            if persona.commute_hour is not None:
                changes["commute_hour"] = self.start_hour
        if persona.commute_hour is not None and self.travel_mode(modes) == "none":  # no trip, so no time to set out
            changes["commute_hour"] = None
        activities = self._personal_activities(persona, modes)
        if activities != persona.activities:
            changes["activities"] = activities
        return replace(persona, **changes) if changes else persona

    def travel_mode(self, modes=()):
        """How the person travels: today's modes first, else their profile's."""
        return next((m for m in modes if m in COMMUTE_MODES), None) or self.commute

    def _personal_activities(self, persona, modes):
        """Only the vehicle rules that fit this person's own vehicle, and the
        commute judged by how they actually travel."""
        from .personas import PERSONAS  # here to avoid an import cycle

        out = list(persona.activities)
        vehicle = VEHICLES.get(self.vehicle) if self.vehicle else None
        car = None
        if vehicle is not None:
            out = [a for a in out if a.id not in VEHICLE_ACTIVITIES]
            if vehicle["activity"]:
                template = PERSONAS[vehicle["rules_as"]].activity(vehicle["activity"])
                car = replace(template, label=VEHICLE_LABELS["driving"].format(vehicle=vehicle["short"]),
                              rules_as=vehicle["rules_as"])
                out.append(car)
        mode = self.travel_mode(modes)
        if mode == "none":
            out = [a for a in out if a.id not in COMMUTE_ACTIVITIES]
        elif mode:
            label = COMMUTE_MODES[mode].lower()
            out = [replace(a, label=VEHICLE_LABELS["by"].format(activity=a.label, mode=label),
                           rules_action=car.id if mode == "car" and car else f"travel_{mode}",
                           rules_as=car.rules_as if mode == "car" and car else a.rules_as)
                   if a.id in COMMUTE_ACTIVITIES else a for a in out]
        return tuple(out)


JOB_MAX = _CONFIG["job_max_chars"]


def clean_text(raw, max_chars):
    """Free text trimmed to one line of at most max_chars printable characters."""
    text = "".join(ch if ch.isprintable() else " " for ch in str(raw or ""))
    text = " ".join(text.split())
    return text[:max_chars] or None


def clean_job(raw):
    """The free-text "what do you do" answer, trimmed to one short line."""
    return clean_text(raw, JOB_MAX)


# Keyword fallback for reading the "what do you do" box when the AI model is
# off. Earlier entries win ties: the most exposed kind of work first.
WORK_KEYWORDS = tuple((pid, tuple(words)) for pid, words in _CONFIG["work_keywords"].items())
# Words that settle the answer on their own, e.g. a college student is a
# commuter, not a school child.
WORK_OVERRIDES = tuple((pid, tuple(words)) for pid, words in _CONFIG["work_keyword_overrides"].items())
ROLE = _CONFIG["role"]


def guess_work(text):
    """The persona whose activities best fit someone's own words, or None."""
    import re

    text = (text or "").lower()
    words = re.findall(r"[a-z]+", text)

    def has(k):
        if not k.isascii() or " " in k:
            return k in text  # Hindi or a phrase: match inside the text
        # "marathons" matches "marathon"; short words must match exactly.
        return any(w == k or (len(k) >= 4 and w.startswith(k)) for w in words)

    for persona_id, keywords in WORK_OVERRIDES:
        if any(has(k) for k in keywords):
            return persona_id
    best, best_score = None, 0
    for persona_id, keywords in WORK_KEYWORDS:
        score = sum(1 for k in keywords if has(k))
        if score > best_score:
            best, best_score = persona_id, score
    return best


def tidy_role(text):
    """A short role line from someone's own words when the AI is off:
    'I am a student in nit delhi' -> 'Student in NIT Delhi'."""
    import re

    text = clean_text(text, ROLE["max_chars"] * 2)
    if not text:
        return None
    low = text.lower()
    for prefix in ROLE["prefixes"]:
        if low.startswith(prefix):
            text = text[len(prefix):]
            break
    for word, shown in ROLE["acronyms"].items():
        text = re.sub(rf"(?<![\w.]){re.escape(word)}(?![\w])", shown, text, flags=re.I)
    for place in ROLE["places"]:
        text = re.sub(rf"\b{re.escape(place)}\b", place.title(), text, flags=re.I)
    text = text.rstrip(" .")
    if len(text) > ROLE["max_chars"]:
        text = text[:ROLE["max_chars"]].rsplit(" ", 1)[0] + "…"
    return (text[:1].upper() + text[1:]) or None


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


def parse_profile(args, persona_id, about=None):
    """Build a Profile from query arguments (or a saved profile in the same
    shape), or None when none were given. `about` is the saved "About me"
    text; it never comes from a link. Raises ValueError for bad input."""
    keys = ("age", "cond", "commute", "start", "end", "mask", "job", "vehicle")
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
    vehicle = args.get("vehicle") or None
    if vehicle and vehicle not in VEHICLES:
        raise ValueError(f"vehicle must be one of {', '.join(VEHICLES)}")
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
        job=clean_job(args.get("job")),
        about=clean_text(about, settings.get("about_me_max_chars")),
        vehicle=vehicle,
    )
