"""보드 상태를 헤드리스 Edge/Chrome으로 캡처 → work/shots/. 에이전트가 전부 열어 본다. --check는 넘기기 전 자동 검사.

  python3 shots.py                      board/draft_motion.html(없으면 최신 board/v<N>_motion.html)
  python3 shots.py board/v2_still.html  지정한 판
  python3 shots.py --only 0             스타일 0만
  python3 shots.py --check              캡처 대신 상태마다 DOM을 열어 "In production" 0건 · 스크립트 오류 0건을 확인(실패면 종료 1)
  python3 shots.py --self-test

상태: 스타일마다 기본 · 옵션 하나씩 · (select "multi"면) 전부 켠 조합 × 앞·뒤(뒤 컷이 있는 스타일만).
파일: s<스타일>_<base|o13>_<F|B>.png. 주소 ?shot#s=&o=&b= (전환 없이, 영상 대신 정지 컷).
브라우저: 환경변수 BROWSER, 없으면 OS별 Edge·Chrome 기본 위치.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import die, tmpdir  # noqa: E402

CANDIDATES = {
    "win32": [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"],
    "darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
}


def browser():
    env = os.environ.get("BROWSER")
    if env:
        return env
    for p in CANDIDATES.get(sys.platform, []):
        if Path(p).exists():
            return p
    for n in ("msedge", "google-chrome", "chromium", "chrome"):
        if shutil.which(n):
            return shutil.which(n)
    die("Edge/Chrome을 못 찾음 — BROWSER 환경변수로 경로 지정")


def default_page():
    bd = Path("board")
    if (bd / "draft_motion.html").exists():
        return bd / "draft_motion.html"
    vs = sorted(bd.glob("v*_motion.html"), key=lambda p: int(re.sub(r"\D", "", p.name) or 0))
    if not vs:
        die("board/에 HTML이 없음 — 먼저 single_file.py")
    return vs[-1]


def states(html):
    """(스타일 번호, 옵션 키 숫자열, 뒤 여부) 목록. 단일 HTML 안의 window.BOARD와 내장 파일 이름으로 정한다."""
    m = re.search(r"window\.BOARD=(\{.*?\});</script>", html, re.S)
    if not m:
        die("window.BOARD를 못 찾음 — single_file.py로 만든 HTML인가?")
    data = json.loads(m.group(1))
    out = []
    for i, st in enumerate(data.get("styles", [])):
        vis = [str(k + 1) for k, o in enumerate(st.get("o", [])) if not o.get("hidden")]
        combos = ["0"] + vis + (["".join(vis)] if data.get("select") == "multi" and len(vis) > 1 else [])
        sides = (0, 1) if f'"img/{st["c"]}_base_B.jpg"' in html else (0,)
        out += [(i, o, b) for o in combos for b in sides]
    return out


def run(exe, url, profile, extra, timeout=120):
    return subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--mute-audio", f"--user-data-dir={profile}",
                           "--window-size=1920,1080", "--virtual-time-budget=3000", "--enable-logging=stderr", "--v=0", *extra, url],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def main(page=None, only=None, out_dir="work/shots", check=False):
    page = Path(page or default_page()).resolve()
    html = page.read_text(encoding="utf-8")
    exe, out_dir, done, bad = browser(), Path(out_dir), [], []
    if not check and out_dir.exists():
        for p in out_dir.glob("s*_*.png"):
            p.unlink()  # 지난 캡처를 남기지 않는다 — 옛 화면을 보고 판단하지 않게
    with tmpdir() as prof:
        for i, o, b in states(html):
            if only is not None and i != only:
                continue
            url = page.as_uri() + f"?shot#s={i}&o={o}&b={b}"
            name = f"s{i}_{'base' if o == '0' else 'o' + o}_{'B' if b else 'F'}"
            if check:
                r = run(exe, url, prof, ["--dump-dom"])
                errs = [ln for ln in r.stderr.splitlines() if "CONSOLE" in ln and re.search(r"Uncaught|Error", ln)]
                pend = re.search(r'data-pending="(\d+)"', r.stdout)
                if not pend or pend.group(1) != "0" or errs:
                    bad.append(f"{name}: " + ("그려지지 않음" if not pend else f"In production {pend.group(1)}칸" if pend.group(1) != "0" else "") +
                               (" · " + errs[0][-160:] if errs else ""))
            else:
                out = (out_dir / f"{name}.png").resolve()  # 브라우저는 상대 경로를 자기 기준으로 쓴다
                out.parent.mkdir(parents=True, exist_ok=True)
                r = run(exe, url, prof, [f"--screenshot={out}"])
                if not out.exists():
                    die(f"캡처 실패 {url}\n{r.stderr[-500:]}")
            done.append(name)
    if check:
        for x in bad:
            print("ERR", x)
        print(f"--check {page.name}: 상태 {len(done)}개, 문제 {len(bad)}개")
        if bad:
            sys.exit(1)
    else:
        print(f"{len(done)}장 → {out_dir.as_posix()}/  (전부 열어 본다: 잘림·글자 넘침·금액 원본 대조·두 칸 인물 크기)")
    return done


def self_test():
    st = Path(__file__).resolve().parent
    sys.path.insert(0, str(st))
    import single_file
    from PIL import Image
    tpl = st.parent / "template" / "board" / "data.js"
    with tmpdir() as t:
        root = Path(t) / "화면 시험"
        (root / "board" / "media" / "img").mkdir(parents=True)
        data = json.loads(re.fullmatch(r"window\.BOARD\s*=\s*(\{.*\})\s*;?", tpl.read_text(encoding="utf-8").strip(), re.S).group(1))
        data["select"] = "multi"
        data["styles"][0]["o"][1].pop("detail")
        (root / "board" / "data.js").write_text("window.BOARD = " + json.dumps(data) + ";", encoding="utf-8")
        for k in ("base", "o1", "o12"):
            for s in "FB":
                Image.new("RGB", (400, 600), "#b97").save(root / "board" / "media" / "img" / f"STYLE1_{k}_{s}.jpg")
        cwd = os.getcwd()
        os.chdir(root)
        try:
            single_file.build(".", draft=True)
            shots = main(out_dir="work/shots")
            assert len(shots) == 8, shots           # (기본 + o1 + o2 + o12) × 앞뒤
            assert Image.open(Path("work/shots") / "s0_o12_B.png").size == (1920, 1080)
            try:                                    # o2 정지 컷이 없다 → In production
                main(check=True)
                raise AssertionError("빠진 컷을 못 잡음")
            except SystemExit as e:
                assert e.code == 1
            for s in "FB":
                Image.new("RGB", (400, 600), "#b97").save(Path("board/media/img") / f"STYLE1_o2_{s}.jpg")
            single_file.build(".", draft=True)
            assert len(main(check=True)) == 8
        finally:
            os.chdir(cwd)
    print("self-test 통과 — 조합 상태 8장 1920×1080 · --check가 빠진 컷을 잡고, 채우면 통과")


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--self-test" in a:
        self_test()
    else:
        only = int(a[a.index("--only") + 1]) if "--only" in a else None
        pages = [x for i, x in enumerate(a) if not x.startswith("--") and (i == 0 or a[i - 1] != "--only")]
        main(pages[0] if pages else None, only, check="--check" in a)
