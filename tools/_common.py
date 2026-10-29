"""도구 공통 — stdout UTF-8 · 원자적 쓰기(OneDrive: 임시 파일 → os.replace) · die · 임시 폴더(py3.9 호환).

각 도구 맨 위:  sys.path.insert(0, str(Path(__file__).resolve().parent)); from _common import ...
(python -I·-P처럼 스크립트 폴더가 sys.path에 안 들어가는 실행에서도 import되게)
"""
import contextlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # 한국어 윈도우 콘솔(cp949)에서 — 등 출력 오류 방지
    except AttributeError:
        pass


def die(msg, code=1):
    print(f"{Path(sys.argv[0]).name}: {msg}", file=sys.stderr)
    sys.exit(code)


def _atomic(path, write):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=path.suffix, dir=path.parent)  # 같은 폴더 = 같은 드라이브
    os.close(fd)
    try:
        write(tmp)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_atomic(path, data):
    """str이면 UTF-8·\\n, bytes면 그대로."""
    if isinstance(data, str):
        _atomic(path, lambda t: Path(t).write_text(data, encoding="utf-8", newline="\n"))
    else:
        _atomic(path, lambda t: Path(t).write_bytes(data))


def save_atomic(img, path, **kw):
    """PIL 이미지 저장. 형식은 확장자로(임시 파일도 같은 확장자)."""
    _atomic(path, lambda t: img.save(t, **kw))


@contextlib.contextmanager
def tmpdir():
    """TemporaryDirectory(ignore_cleanup_errors=True) 대신(py3.9엔 없음) — 윈도우에서 cwd·열린 파일로 못 지워도 실패하지 않음."""
    d = tempfile.mkdtemp()
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)
