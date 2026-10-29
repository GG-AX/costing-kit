"""컷이 기준 컷에서 「옷 안쪽만」 바뀌었는지 본다.

뷰마다 솔리드 기준 컷 1장(사람·포즈·실루엣 고정) → 그 위에 아트웍만 입힌 컷을 대조.
기준과 달라진 화소를 빨갛게 칠하고, 옷이 없는 띠(머리·발·좌우 여백)의 변화 비율을 잰다.
띠 변화가 --pass(1%) 이상이면 실루엣·사람이 흔들린 것 → 「확인」, 종료 코드 1.

    python diff_check.py <기준.png> <결과.png> [...] [--out work/diff]
    → <out>/<상위폴더>_<이름>.jpg + 수치
"""
import argparse
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import save_atomic  # noqa: E402


def compare(base, result, a):
    base, result = Path(base), Path(result)
    x = np.asarray(Image.open(base).convert("RGB")).astype(int)
    y = np.asarray(Image.open(result).convert("RGB").resize((x.shape[1], x.shape[0]))).astype(int)
    d = (np.abs(x - y).max(-1) > a.thr).astype(np.uint8)
    d = cv2.morphologyEx(d, cv2.MORPH_OPEN, np.ones((a.open, a.open), np.uint8))
    h, w = d.shape
    # 옷이 없는 띠: 머리(위) · 발(아래) · 좌우 여백 — 여기서 바뀐 비율은 0 에 가까워야 한다
    head = d[: int(h * a.head)].mean()
    foot = d[int(h * (1 - a.foot)):].mean()
    side = np.concatenate([d[:, : int(w * a.side)], d[:, int(w * (1 - a.side)):]], 1).mean()
    if w / h > a.wide:     # 앞뒤 한 장(4:3) — 두 사람 사이 가운데 여백도 본다
        side = max(side, d[:, int(w * (0.5 - a.mid)): int(w * (0.5 + a.mid))].mean())
    v = x.astype(float).copy()
    v[d > 0] = v[d > 0] * 0.4 + np.array([255, 0, 0]) * 0.6
    # runs/NNN_*/out.png 처럼 이름이 겹치므로 상위 폴더 이름을 붙인다
    out = Path(a.out) / ("%s_%s.jpg" % (result.resolve().parent.name, result.stem))
    save_atomic(Image.fromarray(v.astype(np.uint8)).resize((w // 2, h // 2)), out, quality=a.quality)
    return head, foot, side, out


def run(a):
    bad = 0
    for p in a.results:
        head, foot, side, out = compare(a.base, p, a)
        ok = max(head, foot, side) < a.pass_
        bad += not ok
        print("%-4s %s  머리 %.3f · 발 %.3f · 좌우여백 %.3f  → %s"
              % ("OK" if ok else "확인", Path(p).name, head, foot, side, out))
    return 1 if bad else 0


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", nargs="?", help="기준 컷")
    ap.add_argument("results", nargs="*", help="대조할 컷")
    ap.add_argument("--out", default="work/diff", help="대조 그림 폴더 (기본 work/diff)")
    ap.add_argument("--thr", type=int, default=28, help="바뀐 화소로 볼 채널 차 (0-255)")
    ap.add_argument("--open", type=int, default=5, help="잡티 제거 열림 커널 크기")
    ap.add_argument("--head", type=float, default=0.12, help="머리 띠 (위 비율)")
    ap.add_argument("--foot", type=float, default=0.07, help="발 띠 (아래 비율)")
    ap.add_argument("--side", type=float, default=0.15, help="좌우 여백 띠 (각 비율)")
    ap.add_argument("--wide", type=float, default=1.2, help="가로/세로가 이보다 크면 앞뒤 한 장으로 보고 가운데도 본다")
    ap.add_argument("--mid", type=float, default=0.04, help="가운데 여백 띠 반폭 (0.46~0.54)")
    ap.add_argument("--pass", dest="pass_", metavar="PASS", type=float, default=0.01, help="통과 기준: 띠 변화 비율 < 이 값")
    ap.add_argument("--quality", type=int, default=85, help="대조 JPEG 품질")
    ap.add_argument("--self-test", action="store_true", help="합성 이미지로 자체 점검")
    return ap


def self_test():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "테스트"
        d.mkdir()
        x = np.full((600, 400, 3), 220, np.uint8)
        x[120:540, 120:280] = (60, 90, 160)                     # 옷
        Image.fromarray(x).save(d / "기준.png")
        y = x.copy(); y[250:350, 150:250] = (200, 40, 40)       # 옷 안쪽만 바뀜
        Image.fromarray(y).save(d / "옷만.png")
        z = x.copy(); z[10:60, 170:230] = (20, 20, 20)          # 머리 띠가 바뀜
        Image.fromarray(z).save(d / "머리 바뀜.png")
        a = parser().parse_args([str(d / "기준.png"), str(d / "옷만.png"), "--out", str(d / "대조")])
        assert run(a) == 0
        h, f, s, out = compare(d / "기준.png", d / "머리 바뀜.png", a)
        assert h > 0.01 and f == 0 and s == 0, (h, f, s)
        assert Image.open(out).size == (200, 300)
        a.results = [str(d / "옷만.png"), str(d / "머리 바뀜.png")]
        assert run(a) == 1
    print("self-test OK")


if __name__ == "__main__":
    a = parser().parse_args()
    if a.self_test:
        self_test()
        sys.exit(0)
    if not a.base or not a.results:
        parser().error("<기준.png> <결과.png> ... 가 필요하다")
    sys.exit(run(a))
