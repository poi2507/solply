# 제출 영상 촬영·조립 도구

라이브 화면을 Playwright로 녹화하고, macOS 내레이션과 자막을 얹어 mp4로 조립한다.
사람이 마우스를 잡지 않으므로 **코드가 바뀌면 몇 분 만에 같은 영상을 다시 만들 수 있다.**
대본은 [../../docs/video-script.md](../../docs/video-script.md), 장면 구성은 `plan.json`.

## 준비

```bash
brew install ffmpeg
npm i playwright@1.62 && npx playwright install chromium
gcloud scheduler jobs pause solply-tick --location=us-central1   # 촬영 중 상태 고정
```

## 3단계

```bash
node record.mjs clip0a clip0b clip3a …   # ① 라이브 화면 녹화 → clips/*.webm
node subs.mjs                            # ② 자막 PNG 생성 → subs/
python3 build.py                          # ③ 조립 → out/solply-{subtitles,narrated}.mp4
gcloud scheduler jobs resume solply-tick --location=us-central1  # ④ 촬영 끝나면 재개
```

클립 이름은 `record.mjs` 맨 아래 `CLIPS` 목록에 있다. 한 장면만 다시 찍고 `build.py`를
다시 돌리면 그 장면만 갱신된다 (`work/n-*.mp4` 캐시를 지워야 다시 정규화된다).

## 촬영 순서 주의

- **라이브 기록을 쓰는 장면(clip0a·clip0b·clip3*)을 먼저 찍는다.** `solply-demo` Job은
  DB를 리셋하므로, 쌓인 거래 역사가 필요한 장면을 나중에 찍으면 사라진다.
- 시세 구매 장면(clip3b)은 **마지막 틱에서 10분이 지난 뒤** 찍어야 한다 —
  10분 캐시가 살아 있으면 구매 이벤트가 안 생긴다 (설계된 동작).
- 청구서 타임라인 장면은 특정 번호를 겨냥한다 (차감 `INV-0729-B01`, 유예 `INV-0729-C01`,
  거부 `INV-0729-A02`). DB가 리셋되면 번호가 바뀌므로 `record.mjs`에서 갱신할 것.

## 조립 규칙 (build.py)

- **장면 길이 = 내레이션이 필요한 길이와 영상이 필요한 길이 중 긴 쪽.** 영상을
  `MAX_SPEED`(1.3배) 이상으로 조이지 않는다 — 심사위원이 로그를 읽어야 하는 영상이다.
  읽을 게 많은 장면은 `plan.json`에 `maxSpeed`를 따로 준다 (대화 장면은 1.0 = 실제 속도).
- 남는 시간은 침묵으로 둔다. 자막 시각은 장면 길이의 비율(0~1)로 적어서 길이가 바뀌어도
  자동으로 맞춰진다.
- 자막은 ASS가 아니라 **PNG 오버레이** — 한글 폰트 대체 사고를 원천 차단하고
  대시보드와 같은 타이포를 쓴다.
- 내레이션은 macOS `say -v Yuna`. 기술 용어는 자막이 정확하게 적고,
  내레이션 문장은 **읽기 좋게** 쓴다 (예: "x402" → "표준 응답").
- **문장은 표어가 아니라 사실로 쓴다.** "멈출 줄 아는 에이전트가 신뢰할 수 있는 에이전트" 같은
  경구는 AI가 쓴 티가 난다 — "점주가 정한 상한을 넘으면 결제를 멈춘다"처럼 화면에 보이는 것을 적는다.

## 산출물

| 파일 | 용도 |
|---|---|
| `out/solply-subtitles.mp4` | 자막판(무음) — 본인 목소리를 얹을 베이스 |
| `out/solply-narrated.mp4` | TTS 내레이션판 — 그대로 제출 가능 |
