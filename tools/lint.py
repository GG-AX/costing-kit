"""작업 폴더 트리 검사 — 읽기만 하고(README 3절·log.md 갱신 제외) ERR가 있으면 종료 코드 1. 넘기기 전 반드시 통과.

  python3 lint.py [작업 폴더=.]
  python3 lint.py --self-test

검사(기획 §4.6, 설계 v2 §1.3·§1.4):
  1. 루트·runs/ 루트에 규칙 밖 파일이 없는지, 이름에 한글이 없는지(source/는 바이어 원본이라 제외).
     .DS_Store·Thumbs.db·desktop.ini·.git·.gitignore는 무시
  2. runs/ 폴더마다 run.json이 있고 verdict(후보·확정·폐기)가 비지 않았는지. 미완료 run은 WARN
  3. board/data.js: styles[].c 영문·숫자·- · o[].view F/B/FB · select one/multi · money cost면 k.fc/sc 숫자
     (null ERR — 모르면 k를 뺀다) · money save면 o[].save 숫자|null · detail before/after 파일
  4. board/media: 스타일마다 img/<c>_base_F.jpg(없으면 WARN) · 이름 규칙 밖·data.js에 없는 스타일 = 미참조 WARN ·
     한 스타일 *_loop.mp4 길이 차 > 0.1초 ERR(ffprobe 없으면 INFO)
  5. board/media/img·video 파일마다 확정 run 대조: video_post·split_fb 결과(run.json post)이거나,
     같은 스타일·키의 확정 run이 정확히 하나이고 그 결과와 바이트가 같거나 후처리 memo가 있는지
끝에 README 3절·log.md를 다시 쓰고(log_hook.rebuild) 트리 요약을 찍는다.
"""
import filecmp
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402,F401  (stdout UTF-8)
import log_hook  # noqa: E402

ROOT_FILES = {"CLAUDE.md", "README.md", "log.md", "kit_feedback.md"}
ROOT_DIRS = {".claude", "source", "refs", "runs", "board", "work"}
IGNORE = {".DS_Store", "Thumbs.db", "desktop.ini", ".git", ".gitignore"}
RUN_DIR = re.compile(r"^\d{3}_[A-Za-z0-9-]+_[A-Za-z0-9-]+$")
HANGUL = re.compile(r"[ㄱ-ㆎ가-힣]")
C = r"(?P<c>[A-Za-z0-9-]+)"
K = r"(base|o[1-9]+)"
MEDIA = {  # 설계 §1.4
    "img": re.compile(rf"^{C}_(?P<k>{K})_(?P<v>[FB])\.jpg$"),
    "video": re.compile(rf"^{C}_((?P<k>{K})_loop|m_[FB]_{K}_o[1-9]+)\.mp4$"),
    "chips": re.compile(rf"^{C}\.jpg$"),
    "detail": re.compile(rf"^{C}_[A-Za-z0-9-]+(_before|_after)?\.(jpg|png)$"),  # png도 됨 — single_file이 jpg로 바꿔 넣는다
}


def ignored(rel):
    return any(p in IGNORE for p in rel.parts)


def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def read_board(path, errs):
    """data.js의 `window.BOARD =` 뒤 JSON."""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"window\.BOARD\s*=\s*", text)
    if not m:
        errs.append("board/data.js: `window.BOARD =` 없음")
        return None
    try:
        return json.JSONDecoder().raw_decode(text, m.end())[0]
    except ValueError as e:
        errs.append(f"board/data.js: JSON 아님 — {e} (키는 \"따옴표\", 끝 쉼표 금지)")
        return None


