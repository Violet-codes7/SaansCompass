"""English to Hindi for the whole page.

The browser sends the page's visible text; each string is looked up in a
built-in dictionary (headings, labels, buttons) and anything else goes to
Amazon Translate. Without Translate, the built-in words still switch and the
rest stays in English. Translations are cached in this Lambda's memory only:
page text can carry health details, so it is never written to DynamoDB.
"""
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

MAX_TEXTS = 400
MAX_CHARS = 2000
CHUNK_BYTES = 4500  # TranslateText takes up to 10,000 bytes per call
PAUSE_AFTER_FAILURE = 600

HI = {
    # Site
    "Saans Compass": "साँस कम्पास",
    "Delhi's air rules and your day, in one plan": "दिल्ली के हवा के नियम और आपका दिन, एक योजना में",
    "English": "English",
    "हिंदी": "हिंदी",
    "Advisory only. Not medical advice and not an official order; CAQM declares the GRAP stage.":
        "केवल सलाह। यह चिकित्सा सलाह या सरकारी आदेश नहीं है; GRAP स्टेज CAQM घोषित करता है।",
    # Form
    "Your air plan for today": "आज के लिए आपकी हवा योजना",
    "What do you do most days?": "आप ज़्यादातर दिनों में क्या करते हैं?",
    "Tell us in your own words": "अपने शब्दों में बताइए",
    "About you": "आपके बारे में",
    "Age": "उम्र",
    "Area": "इलाका",
    "How you travel": "आप कैसे आते-जाते हैं",
    "Health conditions (tick any that apply)": "सेहत से जुड़ी समस्याएँ (जो लागू हों उन्हें चुनें)",
    "Your outdoor hours": "आप बाहर कब रहते हैं",
    "From": "से",
    "To": "तक",
    "Usual": "सामान्य",
    "I have an N95 mask": "मेरे पास N95 मास्क है",
    "Show my plan": "मेरी योजना दिखाएँ",
    "Try:": "आज़माएँ:",
    "Lungs and breathing": "फेफड़े और साँस",
    "Nose, sinus and eyes": "नाक, साइनस और आँखें",
    "Heart, blood and brain": "दिल, खून और दिमाग",
    "Other long-term illness": "अन्य लंबी बीमारी",
    "Life stage and habits": "जीवन का पड़ाव और आदतें",
    "Asthma": "अस्थमा (दमा)",
    "COPD or emphysema": "COPD या एम्फायसीमा",
    "Chronic bronchitis or frequent chest infections": "पुराना ब्रोंकाइटिस या बार-बार छाती का संक्रमण",
    "TB, now or in the past": "टीबी, अभी या पहले",
    "Recent COVID or long COVID": "हाल में कोविड या लॉन्ग कोविड",
    "Allergic rhinitis (hay fever) or dust allergy": "एलर्जिक राइनाइटिस या धूल से एलर्जी",
    "Sinusitis": "साइनसाइटिस",
    "Eye irritation, dry eyes or conjunctivitis": "आँखों में जलन, सूखी आँखें या आँख आना",
    "Heart disease or high blood pressure": "दिल की बीमारी या हाई ब्लड प्रेशर",
    "Had a stroke or mini-stroke": "पहले स्ट्रोक या मिनी-स्ट्रोक हुआ है",
    "Anaemia": "खून की कमी (एनीमिया)",
    "Diabetes": "डायबिटीज़ (शुगर)",
    "Kidney disease": "किडनी की बीमारी",
    "Weak immunity (cancer treatment, transplant, HIV, steroids)": "कमज़ोर इम्यूनिटी (कैंसर का इलाज, ट्रांसप्लांट, HIV, स्टेरॉयड)",
    "Pregnant": "गर्भवती",
    "I smoke or vape": "मैं धूम्रपान या वेप करता/करती हूँ",
    "On foot": "पैदल",
    "Bicycle": "साइकिल",
    "Two-wheeler": "दोपहिया",
    "Auto-rickshaw": "ऑटो-रिक्शा",
    "Bus": "बस",
    "Metro": "मेट्रो",
    "Car or cab": "कार या कैब",
    "I mostly stay home": "मैं ज़्यादातर घर पर रहता/रहती हूँ",
    # Work groups
    "Student, parent or school staff": "छात्र, अभिभावक या स्कूल स्टाफ़",
    "Delivery or gig rider": "डिलीवरी या गिग राइडर",
    "Outdoor or construction worker": "बाहर या निर्माण में काम करने वाले",
    "Office worker who commutes": "ऑफ़िस जाने वाले कर्मचारी",
    "Retired or mostly at home": "रिटायर या ज़्यादातर घर पर",
    "Runner or athlete": "धावक या खिलाड़ी",
    "We read you as:": "हमने आपको समझा:",
    "Not right? Pick the closest:": "सही नहीं? सबसे नज़दीकी चुनें:",
    "Update": "बदलें",
    # Plan page
    "Today": "आज",
    "Tomorrow": "कल",
    "Change my details": "मेरी जानकारी बदलें",
    "GRAP stage": "GRAP स्टेज",
    "No restrictions today": "आज कोई पाबंदी नहीं",
    "Estimated from the PM2.5/PM10 forecast": "PM2.5/PM10 पूर्वानुमान से अनुमानित",
    "Declared by CAQM": "CAQM द्वारा घोषित",
    "Demo: set by you": "डेमो: आपके द्वारा चुना गया",
    "Back to the real stage": "असली स्टेज पर लौटें",
    "Try Stage III": "स्टेज III आज़माएँ",
    "Try Stage IV": "स्टेज IV आज़माएँ",
    "GRAP rules for you": "आपके लिए GRAP नियम",
    "What it means for you:": "आपके लिए इसका मतलब:",
    "Why:": "क्यों:",
    "What to do:": "क्या करें:",
    "Official source": "आधिकारिक स्रोत",
    "Allowed": "अनुमति है",
    "Not allowed": "अनुमति नहीं",
    "Advised against": "न करने की सलाह",
    "Check the official order": "आधिकारिक आदेश देखें",
    "You are here": "आप यहाँ हैं",
    "At a glance": "एक नज़र में",
    "Air today": "आज की हवा",
    "Main pollutant": "मुख्य प्रदूषक",
    "Worst time to be outside": "बाहर रहने का सबसे बुरा समय",
    "Your limits": "आपकी सीमाएँ",
    "Rough breath dose (estimate)": "साँस में गया प्रदूषण (अनुमान)",
    "Like smoking": "धूम्रपान जैसा",
    "Weather": "मौसम",
    "What to do": "क्या करें",
    "Your health": "आपकी सेहत",
    "Sensitivity to polluted air:": "प्रदूषित हवा के प्रति संवेदनशीलता:",
    "Usual sensitivity": "सामान्य",
    "Higher": "ज़्यादा",
    "Highest": "सबसे ज़्यादा",
    "Why air matters:": "हवा क्यों मायने रखती है:",
    "Do this:": "यह करें:",
    "Watch for:": "इन पर ध्यान दें:",
    "Protect yourself every day": "हर दिन अपना बचाव करें",
    "Get help now if": "तुरंत मदद लें अगर",
    "Your activities": "आपकी गतिविधियाँ",
    "Personal advice": "निजी सलाह",
    "Listen": "सुनें",
    "Your day, hour by hour": "आपका दिन, घंटे-दर-घंटे",
    "Please read": "कृपया पढ़ें",
    "Daily poster": "दैनिक पोस्टर",
    "Subscribe": "सदस्यता लें",
    "Air quality": "हवा की गुणवत्ता",
    "Weather now": "अभी का मौसम",
    "Now": "अभी",
    "Temperature": "तापमान",
    "Humidity": "नमी",
    "Wind": "हवा की गति",
    "Why it matters:": "यह क्यों मायने रखता है:",
    "Day average, forecast": "दिन का औसत, पूर्वानुमान",
    # AQI categories and verdicts
    "Good": "अच्छी",
    "Satisfactory": "संतोषजनक",
    "Moderate": "मध्यम",
    "Poor": "खराब",
    "Very Poor": "बहुत खराब",
    "Severe": "गंभीर",
    "No data": "डेटा नहीं",
    "Go outdoors": "बाहर जा सकते हैं",
    "Limit outdoor time": "बाहर कम समय बिताएँ",
    "Keep activities indoors": "गतिविधियाँ अंदर रखें",
    "Normal shift": "सामान्य शिफ्ट",
    "Take breaks indoors": "ब्रेक अंदर लें",
    "Cut outdoor hours": "बाहर के घंटे कम करें",
    "Fine to go out": "बाहर जाना ठीक है",
    "Go out briefly": "थोड़ी देर के लिए बाहर जाएँ",
    "Stay in": "घर में रहें",
    "Mask up and rest indoors": "मास्क पहनें और अंदर आराम करें",
    "Normal day": "सामान्य दिन",
    "Keep outdoor time short": "बाहर कम समय रहें",
    "Stay inside where you can": "जहाँ हो सके अंदर रहें",
    "Train outdoors": "बाहर ट्रेनिंग करें",
    "Go easy or train indoors": "हल्का करें या अंदर ट्रेनिंग करें",
    "Train indoors today": "आज अंदर ट्रेनिंग करें",
    "Fine for outdoor activity.": "बाहर की गतिविधि के लिए ठीक।",
    "Keep outdoor time short and easy.": "बाहर का समय कम और हल्का रखें।",
    "Keep activity indoors.": "गतिविधि अंदर रखें।",
    "No forecast for this hour.": "इस घंटे का पूर्वानुमान नहीं है।",
    "Normal riding.": "सामान्य राइडिंग।",
}


