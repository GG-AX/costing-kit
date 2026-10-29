"""생성 1회 = runs/NNN_<스타일>_<키>/ 폴더 하나(run.json + 결과 + compare.jpg). 이미지·영상 공용. 작업 폴더에서 실행.

  python3 run.py <스타일> <키> --model <job_type> --template <뼈대.txt> --values refs/values/<스타일>_<키>.json
                 [--image refs/a.png …] [--start-image A --end-image B] [--aspect 2:3]
                 [--param name=value …] [--views F,B] [--changed "직전 대비 바꾼 것"] [--step base]
  python3 run.py --estimate …같은 인자…      견적만(job·폴더 안 만듦)
  python3 run.py --dry …같은 인자…           CLI를 부르지 않고 할 일만 출력
  python3 run.py --resume NNN [--job-id ID]  저장된 job ID로 기다리기·받기만(새 결제 없음)
  python3 run.py --self-test

모델은 인자로만 받는다(기본값 없음). 낭비 방지(SKILL 원칙 "낭비"):
  같은 입력(모델·프롬프트·참조 sha·파라미터)의 run이 있으면 건너뜀(--again으로만 다시) ·
  job ID는 create 직후 wait 전에 run.json에 · 실패는 자동 재생성 없이 종료 코드 1 ·
  다운로드는 임시 파일 → os.replace · 업로드는 refs/uploads.json sha 캐시.
CLI: 환경변수 HIGGSFIELD(예: "python fake_hf.py")가 있으면 그것, 없으면 PATH의 higgsfield
(윈도우는 .cmd 래퍼가 여러 줄 프롬프트를 깨므로 같은 패키지의 vendor/hf.exe를 직접 부른다).
"""
import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import die, save_atomic, tmpdir, write_atomic  # noqa: E402

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
ROOT = Path.cwd().resolve()
FAILED = {"failed", "error", "canceled", "cancelled", "nsfw"}


def hf_cmd():
    env = os.environ.get("HIGGSFIELD")
    if env:
        return shlex.split(env)  # 경로는 / 로 적는다(윈도우 \ 는 shlex가 지움)
    exe = shutil.which("higgsfield")
    if not exe:
        die("higgsfield CLI를 찾지 못함 — 설치·로그인 후 다시(README 필요한 것)")
    if exe.lower().endswith((".cmd", ".bat")):
        vendor = Path(exe).parent / "node_modules/@higgsfield/cli/vendor/hf.exe"
        if vendor.exists():
            return [str(vendor)]
    return [exe]


