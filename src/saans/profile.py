"""A person's own profile: age, health, work, travel and hours.

It lives only in the page's URL and the request. Nothing here is stored, and
it is never written to logs. Thresholds and tips are our own public-health
heuristics, labelled as such on the page: not medical advice.
"""
from dataclasses import dataclass, replace

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


# GRAP's Stage IV charter names children, pregnant women, the elderly, and
# people with respiratory, cardiovascular, cerebrovascular or other chronic
# diseases. Conditions outside that list still lower the thresholds.
CONDITION_INFO = {
    "asthma": Condition(
        "Asthma", "asthma", "Lungs and breathing", 100, True,
        "Fine particles inflame airways that are already sensitive, so attacks come sooner and harder.",
        "Keep your reliever inhaler with you and use your preventer as prescribed.",
        "Cough, wheeze, a tight chest, or needing your reliever more than usual."),
    "copd": Condition(
        "COPD or emphysema", "COPD", "Lungs and breathing", 100, True,
        "Damaged lungs have less reserve, so a bad-air day can tip you into a flare-up.",
        "Keep outdoor time short and follow your COPD action plan.",
        "Breathlessness worse than usual, more or darker phlegm."),
    "bronchitis": Condition(
        "Chronic bronchitis or frequent chest infections", "chronic bronchitis", "Lungs and breathing", 100, True,
        "Pollution irritates the airways and makes chest infections more likely.",
        "Steam inhalation and warm fluids help clear mucus; avoid smoke of any kind.",
        "A cough that keeps getting worse, fever, or green or bloody phlegm."),
    "tb": Condition(
        "TB, now or in the past", "TB", "Lungs and breathing", 100, True,
        "TB can leave scarring that makes the lungs react more to polluted air.",
        "Finish any TB treatment fully and keep follow-up visits, even on bad-air days.",
        "Cough for more than two weeks, coughing blood, night sweats or weight loss."),
    "covid": Condition(
        "Recent COVID or long COVID", "recent or long COVID", "Lungs and breathing", 100, True,
        "Lungs that are still recovering are easily irritated, and breathlessness can return.",
        "Build activity up slowly and do it indoors on poor-air days.",
        "Breathlessness at rest, chest pain, or a racing heart."),
    "allergic_rhinitis": Condition(
        "Allergic rhinitis (hay fever) or dust allergy", "allergies", "Nose, sinus and eyes", 50, True,
        "Dust and smoke set off sneezing, a blocked nose and itching, and can trigger asthma in some people.",
        "Rinse your nose with saline after being out, and take your allergy medicine as prescribed.",
        "Wheeze or a tight chest along with your usual allergy symptoms."),
    "sinusitis": Condition(
        "Sinusitis", "sinusitis", "Nose, sinus and eyes", 50, True,
        "Polluted air dries and inflames the sinuses, so blocked, painful sinuses last longer.",
        "Saline nose rinses and steam help; drink plenty of water.",
        "Facial pain with fever, or symptoms lasting more than ten days."),
    "eyes": Condition(
        "Eye irritation, dry eyes or conjunctivitis", "sore eyes", "Nose, sinus and eyes", 0, False,
        "Smoke and dust make eyes red, watery and itchy.",
        "Wear glasses or sunglasses outdoors, wash your eyes with clean water after, and do not rub them.",
        "Eye pain, blurred vision or a lot of discharge."),
    "heart": Condition(
        "Heart disease or high blood pressure", "heart disease", "Heart, blood and brain", 100, True,
        "Fine particles get into the blood, raise blood pressure and make the heart work harder.",
        "Avoid hard effort outdoors and keep taking your heart and BP medicines.",
        "Chest pain or pressure, palpitations, or unusual breathlessness."),
    "stroke": Condition(
        "Had a stroke or mini-stroke", "past stroke", "Heart, blood and brain", 100, True,
        "Polluted air thickens the blood and raises the risk of another stroke.",
        "Keep taking your blood thinners and BP medicines, and avoid outdoor effort on bad days.",
        "Sudden weakness on one side, a drooping face, slurred speech: call 112 at once."),
    "anaemia": Condition(
        "Anaemia", "anaemia", "Heart, blood and brain", 50, True,
        "With less oxygen in the blood, the heart and lungs already work harder, and polluted air adds to that.",
        "Take iron or other supplements as prescribed and keep outdoor effort light.",
        "Dizziness, a pounding heart or breathlessness on light effort."),
    "diabetes": Condition(
        "Diabetes", "diabetes", "Other long-term illness", 50, True,
        "Polluted air raises inflammation and can make blood sugar harder to control.",
        "Keep exercise going but move it indoors on poor-air days, and check your sugar as usual.",
        "Feeling unwell with high or unusually low sugar readings."),
    "kidney": Condition(
        "Kidney disease", "kidney disease", "Other long-term illness", 50, True,
        "Kidney disease often comes with heart strain, which polluted air makes worse.",
        "Keep outdoor effort light and follow your fluid advice.",
        "Swelling, breathlessness or much less urine."),
    "immune": Condition(
        "Weak immunity (cancer treatment, transplant, HIV, steroids)", "weak immunity", "Other long-term illness", 50, True,
        "A weaker immune system means polluted air is more likely to lead to chest infections.",
        "Wear an N95 in crowded or smoky places and avoid people with colds.",
        "Fever, a new cough or breathlessness: call your doctor early."),
    "pregnant": Condition(
        "Pregnant", "pregnancy", "Life stage and habits", 50, True,
        "Polluted air is linked to low birth weight and early birth, and you breathe more air while pregnant.",
        "Prefer indoor exercise on poor-air days and keep windows shut at the worst hours.",
        "Breathlessness, a bad headache, or less movement from the baby: see your doctor."),
    "smoker": Condition(
        "I smoke or vape", "smoking", "Life stage and habits", 50, False,
        "Smoke already irritates your lungs, and outdoor pollution adds to the same damage.",
        "Bad-air days are a good time to cut down; do not smoke indoors, where it adds to the air everyone breathes.",
        "A cough that will not go away, or getting breathless sooner than before."),
}
CONDITIONS = {k: c.label for k, c in CONDITION_INFO.items()}
CONDITION_GROUPS = {}
for _id, _c in CONDITION_INFO.items():
    CONDITION_GROUPS.setdefault(_c.group, []).append(_id)
