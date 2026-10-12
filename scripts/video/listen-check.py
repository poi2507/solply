"""내레이션 귀 검사 — 장면별 TTS 음성을 Gemini(Vertex)에 들려주고 부자연스러운 곳을 찾게 한다. (cwf/ 에서)"""
import base64, json, subprocess, sys
from pathlib import Path
GCLOUD = str(Path.home() / ".local/google-cloud-sdk/bin/gcloud")
PROJECT, LOC = "gen-lang-client-0014864033", "us-central1"
MODEL = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("s") else "gemini-2.5-pro"
only = {a for a in sys.argv[1:] if a.startswith("s")}
plan = json.loads(Path("plan.json").read_text())
token = subprocess.run([GCLOUD, "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
ASK = """You are a strict audio producer reviewing narration for a product demo video.
The intended script is:
\"\"\"{script}\"\"\"
Listen to the audio carefully. Report ONLY real problems a native English listener would notice:
mispronounced or swallowed words, words that differ from the script, odd stress or rising intonation,
unnatural pauses or rushed phrases, robotic or glitchy sounds, clipped endings, tone that sounds off.
Answer as JSON: {{"verdict": "ok" | "redo", "problems": [{{"time_s": number, "words": "...", "issue": "..."}}]}}"""
for s in plan["scenes"]:
    if not s["narration"] or (only and s["id"] not in only):
        continue
    audio = base64.b64encode(Path(f"work/{s['id']}-tts.mp3").read_bytes()).decode()
    body = {"contents": [{"role": "user", "parts": [
                {"inlineData": {"mimeType": "audio/mpeg", "data": audio}},
                {"text": ASK.format(script=s["narration"])}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    Path("stt/req.json").write_text(json.dumps(body))
    url = f"https://{LOC}-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/{LOC}/publishers/google/models/{MODEL}:generateContent"
    out = subprocess.run(["curl", "-s", "-X", "POST", url, "-H", f"Authorization: Bearer {token}",
                          "-H", "Content-Type: application/json", "-d", "@stt/req.json"], capture_output=True, text=True).stdout
    try:
        text = json.loads(out)["candidates"][0]["content"]["parts"][0]["text"]
        r = json.loads(text)
        print(f"== {s['id']}: {r['verdict']}")
        for p in r.get("problems", []):
            print(f"   {p.get('time_s')}s  [{p.get('words')}]  {p.get('issue')}")
    except Exception:
        print(s["id"], "error:", out[:300])
