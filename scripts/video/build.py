#!/usr/bin/env python3
"""Solply 영상 조립 — 클립 + Google Cloud TTS 내레이션 + 자막 오버레이.

산출물:
  out/solply-subtitles.mp4  자막판 (무음)
  out/solply-narrated.mp4   TTS 내레이션판

장면 길이는 내레이션 길이가 정한다 (내레이션 없는 카드는 지정 길이).
클립 footage가 남거나 부족하면 배속으로 맞춘다 — 화면 녹화는 배속에 잘 견딘다.
"""

import base64
import json
import subprocess
from pathlib import Path

FF, FP = "/opt/homebrew/bin/ffmpeg", "/opt/homebrew/bin/ffprobe"
GCLOUD = str(Path.home() / ".local/google-cloud-sdk/bin/gcloud")
W, H, FPS = 1600, 900, 30

# 내레이션은 Google Cloud TTS. 맥 내장 `say`보다 확연히 자연스럽고, 우리 GCP 크레딧으로 돈다.
# 목소리를 바꾸려면 이 한 줄만 — ko-KR-Chirp3-HD-* (최신 생성형) / Neural2 / Wavenet 중에서.
PROJECT = "gen-lang-client-0014864033"
VOICE = "ko-KR-Chirp3-HD-Achernar"
# 제출 한도가 3분이다. 1.12배면 또박또박함을 잃지 않으면서 10% 남짓 줄어든다.
SPEAKING_RATE = 1.12
GAP = 0.55       # 내레이션 앞뒤 여백 (초)
MAX_SPEED = 1.3  # 화면 녹화 배속 상한 — 이보다 빠르면 심사위원이 로그를 못 읽는다

Path("work").mkdir(exist_ok=True)
Path("out").mkdir(exist_ok=True)
plan = json.loads(Path("plan.json").read_text())


def run(args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"{args[0]} 실패: {(r.stderr or r.stdout)[-700:]}")
    return r


def dur(path):
    return float(run([FP, "-v", "error", "-show_entries", "format=duration",
                      "-of", "csv=p=0", str(path)]).stdout.strip())


# ── 1. 내레이션 (Google Cloud TTS) ────────────────────────────────────
def synthesize(text: str, out_mp3: Path) -> None:
    """한 장면의 내레이션을 합성한다. 실패하면 원인을 그대로 보여준다."""
    token = run([GCLOUD, "auth", "print-access-token"]).stdout.strip()
    body = json.dumps({
        "input": {"text": text},
        "voice": {"languageCode": "ko-KR", "name": VOICE},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": SPEAKING_RATE},
    })
    req = Path("work/tts-req.json")
    req.write_text(body)
    res = run(["curl", "-s", "-X", "POST",
               "https://texttospeech.googleapis.com/v1/text:synthesize",
               "-H", f"Authorization: Bearer {token}",
               "-H", f"x-goog-user-project: {PROJECT}",
               "-H", "Content-Type: application/json",
               "-d", f"@{req}"]).stdout
    payload = json.loads(res)
    if "audioContent" not in payload:
        raise RuntimeError(f"TTS 실패: {str(payload)[:300]}")
    out_mp3.write_bytes(base64.b64decode(payload["audioContent"]))


print(f"① 내레이션 생성 (Google Cloud TTS · {VOICE})")
for s in plan["scenes"]:
    wav = Path(f"work/{s['id']}.wav")
    if not s["narration"]:
        s["narr_dur"] = 0.0
        continue
    mp3 = Path(f"work/{s['id']}-tts.mp3")
    synthesize(s["narration"], mp3)
    run([FF, "-y", "-loglevel", "error", "-i", str(mp3), "-ar", "48000", "-ac", "2", str(wav)])
    s["narr_dur"] = dur(wav)
    print(f"   {s['id']}: {s['narr_dur']:.1f}s")

# 장면 길이 = 내레이션이 필요한 길이와 영상이 필요한 길이 중 긴 쪽.
# 영상을 상한 배속 이상으로 조여 읽을 수 없게 만들지 않는다 — 남는 시간은 침묵으로 둔다.
def clip_pairs(scene):
    """클립 지정: "이름" | ["이름", 사용초] | ["이름", 사용초, 시작초(로딩 구간 스킵)]"""
    out = []
    for c in scene.get("clips", []):
        if isinstance(c, str):
            out.append((c, None, 0.0))
        else:
            out.append((c[0], c[1], c[2] if len(c) > 2 else 0.0))
    return out


for s in plan["scenes"]:
    if s.get("card"):
        s["dur"] = s["duration"]
        continue
    footage = sum(cap if cap else dur(f"clips/{n}.webm") - off for n, cap, off in clip_pairs(s))
    s["footage"] = footage
    # 읽어야 하는 장면(대화·협상 문구)은 장면에서 배속 상한을 1.0까지 낮춘다
    s["dur"] = round(max(s["narr_dur"] + GAP * 2, footage / s.get("maxSpeed", MAX_SPEED)), 2)

