# costing-kit

코스팅 옵션 보드 키트 — 바이어 원본으로 AI 착샷 → 옵션 전환 화면 → 단일 HTML. 프롬프트 뼈대 + 공용 도구 + 화면 엔진 + 작업 폴더 양식. Claude Code 플러그인으로 설치해서 쓴다.
에이전트용 사용 설명은 `SKILL.md`.

## 설치 (Claude Code 플러그인)

1. Claude Code에서 마켓플레이스 `GG-AX/plugins`를 추가하고(이미 deck-kit을 쓰면 되어 있음) `costing-kit`을 설치한다 — `claude plugin marketplace add GG-AX/plugins` → `claude plugin install costing-kit@gg-ax`, 또는 Manage plugins 화면에서.
2. `/costing-kit:update`를 한 번 실행한다 — 자동 업데이트를 켜고 필요한 프로그램을 점검한다. 예전에 `~/.claude/skills/costing-kit`에 복사해 둔 키트가 있으면 지운다(두 벌이 겹친다).
3. 새 보드용 빈 폴더(이름은 영어)를 만들어 Claude Code로 열고, 바이어 원본(렌더·스케치·아트워크·옵션 정의·원가)을 넣는다.
4. "코스팅 옵션 보드 만들어줘"라고 한다. `/costing-kit`으로 불러도 된다.

맥·윈도우 모두 동작한다. 필요한 것: Python 3(`pip install pillow numpy opencv-python`), Higgsfield CLI(로그인), Microsoft Edge 또는 Google Chrome, 영상 작업은 ffmpeg(맥 `brew install ffmpeg`, 윈도우 `winget install Gyan.FFmpeg`).

## 쓰는 법

- 사용자는 ① 첫 질문 답 ② 견적 승인 ③ 컷 선택 ④ 후처리 승인 때만 참여한다.
- "현황 알려줘" → 작업 폴더 `README.md`를 읽고 답한다. 기록은 자동이다(생성 기록 = 훅, 사용자 결정 = 에이전트).

## 키트 버전 기록

키트 = 이 폴더 전체. 작업 폴더 README 첫 줄에 맨 아래 버전을 적는다. 번호는 vX.Y.Z — 패치(Z) 버그·화면 수정, 마이너(Y) 실전 피드백 묶음, 메이저(X) 작업 폴더·data.js 형식이 바뀔 때. git 태그 `kit-vX.Y.Z`.

| 버전 | 날짜 | 바뀐 점 |
| --- | --- | --- |
| v0.1 | 2026-10-19 | 뼈대: SKILL.md·README·template(CLAUDE.md·README·log.md·훅 settings.json), `log_hook.py`. 프롬프트·나머지 도구·화면 엔진은 아직 없음. 맥·윈도우 겸용(훅 `python3 \|\| python`, 경로 `/`) |
| v0.2 | 2026-10-19 | `prompts/` 10종(sheet·shot_base·shot_option_fresh·shot_option_edit·white_base·artwork_2x2·artwork_from_ref·video_turn_front·video_turn_back·video_option). 모델 고정 안 함(원칙을 역할 + 검증된 예로), 낭비 방지·영상 연출·턴 원칙 |
| v0.3 | 2026-10-19 | 도구: `run.py`(이미지·영상 생성, 낭비 방지 7규칙) · `video_post.py` · `lint.py` · `align_sketch` `diff_check` `fit_height` `restore_head` `sync_screen` 이식. 모두 `--self-test`. 출력 UTF-8(한국어 윈도우 콘솔) |
| v0.4 | 2026-10-19 | 화면 엔진 v1.0(`template/screen/`), 도구 `single_file.py`·`shots.py`·`split_fb.py`. ffmpeg로 `video_post` 인코딩 시험 통과 |
| v0.5 | 2026-10-19 | 첫 실전 피드백 16건 반영. 뼈대: 승인 run에서 `shot_front`·`shot_front_option`·`video_option`(교체)·`video_loop` 추가(원래 값으로 채우면 승인 프롬프트와 바이트 동일). `run.py --template --values`(채운 프롬프트는 run.json에만). `video_post` loop·strip, 턴 결과 `_loop.mp4`. lint: 영상 final은 post로 대조, `kit_feedback.md` 허용. 견적 줄 첫 숫자 읽기. SKILL: 단계 체크리스트·시트 먼저·포즈는 시트에서·원가 없음 선택·영상 기본값·중간 프레임 검수 |
| v1.0 | 2026-10-28 | 화면 엔진 v2(가로 비포·애프터, `engine/`로 이동 — 작업 폴더에 복사하지 않음). 작업 폴더 `source refs runs board work`(`final`·`screen`·`output` 없앰), 공유본 = `board/v<N>_motion.html`·`v<N>_still.html`(수정마다 N+1). `single_file` 재작성(참조된 파일만·1200 JPEG·두 판·`--draft`), `sync_screen` 삭제, `shots --check`. 도구 공통 `_common.py`(py3.9). 버그: run.py가 create 뒤 job ID를 버려 재결제될 수 있던 것, `k.fc: null` 화면 크래시(lint ERR로), sync mtime 비교, lint가 맥·OneDrive 숨김 파일을 ERR. lint에 data.js·턴 길이·미참조 검사, 훅이 run.json 편집에도 발동. 끄기 모션 폐지(켜기만). 설계 = 개발 `docs/02_engine_v2_design.md` |
| v1.0.1 | 2026-10-29 | 화면 엔진 v2.1~v2.3: 영상 보드 전환 때 칸 테두리 선 제거, 유리판 깜빡임 제거, Clear all 폭(패치) |
| v1.1.0 | 2026-10-29 | **플러그인으로 배포**(GG-AX/plugins 마켓플레이스, 공개 저장소 GG-AX/costing-kit, 자동 업데이트). KIT 경로 = `${CLAUDE_SKILL_DIR}`, 작업 기록 훅을 작업 폴더 `.claude/settings.json`에서 플러그인 훅으로(README 현황 표시줄이 있는 폴더에서만 동작), `/costing-kit:update`(업데이트·환경 점검). 출처 주석의 바이어 이름을 일반 표현으로 |

