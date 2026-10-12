#!/usr/bin/env python3
"""장면별 내레이션 테이크 고르기 — 합성 → Gemini가 듣고 판정 → 문제없는 테이크를 work/에 고정.
Gemini-TTS는 같은 문장도 매번 다르게 읽는다. 여러 번 뽑아 귀 검사를 통과한 것만 쓴다.
사용 (cwf/ 에서, build.py와 같은 환경변수):  python3 ../takes.py [장면id…] [--tries 3]
"""
import base64, json, os, subprocess, sys
from pathlib import Path

GCLOUD = str(Path.home() / ".local/google-cloud-sdk/bin/gcloud")
PROJECT, LOC = "gen-lang-client-0014864033", "us-central1"
VOICE, TTS_MODEL, TTS_PROMPT = os.getenv("VOICE"), os.getenv("TTS_MODEL", ""), os.getenv("TTS_PROMPT", "")
LANG = os.getenv("TTS_LANG") or "-".join(VOICE.split("-")[:2])
RATE = float(os.getenv("SPEAKING_RATE", "1.0"))
args = sys.argv[1:]
tries = int(args[args.index("--tries") + 1]) if "--tries" in args else 3
only = {a for a in args if a.startswith("s")}
plan = json.loads(Path("plan.json").read_text())
Path("work").mkdir(exist_ok=True); Path("stt").mkdir(exist_ok=True)

def token():
    return subprocess.run([GCLOUD, "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()

def post(url, body, user_project=False):
    Path("stt/req.json").write_text(json.dumps(body))
    h = ["-H", f"Authorization: Bearer {token()}", "-H", "Content-Type: application/json"]
    if user_project:
        h += ["-H", f"x-goog-user-project: {PROJECT}"]
    return json.loads(subprocess.run(["curl", "-s", "-X", "POST", url, *h, "-d", "@stt/req.json"],
                                     capture_output=True, text=True).stdout)

def synth(text, out):
    voice = {"languageCode": LANG, "name": VOICE}
    inp = {"text": text}
    if TTS_MODEL:
        voice["modelName"] = TTS_MODEL
        if TTS_PROMPT:
            inp["prompt"] = TTS_PROMPT
    r = post("https://texttospeech.googleapis.com/v1/text:synthesize",
             {"input": inp, "voice": voice, "audioConfig": {"audioEncoding": "MP3", "speakingRate": RATE}}, True)
    out.write_bytes(base64.b64decode(r["audioContent"]))

# 주의: 기대 발음을 판정 지시에 쓰지 않는다 — "Jeff라고 하면 틀림"이라고 적었더니 제대로 읽은 'Jev'도
# Jeff로 들었다고 판정했다 (블라인드 받아쓰기로는 Jev·Jeff를 정확히 구분, 10/12).
ASK = """You are a strict audio producer reviewing narration for a product demo video.
Intended script: \"\"\"{script}\"\"\"
Listen carefully and report ONLY problems a native English listener would clearly notice: wrong or missing words,
mispronounced names, question-like rising endings, clearly slurred phrases, odd pauses, glitches, clipped endings.
Do NOT report normal connected-speech features (a possessive 's blending into the next word, light linking between words).
Answer as JSON: {{"verdict": "ok" | "redo", "problems": [{{"time_s": number, "words": "...", "issue": "..."}}]}}"""

def listen(path, script):
    """Gemini에게 테이크를 들려주고 판정을 받는다. Vertex가 가끔 빈 응답(429 등)을 주면 쉬었다 다시."""
    import time
    audio = base64.b64encode(path.read_bytes()).decode()
    url = (f"https://{LOC}-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/{LOC}"
           "/publishers/google/models/gemini-2.5-pro:generateContent")
    body = {"contents": [{"role": "user", "parts": [{"inlineData": {"mimeType": "audio/mpeg", "data": audio}},
                                                    {"text": ASK.format(script=script)}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    r = {}
    for attempt in range(4):
        r = post(url, body)
        if "candidates" in r:
            return json.loads(r["candidates"][0]["content"]["parts"][0]["text"])
        time.sleep(5 * (attempt + 1))
    return {"verdict": "redo", "problems": [{"words": "-", "issue": f"judge unavailable: {str(r)[:80]}"}]}


for s in plan["scenes"]:
    if not s["narration"] or (only and s["id"] not in only):
        continue
    best = None
    for n in range(1, tries + 1):
        take = Path(f"work/{s['id']}-take{n}.mp3")
        synth(s["narration"], take)
        v = listen(take, s["narration"])
        probs = v.get("problems", [])
        print(f"{s['id']} take{n}: {v['verdict']} " + "; ".join(f"[{p.get('words')}] {p.get('issue')}" for p in probs)[:300])
        if best is None or len(probs) < len(best[1]):
            best = (take, probs)
        if v["verdict"] == "ok" and not probs:
            break
    Path(f"work/{s['id']}-tts.mp3").write_bytes(best[0].read_bytes())
    Path(f"work/{s['id']}-tts.json").write_text(json.dumps(
        {"text": s["narration"], "voice": VOICE, "model": TTS_MODEL, "prompt": TTS_PROMPT}))
    print(f"→ {s['id']}: kept {best[0].name} ({len(best[1])} issues)")