# Conditions that make the lungs or heart react sooner to polluted air.
HEART_LUNG = {k for k, c in CONDITION_INFO.items() if c.shift == 100}

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

AGE_INFO = {
    "child": ("Children breathe faster for their size and their lungs are still growing, so they take in more pollution.",
              "Move play and sport indoors when the air is poor, and keep the school run off main roads."),
    "older": ("After 60 the lungs and heart react sooner to polluted air.",
              "Walk at the cleanest hour, keep it gentle, and keep your usual medicines close."),
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
    job: str | None = None  # what they do, in their own words

    @property
    def child(self):
        return self.age is not None and self.age < 14

    @property
    def older(self):
        return self.age is not None and self.age >= 60

    @property
    def sensitive(self):
        """In a group GRAP's Stage IV citizen charter names."""
        return self.child or self.older or any(CONDITION_INFO[c].charter for c in self.conditions)

    def threshold_shift(self):
        """How much lower the Go and Limit AQI thresholds sit for this person."""
        shift = max((CONDITION_INFO[c].shift for c in self.conditions), default=0)
        if self.child or self.older:
            shift = max(shift, 50)
        return shift

    def reasons(self):
        out = []
        if self.child:
            out.append("child")
        if self.older:
            out.append("over 60")
        out += [CONDITION_INFO[c].short for c in self.conditions]
        return out

    def tips(self):
        out = [CONDITION_INFO[c].tip for c in self.conditions]
        if self.child:
            out.append(AGE_INFO["child"][1])
        if self.older:
            out.append(AGE_INFO["older"][1])
        return out

    def health(self):
        """What the page's "Your health" panel says, condition by condition."""
        items = []
        if self.child:
            items.append({"title": f"Age {self.age}: a child", "why": AGE_INFO["child"][0], "tip": AGE_INFO["child"][1],
                          "watch": "Coughing at night, wheeze, or getting breathless at play."})
        if self.older:
            items.append({"title": f"Age {self.age}: over 60", "why": AGE_INFO["older"][0], "tip": AGE_INFO["older"][1],
                          "watch": "Breathlessness, chest discomfort, dizziness or unusual tiredness."})
        for c in self.conditions:
            info = CONDITION_INFO[c]
            items.append({"title": info.label, "why": info.why, "tip": info.tip, "watch": info.watch})
        shift = self.threshold_shift()
        level = "highest" if shift >= 100 else "higher" if shift or items else "usual"
        return {"level": level, "shift": shift, "charter": self.sensitive, "details": items}

    def summary(self):
        """Profile facts for the page and the AI, without anything identifying."""
        return {
            "work": WORK[self.work],
            "own_words": self.job,
            "age": self.age,
            "conditions": [CONDITIONS[c] for c in self.conditions],
            "commute": COMMUTE_MODES.get(self.commute) if self.commute else None,
            "hours": (f"{self.start_hour:02d}:00-{self.end_hour:02d}:00"
                      if self.start_hour is not None and self.end_hour is not None else None),
            "has_n95_mask": self.mask,
            "sensitive_group": self.sensitive,
            "sensitivity": self.health()["level"],
        }

    def apply(self, persona):
        """The persona with this person's hours and thresholds."""
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
        return replace(persona, **changes) if changes else persona


JOB_MAX = 160


def clean_job(raw):
    """The free-text "what do you do" answer, trimmed to one short line."""
    text = "".join(ch if ch.isprintable() else " " for ch in str(raw or ""))
    text = " ".join(text.split())
    return text[:JOB_MAX] or None


# Keyword fallback for reading the "what do you do" box when the AI model is off.
# Earlier entries win ties: the most exposed kind of work first.
WORK_KEYWORDS = (
    ("rider", ("deliver", "delivery", "rider", "zomato", "swiggy", "blinkit", "zepto", "dunzo", "courier", "gig",
               "rapido", "uber", "ola", "cab", "taxi", "driver", "auto", "rickshaw", "scooter", "bike", "डिलीवरी", "ड्राइवर")),
    ("worker", ("construction", "labour", "labor", "labourer", "mason", "builder", "site", "painter", "plumber",
                "electrician", "carpenter", "welder", "farmer", "vendor", "hawker", "guard", "security", "police",
                "sweeper", "sanitation", "safai", "gardener", "mali", "porter", "outdoor", "field", "मजदूर", "किसान")),
    ("athlete", ("runner", "running", "athlete", "cricket", "football", "hockey", "cyclist", "cycling",
                 "marathon", "sports", "sport", "coach", "trainer", "training", "train", "gym", "jogging", "jog", "खिलाड़ी")),
    ("older", ("retired", "retiree", "pensioner", "homemaker", "housewife", "grandmother", "grandfather",
               "grandma", "grandpa", "senior", "elderly", "old", "रिटायर", "गृहिणी")),
    ("school", ("student", "school", "class", "teacher", "principal", "parent", "kid", "kids", "child", "children",
                "son", "daughter", "छात्र", "स्कूल", "शिक्षक")),
    ("commuter", ("office", "software", "engineer", "developer", "bank", "banker", "manager", "accountant",
                  "consultant", "corporate", "desk", "clerk", "government", "sales", "doctor", "nurse", "lawyer",
                  "shop", "shopkeeper", "college", "university", "intern", "ऑफिस", "दफ्तर", "नौकरी")),
)


def guess_work(text):
    """The persona whose activities best fit someone's own words, or None."""
    import re

    text = (text or "").lower()
    words = re.findall(r"[a-z]+", text)

    def has(k):
        if not k.isascii():
            return k in text  # Hindi: match inside the text
        # "marathons" matches "marathon"; short words must match exactly.
        return any(w == k or (len(k) >= 4 and w.startswith(k)) for w in words)

    best, best_score = None, 0
    for persona_id, keywords in WORK_KEYWORDS:
        score = sum(1 for k in keywords if has(k))
        if score > best_score:
            best, best_score = persona_id, score
    return best


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
    keys = ("age", "cond", "commute", "start", "end", "mask", "job")
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
        job=clean_job(args.get("job")),
    )