def check_board(root, errs, warns):
    """data.js 검사 → (스타일 c 집합, data.js가 직접 가리키는 media 경로들). 없으면 (None, set())."""
    f = root / "board/data.js"
    if not f.exists():
        return None, set()
    B = read_board(f, errs)
    if not isinstance(B, dict):
        return None, set()
    media = root / "board/media"
    if B.get("select", "one") not in ("one", "multi"):
        errs.append(f"data.js select {B.get('select')!r}: one 또는 multi")
    money = B.get("money", "")
    cs = set()
    refs = {x for x in ((B.get("brand") or {}).get("logo"), B.get("creditLogo")) if x}
    for si, s in enumerate(B.get("styles") or []):
        c = str(s.get("c", ""))
        at = f"data.js styles[{si}] {c}"
        if not re.fullmatch(r"[A-Za-z0-9-]+", c):
            errs.append(f"{at}: c는 영문·숫자·- 만(미디어 파일 이름이 됨)")
        cs.add(c)
        if s.get("logo"):
            refs.add(s["logo"])
        objs = [(at, s)] + [(f"{at} o[{oi}]", o) for oi, o in enumerate(s.get("o") or [])]
        for where, x in objs:
            if money == "cost" and "k" in x:
                k = x["k"] or {}
                bad = [n for n in ("fc", "sc") if not num(k.get(n))]
                if bad:
                    errs.append(f"{where}: k.{'/'.join(bad)}가 숫자 아님 — 원가를 모르면 k를 통째로 뺀다(\"Cost not set\")")
        for oi, o in enumerate(s.get("o") or []):
            where = f"{at} o[{oi}]"
            if o.get("view") not in ("F", "B", "FB"):
                errs.append(f"{where}: view {o.get('view')!r} — F·B·FB 중 하나")
            if money == "save" and "save" in o and o["save"] is not None and not num(o["save"]):
                errs.append(f"{where}: save {o['save']!r} — 달러 숫자 또는 null")
            d = o.get("detail")
            if d:
                refs |= {d[k] for k in ("before", "after", "img") if d.get(k)}
                for side in ("img",) if d.get("img") else ("before", "after"):  # img = 이미 전·후가 한 장에 붙은 그림
                    if not d.get(side) or not (media / d[side]).is_file():
                        errs.append(f"{where}: detail.{side} 파일 없음 — board/media/{d.get(side)}")
        if c and not (media / f"img/{c}_base_F.jpg").is_file():
            warns.append(f"스타일 {c}: board/media/img/{c}_base_F.jpg 없음")
    return cs, refs


def duration(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout)
    except ValueError:
        return None


def check_media(root, cs, refs, errs, warns, infos):
    media = root / "board/media"
    loops = {}
    for p in sorted(media.rglob("*")) if media.is_dir() else []:
        rel = p.relative_to(media)
        if p.is_dir() or ignored(rel) or rel.as_posix() in refs:  # 로고·디테일은 data.js가 직접 가리킨다
            continue
        m = MEDIA.get(rel.parts[0]).match(p.name) if len(rel.parts) == 2 and rel.parts[0] in MEDIA else None
        if not m:
            warns.append(f"board/media/{rel.as_posix()}: 이름 규칙 밖 — 미참조(설계 §1.4)")
            continue
        if cs is not None and m["c"] not in cs:
            warns.append(f"board/media/{rel.as_posix()}: data.js에 없는 스타일 {m['c']} — 미참조")
        if rel.parts[0] == "video" and p.name.endswith("_loop.mp4"):
            loops.setdefault(m["c"], []).append(p)
    if not loops:
        return
    if not shutil.which("ffprobe"):
        infos.append("ffprobe 없음 — 턴 영상 길이 검사 건너뜀")
        return
    for c, ps in loops.items():
        ds = {p.name: duration(p) for p in ps}
        got = [d for d in ds.values() if d is not None]
        if got and max(got) - min(got) > 0.1:
            errs.append(f"스타일 {c} _loop.mp4 길이가 다름(>0.1초): " + " · ".join(f"{n} {d:.2f}s" for n, d in ds.items() if d)
                        + " — video_post --duration으로 맞춘다")


def check_runs_media(root, runs, errs):
    """board/media/img·video ↔ 확정 run (바이트 비교 — mtime 아님)."""
    for sub in ("img", "video"):
        d = root / "board/media" / sub
        for f in sorted(d.iterdir()) if d.is_dir() else []:
            if f.name in IGNORE or not f.is_file():
                continue
            rel = f"board/media/{sub}/{f.name}"
            posted = [r for r in runs if rel in r.get("post", [])]
            if posted:
                if not any(r.get("verdict") == "확정" for r in posted):
                    errs.append(f"{rel}: 만든 run {', '.join(r.get('no', '?') for r in posted)}이 확정이 아님")
                continue
            m = MEDIA[sub].match(f.name)
            if not (m and m["k"]):
                errs.append(f"{rel}: 만든 run 기록(post)이 없음 — video_post·split_fb로 만들거나 run 결과를 그대로 둔다")
                continue
            sure = [r for r in runs if r.get("verdict") == "확정" and (r.get("style"), r.get("key")) == (m["c"], m["k"])]
            if len(sure) != 1:
                errs.append(f"{rel}: {m['c']} {m['k']} 확정 run이 {len(sure)}개 (정확히 1개여야)")
                continue
            r = sure[0]
            same = any((r["_dir"] / o).is_file() and filecmp.cmp(r["_dir"] / o, f, shallow=False)
                       for o in (r.get("outputs") or {}).values())
            if not (same or r.get("memo")):
                errs.append(f"{rel}: run {r['no']} 결과와 바이트가 다름 — 후처리했으면 run.json memo에 적는다")