## 화면 엔진 버전 기록

엔진 = `engine/`(index.html · engine.css · engine.js). 바꾸면 `engine.js` 첫 줄 버전과 이 표를 함께 올린다. 공유본은 만들 때의 엔진을 품으므로 옛 보드는 그대로 열린다.

| 버전 | 날짜 | 바뀐 점 |
| --- | --- | --- |
| v1.0 | 2026-10-19 | 스틸 보드 화면 + 영상 보드(절감액) 통합. 내용은 `data.js`(JSON) 하나로, 원가 방식 `cost`/`save`. 죽은 코드(줌·쇼룸·언어 토글) 삭제, 파일 검사는 2^n → n+1, 주소로 상태 지정(`?shot#s=&o=&b=`). 두 보드 산출물을 data.js만으로 재현 확인 |
| v1.1 | 2026-10-19 | 프레임을 맞춘 영상 이음(스틸→켜기, 영상 끝→다음)은 블러 없이 바로 잇기(첫 실전에서 사용자 승인한 수정). 반복 영상 이름 `_turn` → `_loop`. `money: ""`이면 옵션 금액 칸도 비움 |
| v2.0 | 2026-10-28 | 1920×1080 가로, 오리지널·옵션 나란히 비교(10/21·10/28 가로 보드 기준). 두 칸 턴 영상 동기 재생, 켜기 모션, `select` one/multi(조합 키 `o13`), still 판(양쪽 정지 컷 + 앞뒤), 디테일 전·후 카드, 컬러 변형 칩, 스타일별 로고·자릿수, 단가 전·후 %. 쇼룸·한국어 토글·끄기 모션 삭제. 두 가로 보드 공유본을 data.js만으로 재현(84.5MB → 52.7 / 5.3MB) |
| v2.1 | 2026-10-29 | 영상에 같은 장면 정지 컷을 poster로(디코딩 전 빈 칸 → 바탕과 어긋난 사각 테두리가 보이던 것), 바탕(#stagebg)도 0.6초 페이드 |
| v2.2 | 2026-10-29 | 칸 가장자리 녹이기를 mask-image → 바탕색 그라데이션 띠를 위에 덮기로(Chrome·Edge가 영상에 mask를 안 먹여 칼선이 보임 — 사용자 캡처). 바탕 = 컷 테두리 평균색(--bgc, 0.6초 전환) |
| v2.3 | 2026-10-29 | 영상 칸 테두리 선 제거(사용자 Chrome 확인): 전환이 끝나면 층의 filter·transform을 none(will-change 없앰) · 층마다 clip-path로 잘라 흐린 영상이 칸 밖으로 번지지 않게 · 덮개 띠를 칸보다 6px 크게, 바깥 8px 불투명 · 칸 안 컷 3% 확대로 16 배수가 아닌 영상의 여분 픽셀(오른쪽·아래 1px 어두운 선)을 밀어냄. 유리판 backdrop-filter 제거(연속 클릭 때 박스 테두리 깜빡임). Clear all 버튼 폭을 옵션 칸에 맞춤 |