total = sum(s["dur"] for s in plan["scenes"])
print(f"   총 길이 {int(total // 60)}:{total % 60:04.1f}")

# ── 2. 장면 영상 (클립 이어붙이고 배속으로 길이 맞춤) ─────────────────
print("② 장면 영상")
for s in plan["scenes"]:
    out = Path(f"work/{s['id']}.mp4")
    target = s["dur"]

    if s.get("card"):  # 정지 카드
        run([FF, "-y", "-loglevel", "error", "-loop", "1", "-i", f"cards/{s['card']}.png",
             "-t", str(target), "-r", str(FPS), "-vf", f"scale={W}:{H}",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", str(out)])
        print(f"   {s['id']}: 카드 {target:.1f}s")
        continue

    # 클립들을 정규화(+지정 길이만 사용)해서 이어붙인다
    parts = []
    for name, cap, off in clip_pairs(s):
        src, norm = Path(f"clips/{name}.webm"), Path(f"work/n-{name}.mp4")
        if not norm.exists():
            args = [FF, "-y", "-loglevel", "error"]
            if off:
                args += ["-ss", str(off)]
            args += ["-i", str(src)]
            if cap:
                args += ["-t", str(cap)]
            run(args + ["-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                               f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0xeef1ee,fps={FPS}",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                        "-pix_fmt", "yuv420p", "-an", str(norm)])
        parts.append(norm)

    lst = Path(f"work/{s['id']}.txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    joined = Path(f"work/{s['id']}-join.mp4")
    run([FF, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", str(joined)])

    footage = dur(joined)
    speed = max(0.75, min(footage / target, s.get("maxSpeed", MAX_SPEED)))  # >1 이면 빨리 감기
    run([FF, "-y", "-loglevel", "error", "-i", str(joined),
         "-vf", f"setpts=PTS/{speed:.5f},fps={FPS}", "-t", str(target),
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-pix_fmt", "yuv420p", "-an", str(out)])
    print(f"   {s['id']}: {footage:.1f}s → {target:.1f}s (×{speed:.2f})")

# ── 3. 자막 오버레이 ─────────────────────────────────────────────────
print("③ 자막")
for s in plan["scenes"]:
    src, out = Path(f"work/{s['id']}.mp4"), Path(f"work/{s['id']}-sub.mp4")
    subs = s.get("subs") or []
    if not subs:
        out.write_bytes(src.read_bytes())
        continue
    inputs, filters, last = ["-i", str(src)], [], "0:v"
    for i, sub in enumerate(subs):
        a, b = sub[0], sub[1]
        inputs += ["-i", f"subs/{s['id']}-{i}.png"]
        t0, t1 = a * s["dur"], b * s["dur"]
        nxt = f"v{i}"
        filters.append(
            f"[{last}][{i+1}:v]overlay=0:0:enable='between(t,{t0:.2f},{t1:.2f})'[{nxt}]"
        )
        last = nxt
    run([FF, "-y", "-loglevel", "error", *inputs,
         "-filter_complex", ";".join(filters), "-map", f"[{last}]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-pix_fmt", "yuv420p", "-an", str(out)])
    print(f"   {s['id']}: {len(subs)}장")

# ── 4. 이어붙이기 → 자막판 ───────────────────────────────────────────
print("④ 자막판")
lst = Path("work/all.txt")
lst.write_text("".join(
    "file '%s'\n" % Path("work/%s-sub.mp4" % s["id"]).resolve() for s in plan["scenes"]
))
silent = Path("out/solply-subtitles.mp4")
run([FF, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
     "-c", "copy", str(silent)])

# ── 5. 내레이션 트랙 → 내레이션판 ────────────────────────────────────
print("⑤ 내레이션판")
seg_files = []
for s in plan["scenes"]:
    seg = Path(f"work/a-{s['id']}.wav")
    if s["narr_dur"]:
        # 앞 여백 + 내레이션, 장면 길이에 맞춰 뒤를 채운다
        run([FF, "-y", "-loglevel", "error", "-i", f"work/{s['id']}.wav",
             "-af", f"adelay={int(GAP*1000)}|{int(GAP*1000)},"
                    f"apad,atrim=0:{s['dur']}",
             "-ar", "48000", "-ac", "2", str(seg)])
    else:
        run([FF, "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", f"anullsrc=r=48000:cl=stereo", "-t", str(s["dur"]), str(seg)])
    seg_files.append(seg)

alst = Path("work/audio.txt")
alst.write_text("".join(f"file '{p.resolve()}'\n" for p in seg_files))
track = Path("work/narration.wav")
run([FF, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(alst),
     "-c", "copy", str(track)])

narrated = Path("out/solply-narrated.mp4")
run([FF, "-y", "-loglevel", "error", "-i", str(silent), "-i", str(track),
     "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(narrated)])

for p in (silent, narrated):
    print(f"✓ {p}  {dur(p):.1f}s  {p.stat().st_size/1e6:.1f}MB")