def _core(text):
    """Split off leading and trailing punctuation so " · Moderate" finds "Moderate"."""
    strip = " ·:,()–-•"
    start = len(text) - len(text.lstrip(strip))
    end = len(text.rstrip(strip))
    return text[:start], text[start:end], text[end:]


def builtin(text):
    """The dictionary's Hindi for `text`, or None."""
    if text in HI:
        return HI[text]
    head, core, tail = _core(text)
    if core in HI:
        return head + HI[core] + tail
    if core + ":" in HI:
        return head + HI[core + ":"].rstrip(":") + tail
    return None


_cache = {}
_state = {"paused_until": 0.0}
_client = None


def translate_enabled():
    return os.environ.get("TRANSLATE", "").lower() in ("on", "1", "true")


def _translate_client():
    global _client
    if _client is None:
        import boto3

        _client = boto3.client("translate")
    return _client


def _remember(src, dst):
    if len(_cache) >= 5000:
        _cache.pop(next(iter(_cache)))
    _cache[src] = dst


def _translate_chunk(client, chunk):
    """Translate a list of strings in one call, joined by newlines; per string
    if the line count does not come back the same."""
    resp = client.translate_text(Text="\n".join(chunk), SourceLanguageCode="en", TargetLanguageCode="hi")
    lines = resp["TranslatedText"].split("\n")
    if len(lines) == len(chunk):
        return lines
    return [client.translate_text(Text=t, SourceLanguageCode="en", TargetLanguageCode="hi")["TranslatedText"]
            for t in chunk]


