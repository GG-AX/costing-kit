"""작업 폴더 훅: run.py가 돈 뒤 log.md와 README 3절(현황)을 runs/*/run.json에서 다시 쓴다.

훅 호출(stdin에 Claude Code PostToolUse JSON): 셸 명령에 run.py가 있거나, Edit/Write로 runs/*/run.json을 고쳤을 때만
(verdict·memo를 손으로 고쳐도 현황이 따라옴). 그 밖에는 아무것도 안 함.
직접 호출: python log_hook.py <작업 폴더>   (lint.py도 rebuild()를 쓴다)

run.json에서 읽는 칸: no, style, key, model, credits, outputs{보기: 파일}, changed, verdict(후보|확정|폐기|""), memo
"""
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import write_atomic  # noqa: E402

BEGIN = "<!-- status:begin — tools/log_hook.py가 다시 씀. 손대지 않음 -->"
END = "<!-- status:end -->"
VERDICTS = ("후보", "확정", "폐기")


def cell(v):
    return str(v if v not in (None, "") else "-").replace("|", "\\|").replace("\n", " ")


def num(v):
    return f"{v:g}" if isinstance(v, (int, float)) else "?"


def load_runs(root):
    runs = []
    for f in sorted((root / "runs").glob("*/run.json")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            r = {"memo": f"run.json 읽기 실패: {e}"}
        r.setdefault("no", f.parent.name.split("_")[0])
        runs.append(r)
    return runs


def log_md(runs):
    lines = [
        "# log",
        "",
        "> 작업 기록. `tools/log_hook.py`가 `runs/*/run.json`에서 다시 쓴다 — 사람·에이전트는 고치지 않는다(고칠 것은 run.json에).",
        "",
        "| # | 스타일 | 키 | 모델 | 크레딧 | 바꾼 것(직전 대비 1개) | 결과 → 원인 | 판정 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in runs:
        v = r.get("verdict") or "미판정"
        lines.append("| " + " | ".join(cell(x) for x in (
            r["no"], r.get("style"), r.get("key"), r.get("model"), num(r.get("credits")),
            r.get("changed"), r.get("memo"), f"**{v}**" if v == "확정" else v)) + " |")
    return "\n".join(lines) + "\n"


def status_block(runs, readme_text):
    final = [r for r in runs if r.get("verdict") == "확정"]
    views = sorted({k for r in runs for k in (r.get("outputs") or {})}, key=lambda k: (k not in ("F", "B"), k))
    rows = list(dict.fromkeys((r.get("style"), r.get("key")) for r in runs if r.get("style")))
    out = [BEGIN, ""]
    if rows and views:
        out += ["| 스타일 | 키 | " + " | ".join(views) + " |", "| --- | --- | " + " | ".join("---" for _ in views) + " |"]
        for s, k in rows:
            got = [", ".join(r["no"] for r in final if (r.get("style"), r.get("key")) == (s, k) and v in (r.get("outputs") or {}))
                   for v in views]
            out.append(f"| {cell(s)} | {cell(k)} | " + " | ".join(g or " " for g in got) + " |")
        out.append("")
        out.append("(칸 = 확정 run 번호, 빈 칸 = 남은 일)")
    else:
        out.append("(아직 run 없음)")
    count = {v: sum(r.get("verdict") == v for r in runs) for v in VERDICTS}
    undecided = sum(r.get("verdict") not in VERDICTS for r in runs)
    m = re.search(r"승인 견적\(크레딧\):[^\n\d]*(\d+(?:\.\d+)?)", readme_text)  # 줄의 첫 숫자 = 누적 승인 합계
    spent = sum(r["credits"] for r in runs if isinstance(r.get("credits"), (int, float)))
    out += ["",
            f"- 판정: " + " · ".join(f"{v} {n}" for v, n in count.items()) + f" · 미판정 {undecided} (run {len(runs)}개)",
            f"- 크레딧: {spent:g} / 견적 {m.group(1) if m else '미승인'}",
            "", END]
    return "\n".join(out)


def rebuild(root):
    root = Path(root)
    runs = load_runs(root)
    write_atomic(root / "log.md", log_md(runs))
    readme = root / "README.md"
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        if BEGIN in text and END in text:
            head, rest = text.split(BEGIN, 1)
            text = head + status_block(runs, text) + rest.split(END, 1)[1]
            write_atomic(readme, text)
        else:
            print("log_hook: README.md에 현황 표시줄(status:begin/end)이 없어 3절을 건너뜀", file=sys.stderr)
    return runs


def touches_runs(event):
    """다시 쓸 일인가: 셸 명령에 run.py · Edit/Write 대상이 runs/<run>/run.json."""
    ti = event.get("tool_input") or {}
    if event.get("tool_name") in ("Edit", "Write", "MultiEdit"):
        parts = Path(str(ti.get("file_path", "")).replace("\\", "/")).parts
        return len(parts) >= 3 and parts[-1] == "run.json" and parts[-3] == "runs"
    return "run.py" in str(ti.get("command", ""))


def main(stdin=None):
    if len(sys.argv) > 1 and sys.argv[1] != "--self-test":
        rebuild(sys.argv[1])
        return
    try:
        event = json.load(stdin or sys.stdin)
    except ValueError:
        return
    if not isinstance(event, dict) or not touches_runs(event):
        return
    root = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd")
    # 플러그인 훅이라 모든 프로젝트에서 불린다 — README에 현황 표시줄이 있는 코스팅 작업 폴더만
    readme = Path(root or ".") / "README.md"
    if root and (Path(root) / "runs").is_dir() and readme.is_file() and BEGIN in readme.read_text(encoding="utf-8", errors="replace"):
        rebuild(root)


def self_test():
    """가짜 훅 stdin 2종(Bash로 run.py · Edit로 run.json) → log.md가 다시 쓰이고, 무관한 Edit는 무시."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t, "작업 폴더")
        (t / "runs/001_S_base").mkdir(parents=True)
        rj = t / "runs/001_S_base/run.json"
        rj.write_text(json.dumps({"no": "001", "style": "S", "key": "base", "verdict": "후보"}), encoding="utf-8")
        (t / "README.md").write_text(f"x\n{BEGIN}\n{END}\n", encoding="utf-8")
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        feed = lambda ev: main(io.StringIO(json.dumps(ev)))
        feed({"tool_name": "Bash", "cwd": str(t), "tool_input": {"command": "python3 ~/x/tools/run.py S base --model m"}})
        assert "후보" in (t / "log.md").read_text(encoding="utf-8")
        rj.write_text(json.dumps({"no": "001", "style": "S", "key": "base", "verdict": "확정"}), encoding="utf-8")
        feed({"tool_name": "Edit", "cwd": str(t), "tool_input": {"file_path": str(t / "runs/001_S_base/run.json")}})
        assert "**확정**" in (t / "log.md").read_text(encoding="utf-8")
        assert "확정 1" in (t / "README.md").read_text(encoding="utf-8")
        (t / "log.md").unlink()
        feed({"tool_name": "Write", "cwd": str(t), "tool_input": {"file_path": str(t / "README.md")}})
        feed({"tool_name": "Bash", "cwd": str(t), "tool_input": {"command": "ls runs"}})
        assert not (t / "log.md").exists(), "무관한 도구 호출에 다시 씀"
        assert touches_runs({"tool_name": "Write", "tool_input": {"file_path": "C:\\w\\runs\\002_S_o1\\run.json"}})
        (t / "README.md").write_text("다른 프로젝트\n", encoding="utf-8")  # runs/가 있어도 표시줄이 없으면 남의 폴더
        feed({"tool_name": "Bash", "cwd": str(t), "tool_input": {"command": "python run.py"}})
        assert not (t / "log.md").exists(), "코스팅 작업 폴더가 아닌데 다시 씀"
    print("self-test 통과 — Bash run.py · Edit run.json에 다시 씀, 무관한 호출·남의 폴더는 무시")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        main()

