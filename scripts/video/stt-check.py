"""내레이션 점검 — 장면별 TTS 음성을 Google STT로 받아써 대본과 비교한다.
대본과 다른 단어, 낮은 인식 신뢰도, 긴 쉼, 끝이 잘린 문장을 찾는다. (cwf/ 에서 실행)"""
import base64, json, re, subprocess, sys, difflib
from pathlib import Path
FF = "/opt/homebrew/bin/ffmpeg"
GCLOUD = str(Path.home() / ".local/google-cloud-sdk/bin/gcloud")
PROJECT = "gen-lang-client-0014864033"
plan = json.loads(Path("plan.json").read_text())
token = subprocess.run([GCLOUD, "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
only = set(sys.argv[1:])
norm = lambda w: re.sub(r"[^a-z0-9]", "", w.lower())
for s in plan["scenes"]:
    if not s["narration"] or (only and s["id"] not in only):
        continue
    flac = Path(f"stt/{s['id']}.flac")
    subprocess.run([FF, "-y", "-loglevel", "error", "-i", f"work/{s['id']}-tts.mp3", "-ac", "1", "-ar", "16000", str(flac)], check=True)
    body = {"config": {"encoding": "FLAC", "sampleRateHertz": 16000, "languageCode": "en-US", "model": "video",
                       "useEnhanced": True, "enableWordTimeOffsets": True, "enableWordConfidence": True,
                       "enableAutomaticPunctuation": True},
            "audio": {"content": base64.b64encode(flac.read_bytes()).decode()}}
    Path("stt/req.json").write_text(json.dumps(body))
    out = subprocess.run(["curl", "-s", "-X", "POST", "https://speech.googleapis.com/v1p1beta1/speech:recognize",
                          "-H", f"Authorization: Bearer {token}", "-H", f"x-goog-user-project: {PROJECT}",
                          "-H", "Content-Type: application/json", "-d", "@stt/req.json"], capture_output=True, text=True).stdout
    res = json.loads(out)
    if "results" not in res:
        print(s["id"], "STT error:", str(res)[:200]); continue
    words = [w for r in res["results"] for w in r["alternatives"][0].get("words", [])]
    heard = [norm(w["word"]) for w in words]
    script = [norm(w) for w in s["narration"].split() if norm(w)]
    sm = difflib.SequenceMatcher(a=script, b=heard)
    issues = []
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op != "equal":
            issues.append(f"{op}: script[{' '.join(script[a0:a1])}] heard[{' '.join(heard[b0:b1])}]")
    t = lambda x: float(x.rstrip("s"))
    for i in range(1, len(words)):
        gap = t(words[i]["startTime"]) - t(words[i-1]["endTime"])
        if gap > 0.9:
            issues.append(f"pause {gap:.1f}s before '{words[i]['word']}' at {t(words[i]['startTime']):.1f}s")
    low = [f"{w['word']}({w.get('confidence',1):.2f}@{t(w['startTime']):.1f}s)" for w in words if w.get("confidence", 1) < 0.75]
    print(f"== {s['id']}  similarity {sm.ratio():.2f}")
    for x in issues: print("  ", x)
    if low: print("   low confidence:", ", ".join(low))