def lint(root):
    """→ (errs, warns, infos, runs)"""
    root = Path(root)
    errs, warns, infos = [], [], []
    if not (root / "runs").is_dir():
        return [f"{root}: 작업 폴더가 아님(runs/ 없음)"], warns, infos, []

    # 1. 규칙 밖 파일 · 한글 이름
    for p in root.iterdir():
        if p.name not in IGNORE and p.name not in (ROOT_DIRS if p.is_dir() else ROOT_FILES):
            errs.append(f"루트에 규칙 밖 {'폴더' if p.is_dir() else '파일'}: {p.name}")
    for p in (root / "runs").iterdir():
        if p.name not in IGNORE and not (p.is_dir() and RUN_DIR.match(p.name)):
            errs.append(f"runs/에 규칙 밖 항목: {p.name} (run 폴더 NNN_<스타일>_<키>만)")
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if rel.parts[0] != "source" and not ignored(rel) and HANGUL.search(p.name):
            errs.append(f"한글 이름: {rel.as_posix()} (폴더·파일 이름은 영어만)")

    # 2. run.json · verdict
    runs = []
    for d in sorted(p for p in (root / "runs").iterdir() if p.is_dir() and p.name not in IGNORE):
        f = d / "run.json"
        if not f.exists():
            errs.append(f"runs/{d.name}: run.json 없음")
            continue
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            errs.append(f"runs/{d.name}/run.json 읽기 실패: {e}")
            continue
        r["_dir"] = d
        runs.append(r)
        if r.get("verdict") not in log_hook.VERDICTS:
            errs.append(f"run {r.get('no', d.name)}: verdict 비어 있음 — 후보·확정·폐기 중 하나로")
        if r.get("status", "completed") != "completed":
            warns.append(f"run {r.get('no', d.name)}: {r.get('status')} — 미완료면 `run.py --resume {r.get('no')}`")

    # 3~5. board
    cs, refs = check_board(root, errs, warns)
    check_media(root, cs, refs, errs, warns, infos)
    check_runs_media(root, runs, errs)

    for r in runs:
        r.pop("_dir", None)
    return errs, warns, infos, runs


def summary(root, runs):
    lines = ["트리 요약:"]
    for name in sorted(ROOT_DIRS - {".claude"}):
        d = Path(root) / name
        n = sum(1 for p in d.rglob("*") if p.is_file() and not ignored(p.relative_to(d))) if d.is_dir() else 0
        lines.append(f"  {name + '/':8} {n}")
    count = {v: sum(r.get("verdict") == v for r in runs) for v in log_hook.VERDICTS}
    spent = sum(r["credits"] for r in runs if isinstance(r.get("credits"), (int, float)))
    lines.append("  판정 " + " · ".join(f"{k} {v}" for k, v in count.items()) + f" · 크레딧 {spent:g}")
    return "\n".join(lines)


def main(root):
    errs, warns, infos, runs = lint(root)
    if (Path(root) / "runs").is_dir():
        log_hook.rebuild(root)
    for tag, xs in (("ERR  ", errs), ("WARN ", warns), ("INFO ", infos)):
        for x in xs:
            print(tag + x)
    print(summary(root, runs))
    print(f"lint: ERR {len(errs)} · WARN {len(warns)}")
    return 1 if errs else 0