def _chunks(texts):
    chunk, size = [], 0
    for t in texts:
        n = len(t.encode()) + 1
        if chunk and size + n > CHUNK_BYTES:
            yield chunk
            chunk, size = [], 0
        chunk.append(t)
        size += n
    if chunk:
        yield chunk


def to_hindi(texts, client=None, now=None):
    """Hindi for each string, in order. Returns (texts, complete): complete is
    False when some strings had to stay in English."""
    out = list(texts)
    todo = []
    texts = [" ".join(t.split()) for t in texts]  # one line each, for the newline batching
    for i, t in enumerate(texts):
        hit = builtin(t) or _cache.get(t)
        if hit is not None:
            out[i] = hit
        else:
            todo.append(i)
    now = now if now is not None else time.time()
    if not todo:
        return out, True
    if not (client or translate_enabled()) or now < _state["paused_until"]:
        return out, False
    unique = list(dict.fromkeys(texts[i] for i in todo))
    client = client or _translate_client()
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            parts = list(pool.map(lambda c: (c, _translate_chunk(client, c)), _chunks(unique)))
    except Exception as exc:  # missing permission, throttling, network
        log.warning("amazon translate failed: %s", type(exc).__name__)
        _state["paused_until"] = now + PAUSE_AFTER_FAILURE
        return out, False
    for src, dst in parts:
        for a, b in zip(src, dst):
            _remember(a, b)
    for i in todo:
        out[i] = _cache.get(texts[i], texts[i])
    return out, True
