"""Ask the deployed Ask Saans chat a few questions and print the answers.

    python scripts/ask_saans.py https://<your SiteUrl>/
    python scripts/ask_saans.py https://<your SiteUrl>/ "Can I take my car out today?"

Uses only the standard library. The plan is the one in the link below (a
student commuting by car from Rohini to ITO), not anyone's saved profile.
"""
import json
import sys
import urllib.error
import urllib.request

PLAN = "persona=commuter&area=rohini&to_area=ito&commute=car&modes=car&age=21&route_read=picked"
QUESTIONS = [
    "Can I take my car out today?",
    "What's the best time to go out tomorrow?",
    "Is it okay to go for a run this evening?",
    "What changes for me if Delhi goes to Stage III?",
]


def ask(site, question):
    req = urllib.request.Request(site.rstrip("/") + "/api/chat?" + PLAN,
                                 data=json.dumps({"question": question, "lang": "en"}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)["answer"]
    except urllib.error.HTTPError as exc:
        return f"(error {exc.code}: {json.load(exc).get('error')})"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for q in sys.argv[2:] or QUESTIONS:
        print(f"Q: {q}\nA: {ask(sys.argv[1], q)}\n")