def self_test():
    def board(styles, **kw):
        (t / "board/data.js").write_text("window.BOARD = " + json.dumps({"money": "cost", "styles": styles, **kw}) + ";\n",
                                         encoding="utf-8")

    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        for d in ROOT_DIRS:
            (t / d).mkdir()
        for d in ("img", "video", "chips", "detail"):
            (t / "board/media" / d).mkdir(parents=True)
        (t / "README.md").write_text(f"x\n{log_hook.BEGIN}\n{log_hook.END}\n", encoding="utf-8")
        (t / "runs/001_S_base").mkdir()
        (t / "runs/001_S_base/out.jpg").write_bytes(b"jpg1")
        run = {"no": "001", "style": "S", "key": "base", "outputs": {"F": "out.jpg"}, "verdict": "확정", "credits": 7}
        (t / "runs/001_S_base/run.json").write_text(json.dumps(run), encoding="utf-8")
        (t / "board/media/img/S_base_F.jpg").write_bytes(b"jpg1")
        (t / "board/media/chips/S.jpg").write_bytes(b"c")
        (t / "board/media/detail/S_btn_before.jpg").write_bytes(b"d")
        (t / "board/media/detail/S_btn_after.jpg").write_bytes(b"d")
        ok = [{"c": "S", "k": {"fc": 10, "sc": 12}, "o": [
            {"view": "FB", "k": {"fc": 9, "sc": 11}, "detail": {"before": "detail/S_btn_before.jpg", "after": "detail/S_btn_after.jpg"}}]}]
        board(ok)
        for junk in (".DS_Store", "Thumbs.db", "desktop.ini", ".gitignore"):  # 숨김·시스템 파일은 무시
            (t / junk).write_bytes(b"x")
            (t / "board/media/img" / junk).write_bytes(b"x")
        (t / ".git/objects").mkdir(parents=True)
        (t / ".git/objects/한글").write_bytes(b"x")
        errs, warns, _, _ = lint(t)
        assert errs == [] and warns == [], (errs, warns)

        board([{"c": "S", "k": {"fc": None, "sc": 12}, "o": [{"view": "X"}]}], select="many")  # null fc · 잘못된 view · select
        errs = "\n".join(lint(t)[0])
        for want in ("styles[0] S: k.fc가 숫자 아님", "o[0]: view 'X'", "select 'many'"):
            assert want in errs, (want, errs)
        board([{"c": "S", "o": [{"view": "F", "save": "1.2", "detail": {"before": "detail/S_x_before.jpg"}}]}], money="save")
        errs = "\n".join(lint(t)[0])
        assert "save '1.2'" in errs and "detail.before 파일 없음" in errs and "detail.after 파일 없음" in errs, errs
        board(ok)

        (t / "board/media/img/T_base_F.jpg").write_bytes(b"x")  # data.js에 없는 스타일
        (t / "board/media/video/S_o1_on.mp4").write_bytes(b"x")  # v1.1 이름(폐기)
        warns = "\n".join(lint(t)[1])
        assert "T_base_F.jpg: data.js에 없는 스타일 T" in warns and "S_o1_on.mp4: 이름 규칙 밖" in warns, warns
        (t / "board/media/img/T_base_F.jpg").unlink()
        (t / "board/media/video/S_o1_on.mp4").unlink()

        (t / "board/media/img/S_base_B.jpg").write_bytes(b"other")  # 바이트 다름 · memo 없음
        (t / "메모.txt").write_text("x", encoding="utf-8")  # 규칙 밖 + 한글
        (t / "runs/loose.png").write_bytes(b"x")
        (t / "runs/003_S_o1-motion").mkdir()  # 영상 run: 키가 달라도 post로 대조
        (t / "runs/003_S_o1-motion/run.json").write_text(json.dumps({"no": "003", "style": "S", "key": "o1-motion", "verdict": "확정",
                                                                     "post": ["board/media/video/S_m_F_base_o1.mp4"]}), encoding="utf-8")
        (t / "board/media/video/S_m_F_base_o1.mp4").write_bytes(b"mp4")
        (t / "kit_feedback.md").write_text("x", encoding="utf-8")
        assert not any("S_m_F_base_o1" in e or "kit_feedback" in e for e in lint(t)[0]), lint(t)[0]
        (t / "runs/002_S_o1").mkdir()  # run.json 없음
        errs = "\n".join(lint(t)[0])
        for want in ("S_base_B.jpg: run 001", "루트에 규칙 밖 파일: 메모.txt", "한글 이름: 메모.txt", "runs/에 규칙 밖 항목: loose.png",
                     "002_S_o1: run.json 없음"):
            assert want in errs, (want, errs)
        assert main(t) == 1
        assert "| S | base |" in (t / "README.md").read_text(encoding="utf-8")
        msg = ""
        if shutil.which("ffmpeg") and shutil.which("ffprobe"):  # 턴 길이 차 > 0.1초 → ERR
            for k, sec in (("base", 1), ("o1", 2)):
                p = t / f"board/media/video/S_{k}_loop.mp4"
                subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"testsrc=size=64x96:rate=24:duration={sec}",
                                "-pix_fmt", "yuv420p", str(p)], check=True)
            assert "스타일 S _loop.mp4 길이가 다름" in "\n".join(lint(t)[0])
            msg = " · 턴 길이 차 ERR"
    print("self-test 통과 — 정상 트리 ERR·WARN 0(숨김 파일 무시) · data.js null fc·view·select·save·detail ERR · 미참조 WARN"
          " · 규칙 밖·한글·run.json 없음·media 바이트 불일치 검출 · README 현황 갱신" + msg)


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