def hf(*args, timeout=None):
    r = subprocess.run([*hf_cmd(), *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def parse_json(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def write_json(path, data):
    write_atomic(path, json.dumps(data, ensure_ascii=False, indent=1))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fill(template, values_path):
    """뼈대의 {{칸}}을 값 JSON으로 채운다. 칸만 있는 줄의 값이 빈칸이면 줄째 뺀다(예: 디테일 없음). 채운 결과는 run.json에만 남는다."""
    t = Path(template)
    if not t.exists():
        t = Path(__file__).resolve().parent.parent / "prompts" / template
    if not t.exists():
        die(f"뼈대 없음: {template}")
    try:
        values = json.loads(Path(values_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        die(f"값 파일 {values_path}: {e}")
    lines = []
    for line in t.read_text(encoding="utf-8").splitlines():
        m = re.fullmatch(r"\{\{(\w+)\}\}", line.strip())
        if m and values.get(m.group(1)) == "":
            continue
        for k, v in values.items():
            line = line.replace("{{%s}}" % k, str(v))
        lines.append(line)
    return check_prompt("\n".join(lines), t.name)


def read_prompt(path):
    return check_prompt(Path(path).read_text(encoding="utf-8"), path)


def check_prompt(text, path):
    body = "\n".join(l for l in text.splitlines() if not l.startswith("#")).strip()
    left = re.findall(r"\{\{[^}]*\}\}", body)
    if left:
        die(f"{path}: 안 채운 칸 {sorted(set(left))}")
    return body


def ratio(s):
    w, h = (float(x) for x in s.split(":"))
    return w / h


# ── 업로드 ──────────────────────────────────────────────

def png_copy(src, tmpdir, aspect=None):
    """ASCII 이름의 PNG 임시 사본(CLI는 PNG만·한글 경로 위험). aspect가 다르면 위아래 가장자리 줄을 늘려 덧댐."""
    from PIL import Image
    im = Image.open(src).convert("RGB")
    if aspect and abs(im.width / im.height - ratio(aspect)) > 0.01:
        import numpy as np
        a = np.asarray(im)
        pad = round(im.width / ratio(aspect)) - im.height
        if pad < 0:
            die(f"{src}: --aspect {aspect}보다 세로가 길어 덧댈 수 없음")
        top = pad // 2
        im = Image.fromarray(np.vstack([np.repeat(a[:1], top, 0), a, np.repeat(a[-1:], pad - top, 0)]))
    dst = Path(tmpdir) / f"u{len(list(Path(tmpdir).iterdir()))}.png"
    im.save(dst)
    return dst


def upload(ref, aspect, cache, tmpdir, dry):
    rel = Path(ref).resolve().relative_to(ROOT).as_posix() if Path(ref).resolve().is_relative_to(ROOT) else str(ref)
    key = rel + (f"@{aspect}" if aspect else "")
    digest = sha(ref)
    hit = cache.get(key)
    if hit and hit.get("sha") == digest:
        return rel, digest, hit["id"]
    if dry:
        return rel, digest, f"<upload:{key}>"
    code, out, err = hf("upload", "create", str(png_copy(ref, tmpdir, aspect)), "--json")
    data = parse_json(out)
    uid = (data.get("id") if isinstance(data, dict) else None) or next(iter(UUID.findall(out)), None)
    if code or not uid:
        die(f"업로드 실패 {ref}: {(err or out)[:300]}")
    cache[key] = {"id": uid, "sha": digest, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    return rel, digest, uid


# ── run 폴더 ────────────────────────────────────────────

def all_runs():
    for f in sorted((ROOT / "runs").glob("*/run.json")):
        try:
            yield f.parent, json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue


def new_run_dir(style, key):
    nums = [int(p.name[:3]) for p in (ROOT / "runs").iterdir() if p.name[:3].isdigit()]
    n = max(nums, default=0) + 1
    while True:  # mkdir이 원자적이라 병렬 실행끼리 번호가 겹치지 않음
        d = ROOT / "runs" / f"{n:03d}_{style}_{key}"
        try:
            d.mkdir()
            return f"{n:03d}", d
        except FileExistsError:
            n += 1


def credits_of(text):
    """견적 JSON의 "credits" 키 값만(어느 깊이든 처음 것). 없으면 None — 첫 숫자를 견적으로 잘못 읽지 않게."""
    def walk(x):
        if isinstance(x, dict):
            v = x.get("credits")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return v
            x = list(x.values())
        if isinstance(x, list):
            for v in x:
                got = walk(v)
                if got is not None:
                    return got
        return None

    return walk(parse_json(text))


def download(url, dst):
    part = dst.with_name(dst.name + ".part")
    with urllib.request.urlopen(url, timeout=600) as r, open(part, "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(part, dst)  # 반쯤 받은 파일이 완료로 남지 않음


def compare_sheet(d, run):
    """같은 스타일·키의 직전 이미지 run과 나란히 → compare.jpg (변수 1개 비교용)."""
    from PIL import Image, ImageDraw
    cur = [d / f for f in run["outputs"].values() if f.endswith((".png", ".jpg", ".webp"))]
    if not cur:
        return
    prev = None
    for pd, pr in all_runs():
        if pr.get("no", "") < run["no"] and (pr.get("style"), pr.get("key")) == (run["style"], run["key"]):
            imgs = [pd / f for f in (pr.get("outputs") or {}).values() if f.endswith((".png", ".jpg", ".webp"))]
            if imgs and imgs[0].exists():
                prev = (pr["no"], imgs[0])
    tiles = ([prev] if prev else []) + [(run["no"], cur[0])]
    H = 900
    ims = []
    for no, p in tiles:
        im = Image.open(p).convert("RGB")
        ims.append((no, im.resize((round(im.width * H / im.height), H))))
    sheet = Image.new("RGB", (sum(i.width for _, i in ims) + 10 * (len(ims) - 1), H + 30), "white")
    x, draw = 0, ImageDraw.Draw(sheet)
    for no, im in ims:
        sheet.paste(im, (x, 30))
        draw.text((x + 6, 8), f"run {no}", fill=(180, 0, 0))
        x += im.width + 10
    save_atomic(sheet, d / "compare.jpg", quality=86)


def finish(d, run, timeout):
    """job ID들을 기다려 받는다. 새 결제를 만들지 않는다."""
    path = d / "run.json"
    outputs = {}
    views = run.get("views") or ["out"]
    for i, jid in enumerate(run["job_ids"]):
        code, out, err = hf("generate", "wait", jid, "--quiet", "--json", "--timeout", timeout)
        job = parse_json(out)
        if not isinstance(job, dict):
            _, out2, _ = hf("generate", "get", jid, "--json")
            job = parse_json(out2) if isinstance(parse_json(out2), dict) else {"status": "unknown", "error": (err or out)[:500]}
        if isinstance(job.get("params"), dict):
            job = {k: v for k, v in job.items() if k != "params"}  # 참조 URL 목록은 run.json에 이미 있음
        run["response"] = job
        status = job.get("status")
        if status in FAILED:  # status 필드만 — stderr의 "failed" 글자(재시도 로그 등)로 판단하지 않음
            run["status"] = "failed"
            write_json(path, run)
            die(f"run {run['no']}: job {jid} 실패 — 자동으로 다시 만들지 않음. 다시 하려면 사용자 확인 후 --again")
        url = job.get("result_url")
        if status != "completed" or not url:
            run["status"] = "submitted"
            write_json(path, run)
            die(f"run {run['no']}: job {jid} 아직 안 끝남({status}) — 나중에 `run.py --resume {run['no']}` (새 결제 없음)")
        ext = Path(urllib.request.urlparse(url).path).suffix or ".bin"
        name = f"out{'' if i == 0 else f'_{i + 1}'}{ext}"
        download(url, d / name)
        outputs[views[i] if i < len(views) else f"out{i + 1}"] = name
    run.update(status="completed", outputs=outputs)
    write_json(path, run)
    try:
        compare_sheet(d, run)
    except Exception as e:  # 비교 시트 실패가 결과를 막지 않게
        print(f"run.py: compare.jpg 못 만듦 — {e}", file=sys.stderr)
    print(f"run {run['no']} 완료 → {d.relative_to(ROOT).as_posix()}/ {', '.join(outputs.values())} · 크레딧 {run.get('credits')}")


# ── 메인 ────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("style", nargs="?")
    ap.add_argument("key", nargs="?")
    ap.add_argument("--model", help="job_type (higgsfield model list). 기본값 없음")
    ap.add_argument("--template", help="prompts/ 뼈대 이름(예: shot_front.txt) 또는 경로")
    ap.add_argument("--values", help="칸 값 JSON {칸: 값} — refs/values/<스타일>_<키>.json")
    ap.add_argument("--prompt", help="이미 채운 프롬프트 파일(뼈대가 없는 새 흐름일 때만)")
    ap.add_argument("--image", action="append", default=[], help="참조 이미지(순서 = 프롬프트의 Reference 번호)")
    ap.add_argument("--start-image")
    ap.add_argument("--end-image")
    ap.add_argument("--aspect", help="aspect_ratio. 영상 시작·끝 이미지 비율이 다르면 덧대 올림")
    ap.add_argument("--param", action="append", default=[], help="name=value (예: resolution=4k)")
    ap.add_argument("--views", default="", help="결과 파일 이름표, 쉼표(예: F,B 또는 FB)")
    ap.add_argument("--changed", default="", help="직전 run 대비 바꾼 것 1개")
    ap.add_argument("--step", default="")
    ap.add_argument("--timeout", default="20m")
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--again", action="store_true", help="같은 입력 run이 있어도 새로 생성(사용자 확인 후)")
    ap.add_argument("--resume", metavar="NNN")
    ap.add_argument("--job-id", help="--resume과 함께: create 직후 끊겨 ID가 안 적힌 run에 붙임")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)

    if a.self_test:
        return self_test()
    if not (ROOT / "runs").is_dir():
        die("작업 폴더(runs/가 있는 곳)에서 실행")

    if a.resume:
        hits = [(d, r) for d, r in all_runs() if d.name.startswith(a.resume.zfill(3) + "_")]
        if not hits:
            die(f"run {a.resume} 없음")
        d, run = hits[0]
        if a.job_id:
            run["job_ids"] = [a.job_id]
        if run.get("status") == "completed":
            print(f"run {run['no']} 이미 완료")
            return 0
        if not run.get("job_ids"):
            die(f"run {run['no']}: job ID 없음 — `higgsfield generate list`로 찾아 --job-id로 붙인다")
        finish(d, run, a.timeout)
        return 0

    if not (a.style and a.key and a.model and (a.prompt or (a.template and a.values))):
        die("스타일·키·--model·(--template + --values 또는 --prompt) 필요(모델은 기본값 없음 — SKILL 원칙 \"모델\")")
    if re.search(r"[^A-Za-z0-9-]", a.style + a.key):
        die("스타일·키는 영문·숫자·- 만(폴더 이름이 됨)")
    prompt = fill(a.template, a.values) if a.template else read_prompt(a.prompt)
    params = dict(p.split("=", 1) for p in a.param)
    if a.aspect:
        params["aspect_ratio"] = a.aspect
    video = bool(a.start_image or a.end_image)

    cache_path = ROOT / "refs/uploads.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    refs, media = [], []
    with tmpdir() as tmp:  # 실행마다 고유 임시 폴더
        for role, files in (("image", a.image), ("start-image", [a.start_image]), ("end-image", [a.end_image])):
            for f in files:
                if not f:
                    continue
                if not Path(f).exists():
                    die(f"참조 없음: {f}")
                rel, digest, uid = upload(f, a.aspect if role != "image" else None, cache, tmp, a.dry or a.estimate)
                refs.append({"role": role, "file": rel, "sha": digest, "id": uid})
                media += [f"--{role}", uid]
        if not (a.dry or a.estimate):
            # shortcut: 병렬 run끼리 uploads.json을 동시에 쓰면 한쪽 기록이 빠질 수 있음 → 다음에 한 번 더 올릴 뿐
            cache_path.parent.mkdir(exist_ok=True)
            write_json(cache_path, cache)

    flags = [x for k, v in params.items() for x in (f"--{k}", v)]
    sig = hashlib.sha256(json.dumps([a.model, prompt, [(r["role"], r["sha"]) for r in refs], params],
                                    ensure_ascii=False).encode()).hexdigest()[:16]
    create_args = ["generate", "create", a.model, "--prompt", prompt, *media, *flags, "--json"]

    if a.dry:
        print("할 일(--dry, CLI 안 부름):")
        print("  " + " ".join(shlex.quote(x) for x in create_args[:4]) + " <프롬프트 %d자> " % len(prompt)
              + " ".join(media + flags))
        return 0

    # 견적은 업로드 없이(참조는 빼고) — 견적만 보려고 바이어 이미지를 올리지 않는다
    code, out, err = hf("generate", "cost", a.model, "--prompt", prompt, *([] if a.estimate else media), *flags, "--json")
    credits = credits_of(out) if code == 0 else None
    if a.estimate:
        print(f"견적: {a.model} {credits if credits is not None else '?'} 크레딧" + ("" if credits is not None else f" — {(err or out)[:200]}"))
        return 0 if credits is not None else 1
    if credits is None:  # 견적을 모르면 결제하지 않는다
        die(f"견적 실패 — create 안 함: {(err or out)[:300]}")

    if not a.again:
        for d, r in all_runs():
            if r.get("sig") != sig:
                continue
            st = r.get("status")
            if st == "completed":
                print(f"같은 입력의 run {r['no']}이 이미 있음 — 건너뜀(다시 하려면 사용자 확인 후 --again)")
                return 0
            die(f"같은 입력의 run {r['no']}이 {st} 상태 — " +
                (f"`run.py --resume {r['no']}`" if st != "failed" else "실패 기록, 다시 하려면 사용자 확인 후 --again"))

    no, d = new_run_dir(a.style, a.key)
    run = {"no": no, "style": a.style, "key": a.key, "step": a.step, "model": a.model,
           "kind": "video" if video else "image", "template": a.template or "", "values_file": Path(a.values).as_posix() if a.values else "",
           "prompt_file": Path(a.prompt).as_posix() if a.prompt else "", "prompt": prompt,
           "refs": refs, "params": params, "views": [v for v in a.views.split(",") if v], "sig": sig,
           "credits": credits, "changed": a.changed, "verdict": "", "memo": "",
           "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "status": "creating", "job_ids": []}
    if video and a.aspect:
        from PIL import Image
        w, h = Image.open(a.start_image or a.end_image).size
        run["crop_to"] = f"{w}:{h}"  # video_post.py가 덧댄 만큼 도로 잘라냄
    write_json(d / "run.json", run)  # create 전에 남김 — 끊겨도 흔적이 있음

    code, out, err = hf(*create_args)
    data = parse_json(out)
    ids = [x for x in (data if isinstance(data, list) else [data]) if isinstance(x, str)] if data is not None else []
    if isinstance(data, dict):
        ids = [data.get("id")] if data.get("id") else []
    ids = ids or UUID.findall(out)
    if ids:  # 종료 코드와 무관하게 먼저 저장 — 결제됐을 수 있는 job을 잃지 않음. 끊겨도 --resume으로 새 결제 없이 받음
        run.update(job_ids=ids, status="submitted")
        write_json(d / "run.json", run)
    if code:
        run["response"] = {"error": (err or out)[:500]}
        if not ids:
            run["status"] = "create_failed"
        write_json(d / "run.json", run)
        die(f"run {no}: create 종료 코드 {code} — {(err or out)[:300]}" +
            (f"\n  job ID는 저장됨 → `run.py --resume {no}` (다시 create하지 않음)" if ids else ""))
    if not ids:
        run.update(status="create_failed", response={"error": (err or out)[:500]})
        write_json(d / "run.json", run)
        die(f"run {no}: create 출력에 job ID 없음 — `higgsfield generate list`로 확인 후 --resume {no} --job-id ID")
    finish(d, run, a.timeout)
    return 0


# ── 자체 시험 (가짜 CLI, 0 크레딧) ──────────────────────

FAKE = r'''
import json, sys, os, pathlib
log = pathlib.Path(os.environ["FAKE_LOG"]); a = sys.argv[1:]
log.open("a").write(" ".join(a[:3]) + "\n")
mode = os.environ.get("FAKE_MODE", "ok")
if a[:2] == ["upload", "create"]:
    print(json.dumps({"id": "11111111-1111-1111-1111-%012d" % len(log.read_text().splitlines())}))
elif a[:2] == ["generate", "cost"]:
    if mode == "costfail":
        print("Error: unknown model", file=sys.stderr); sys.exit(1)
    print(json.dumps({"version": 2, "model": {"credits": 7}}))  # 첫 숫자(2)가 아니라 credits 키
elif a[:2] == ["generate", "create"]:
    print(json.dumps(["22222222-2222-2222-2222-222222222222"]))
    if mode == "createfail":
        print("Error: connection reset", file=sys.stderr); sys.exit(1)
elif a[:2] in (["generate", "wait"], ["generate", "get"]):
    if mode == "fail":
        print(json.dumps({"id": a[2], "status": "failed"})); sys.exit(1)
    if mode == "warn":
        print("1 upload attempt failed, retried", file=sys.stderr)  # status는 completed — 실패로 보면 안 됨
    if mode == "slow":
        print(json.dumps({"id": a[2], "status": "in_progress"})); sys.exit(1)
    print(json.dumps({"id": a[2], "status": "completed", "result_url": pathlib.Path(os.environ["FAKE_PNG"]).as_uri()}))
'''


def self_test():
    global ROOT
    from PIL import Image
    with tmpdir() as t:  # 실패로 cwd가 남아도 정리 오류는 무시
        t = Path(t) / "작업 폴더"  # 한글·공백 경로
        (t / "runs").mkdir(parents=True)
        (t / "refs").mkdir()
        Image.new("RGB", (40, 60), "gray").save(t / "refs/a.png")
        Image.new("RGB", (40, 60), "red").save(t / "result.png")
        (t / "p.txt").write_text("# 설명 줄\nphoto of {{X}}", encoding="utf-8")
        (t / "fake_hf.py").write_text(FAKE, encoding="utf-8")
        os.environ.update(HIGGSFIELD=f'"{Path(sys.executable).as_posix()}" "{(t / "fake_hf.py").as_posix()}"', FAKE_LOG=str(t / "log.txt"),
                          FAKE_PNG=str(t / "result.png"), FAKE_MODE="ok")
        ROOT = t.resolve()
        os.chdir(t)
        calls = lambda w: sum(l.startswith(w) for l in (t / "log.txt").read_text().splitlines()) if (t / "log.txt").exists() else 0
        args = ["WT", "base", "--model", "m", "--prompt", "p.txt", "--image", "refs/a.png", "--views", "FB"]

        try:
            main(args)
            raise AssertionError("안 채운 칸을 막지 못함")
        except SystemExit as e:
            assert e.code == 1
        (t / "p.txt").write_text("# 설명 줄\nphoto", encoding="utf-8")

        (t / "refs/values").mkdir()
        (t / "tpl.txt").write_text("# 주석\nphoto of {{A}}\n{{D}}\nend", encoding="utf-8")
        (t / "refs/values/WT_x.json").write_text(json.dumps({"A": "a dress", "D": ""}), encoding="utf-8")
        assert fill(t / "tpl.txt", t / "refs/values/WT_x.json") == "photo of a dress\nend"  # 빈 칸 줄은 빠짐
        main(args)  # 정상 1회
        r = json.loads((t / "runs/001_WT_base/run.json").read_text(encoding="utf-8"))
        assert r["status"] == "completed" and r["outputs"] == {"FB": "out.png"} and r["credits"] == 7, r
        assert r["prompt"] == "photo" and (t / "runs/001_WT_base/out.png").exists()
        assert calls("upload") == 1 and calls("generate create") == 1

        main(args)  # 같은 입력 → 건너뜀, 업로드·생성 0
        assert calls("upload") == 1 and calls("generate create") == 1 and not (t / "runs/002_WT_base").exists()

        os.environ["FAKE_MODE"] = "slow"  # 기다리다 끊김 → ID는 남고 --resume은 create를 다시 안 부름
        try:
            main(args + ["--changed", "x", "--param", "resolution=4k"])
        except SystemExit as e:
            assert e.code == 1
        r = json.loads((t / "runs/002_WT_base/run.json").read_text(encoding="utf-8"))
        assert r["status"] == "submitted" and r["job_ids"], r
        try:
            main(args + ["--param", "resolution=4k"])  # 같은 입력 재실행 → 결제 대신 resume 안내
        except SystemExit as e:
            assert e.code == 1
        assert calls("generate create") == 2
        os.environ["FAKE_MODE"] = "ok"
        main(["--resume", "002"])
        assert calls("generate create") == 2
        assert json.loads((t / "runs/002_WT_base/run.json").read_text(encoding="utf-8"))["status"] == "completed"
        assert (t / "runs/002_WT_base/compare.jpg").exists()

        os.environ["FAKE_MODE"] = "fail"  # 실패 → 종료 1, 자동 재생성 없음
        try:
            main(args + ["--param", "resolution=2k"])
        except SystemExit as e:
            assert e.code == 1
        assert calls("generate create") == 3
        try:
            main(args + ["--param", "resolution=2k"])  # 실패 기록이 있으면 --again 없이는 안 만듦
        except SystemExit as e:
            assert e.code == 1
        assert calls("generate create") == 3
        assert not list(t.glob("runs/*/*.part"))

        os.environ["FAKE_MODE"] = "createfail"  # create가 ID를 찍고 종료 1 → ID 저장, 재실행해도 create 안 부름
        try:
            main(args + ["--param", "resolution=1k"])
        except SystemExit as e:
            assert e.code == 1
        r = json.loads(next(t.glob("runs/004_*/run.json")).read_text(encoding="utf-8"))
        assert r["job_ids"] == ["22222222-2222-2222-2222-222222222222"] and r["status"] == "submitted", r
        try:
            main(args + ["--param", "resolution=1k"])
        except SystemExit as e:
            assert e.code == 1
        assert calls("generate create") == 4

        os.environ["FAKE_MODE"] = "warn"  # stderr의 "failed" 글자는 실패가 아님
        main(["--resume", "004"])
        assert json.loads(next(t.glob("runs/004_*/run.json")).read_text(encoding="utf-8"))["status"] == "completed"

        os.environ["FAKE_MODE"] = "costfail"  # 견적 실패 → create 안 함, run 폴더도 안 만듦
        try:
            main(args + ["--param", "resolution=8k"])
        except SystemExit as e:
            assert e.code == 1
        assert calls("generate create") == 4 and not list(t.glob("runs/005_*"))

        os.environ["FAKE_MODE"] = "ok"  # --end-image만 있어도 crop_to
        main(["WT", "o1-mo", "--model", "v", "--prompt", "p.txt", "--end-image", "refs/a.png", "--aspect", "9:16"])
        r = json.loads(next(t.glob("runs/005_*/run.json")).read_text(encoding="utf-8"))
        assert r["kind"] == "video" and r.get("crop_to") == "40:60", r
        os.chdir(Path(t).parent.parent)
    print("self-test 통과 — 정상 생성 · 같은 입력 건너뜀 · 끊김 후 resume(재결제 0) · 실패 시 재생성 안 함 · 업로드 캐시"
          " · create ID+종료1 → ID 저장·재create 0 · stderr 'failed' 오탐 없음 · 견적 credits 키·실패 시 create 안 함 · --end-image만 crop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
