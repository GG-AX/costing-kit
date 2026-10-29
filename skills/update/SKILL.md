---
name: update
description: costing-kit 플러그인을 GitHub의 최신 버전으로 업데이트하고 작업 환경(파이썬·패키지·ffmpeg·브라우저·Higgsfield CLI)을 점검한다. 사용자가 /costing-kit:update를 칠 때만 쓴다.
disable-model-invocation: true
---

# costing-kit 업데이트

0. 자동 업데이트가 꺼져 있으면 켠다. 사용자 설정 `~/.claude/settings.json`(Windows `%USERPROFILE%\.claude\settings.json`)의 `extraKnownMarketplaces.gg-ax`에 `"autoUpdate": true`가 없으면 그 한 키만 더한다(다른 내용은 건드리지 않고, 고친 뒤 JSON으로 읽히는지 확인). 더했으면 "자동 업데이트를 켰다"고 알린다. `gg-ax` 항목이 없으면 건드리지 않는다.
   예전에 복사해 둔 `~/.claude/skills/costing-kit` 폴더가 있으면 "두 벌이 겹친다 — 지워도 되는지" 물은 뒤 예일 때만 지운다.
1. 지금 버전을 확인한다: `claude plugin list` 출력에서 `costing-kit@gg-ax`의 버전.
2. 순서대로 실행한다(PowerShell이나 Bash 어느 쪽이든).
   - `claude plugin marketplace update gg-ax`
   - `claude plugin update costing-kit@gg-ax`
3. 결과를 한국어로 알린다: 이전 버전 → 새 버전(같으면 "이미 최신"). 새 버전이면 키트 `README.md` 키트 버전 기록에서 그 사이에 바뀐 줄을 보여 준다.
4. 바뀌었으면 "`/reload-plugins`를 입력하거나 Claude Code를 다시 시작해야 적용된다"고 알린다.
5. 환경 점검·설치 — 먼저 모두 점검하고, 빠진 것이 있으면 무엇을 설치하는지 한 줄로 말한 뒤 사용자의 "네"를 한 번 받고 빠진 것만 설치한다. 다 있으면 묻지 않고 결과만 알린다.
   ① `python --version`(Mac은 `python3`)이 3.9 이상. 없으면 Windows `winget install Python.Python.3.12`, Mac `brew install python`
   ② `python -c "import PIL, numpy, cv2"`. 안 되면 `python -m pip install --user pillow numpy opencv-python`
   ③ `ffmpeg -version`(영상 보드에만 필요). 없으면 Windows `winget install Gyan.FFmpeg`(설치 뒤 새 터미널), Mac `brew install ffmpeg`
   ④ Microsoft Edge 또는 Google Chrome(캡처·검사). 없으면 설치를 안내만 한다
   ⑤ Higgsfield CLI: `higgsfield --version`. 없거나 로그인이 안 돼 있으면 설치·로그인은 사용자가 하도록 안내만 한다(계정·크레딧이 걸린 일이라 대신하지 않는다)
   ⑥ 확인: `python ${CLAUDE_SKILL_DIR}/../../tools/single_file.py --self-test`가 "self-test 통과"면 "준비 끝". 아니면 어느 단계에서 막혔는지 오류와 함께 알린다.

`claude` 명령을 찾을 수 없으면(VS Code 확장만 깔린 PC) 2단계 대신 "Manage plugins → Plugins 탭 → `costing-kit`의 🔄 버튼"을 누르라고 안내한다. 0·5단계는 그대로 한다.

실패하면 메시지를 그대로 보여 준다. 저장소는 공개라 GitHub 로그인이 필요 없다. 접근 오류(`not found`, `403`, 시간 초과)는 보통 네트워크·프록시 문제이니 마켓플레이스 주소가 `GG-AX/plugins`인지와 인터넷 연결을 본다.
