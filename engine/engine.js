/* costing-kit 화면 엔진 v2.3 — 고치지 않는다. 내용은 board/data.js(window.BOARD), 미디어는 window.M(경로 → data URI).
   single_file.py가 두 판을 만든다: window.COMPARE = "motion"(턴 영상 동기) | "still"(양쪽 정지 컷, 영상 없음).
   미디어 이름(board/media/ 기준) — 키 = base | o1 | o13 …(정렬된 옵션 번호):
     정지  img/<c>_<키>_F.jpg · _B.jpg     키는 그 면에 보이는 옵션만(view)
     턴    video/<c>_<키>_loop.mp4         키는 켠 옵션 전체. 한 스타일 안 길이가 같아야 두 칸이 맞는다
     모션  video/<c>_m_<F|B>_<from>_<to>.mp4   켤 때 한 번(to = from + 옵션 1개). 끌 때는 블러 전환
     칩    chips/<c>.jpg (없으면 hex)    디테일  data.js o[].detail.before/after(또는 한 장 img)
   캡처: ?shot#s=<스타일>&o=<옵션 번호들, 예 13 · 0=기본>&b=<1=뒤> — 전환 없이, 영상 대신 정지 컷으로 그린다. */
(function () {
  "use strict";
  const B = window.BOARD || {}, S = B.styles || [], $ = id => document.getElementById(id);
  const M = window.M || {}, U = p => M[p] || "", has = p => p in M;
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const MULTI = B.select === "multi";
  const SHOT = /[?&]shot\b/.test(location.search);
  const STILL = SHOT || window.COMPARE === "still";
  const usd = v => "$" + Math.abs(v).toFixed(st().decimals != null ? st().decimals : B.decimals != null ? B.decimals : 2);
  if (SHOT) document.body.classList.add("noanim");

  function fit() { $("fit").style.transform = "scale(" + Math.min(innerWidth / 1920, innerHeight / 1080) + ")"; }
  addEventListener("resize", fit); fit();

  // 머리말 — 전부 data.js에서
  document.title = B.title || "Costing Option Review";
  const br = B.brand || {};
  function brand(logo) {  // 스타일마다 브랜드가 다르면 styles[].logo
    const html = logo && has(logo)
      ? '<img class="brandlogo" src="' + U(logo) + '" alt="' + esc(br.text) + '"' + (br.h ? ' style="height:' + (+br.h) + 'px"' : "") + ">"
      : '<div class="brandname">' + esc(br.text) + "</div>";
    if ($("brand").innerHTML !== html) $("brand").innerHTML = html;
  }
  if (br.h > 50) $("brand").parentNode.classList.add("wide");
  $("sub").textContent = B.sub || "";
  if (B.creditLogo && has(B.creditLogo)) $("rt").innerHTML = '<img class="creditlogo" src="' + U(B.creditLogo) + '" alt="">';
  $("credit").textContent = B.credit || "";
  $("hint").textContent = MULTI ? "Select any combination" : "Select one option";
  $("optsRow").classList.toggle("one", !MULTI);

  let si = 0, on = [], back = false, wait = false, motion = null, shown = 0;
  const st = () => S[si];
  const key = list => list.length ? "o" + list.slice().sort((a, b) => a - b).map(i => i + 1).join("") : "base";
  const faceKey = (list, side) => key(list.filter(i => st().o[i].view.includes(side)));
  const still = (list, side) => "img/" + st().c + "_" + faceKey(list, side) + "_" + side + ".jpg";
  const loop = list => "video/" + st().c + "_" + key(list) + "_loop.mp4";
  const mot = (side, from, to) => "video/" + st().c + "_m_" + side + "_" + faceKey(from, side) + "_" + faceKey(to, side) + ".mp4";
  const side = () => back ? "B" : "F";

  // 돈 — money:"save"면 옵션별 save(달러), "cost"면 스타일 k.fc − 옵션 k.fc, ""면 금액 없음. 모르면 null → "Not set".
  // 자릿수 = styles[].decimals → decimals → 2
  const saving = o => B.money === "save" ? (typeof o.save === "number" ? o.save : null)
    : B.money === "cost" ? (st().k && o.k && typeof o.k.fc === "number" ? st().k.fc - o.k.fc : null) : null;
  const visible = () => st().o.map((o, i) => i).filter(i => !st().o[i].hidden);

  // 스타일 격자 — 컬러 변형(g가 같은 것)은 한 칸, 컬러는 칩으로 고른다
  const groups = [];
  S.forEach((s, i) => { const g = s.g || s.c, f = groups.find(x => x.g === g); f ? f.items.push(i) : groups.push({g, items: [i]}); });
  document.documentElement.style.setProperty("--cols", B.cols || 2);
  function pick(i) { closeDetail(); si = i; on = []; back = false; wait = false; motion = null; shown = 0; render(); }
  groups.forEach(gr => {
    const s = S[gr.items[0]], b = document.createElement("button");
    b.className = "sty"; b.type = "button"; b.dataset.g = gr.g;
    b.innerHTML = "<b>" + esc(s.d || s.c) + "</b><small>" + esc(s.n) + "</small>";
    b.onclick = () => pick(gr.items[0]);
    $("grid").appendChild(b);
  });

  // 레이어 — 새 레이어를 얹고 블러 페이드로 넘긴 뒤 옛것을 치운다. 같은 내용이면 아무것도 안 한다
  const last = {};
  function swap(id, html) {
    if (last[id] === html) return false;
    last[id] = html;
    const fr = $(id), old = fr.querySelector(".layer.on"), nw = document.createElement("div");
    nw.className = "layer"; nw.innerHTML = html; fr.appendChild(nw);
    void nw.offsetHeight;  // rAF는 탭이 안 그려질 때 멈춘다 — 리플로우로 전이 시작점만 만든다
    nw.classList.add("on");
    if (old) { old.classList.remove("on"); old.classList.add("out"); setTimeout(() => old.remove(), SHOT ? 0 : 700); }
    return true;
  }
  const img = p => '<img src="' + U(p) + '" alt="">';
  // poster = 그 영상의 첫 장면과 같은 정지 컷. 없으면 디코딩 전까지 칸이 비어 바탕과 어긋난 사각 테두리가 보였다(10/29)
  const vid = (p, attrs, poster) => '<video src="' + U(p) + '"' + (poster && has(poster) ? ' poster="' + U(poster) + '"' : "") +
    " muted playsinline " + attrs + "></video>";
  const pending = t => '<div class="pending"><b>In production</b>' + esc(t) + "</div>";

  // 두 칸 턴 영상을 0초에서 같이 출발 — 0.12초 넘게 어긋나면 옵션 쪽을 오리지널 시각에 붙인다
  let syncGen = 0;
  function playTogether() {
    const gen = ++syncGen, a = $("orig").querySelector(".layer.on video"), b = $("frame").querySelector(".layer.on video");
    if (!a || !b) return;
    const ready = v => v.readyState >= 3 ? Promise.resolve() : new Promise(r => { v.addEventListener("canplay", r, {once: true}); setTimeout(r, 3000); });
    Promise.all([ready(a), ready(b)]).then(() => {
      if (gen !== syncGen) return;
      a.currentTime = 0; b.currentTime = 0; a.play().catch(() => {}); b.play().catch(() => {});
      a.ontimeupdate = () => {
        if (gen !== syncGen || b.paused) return;
        const D = a.duration || 6.5; let d = b.currentTime - a.currentTime;
        if (d > D / 2) d -= D; if (d < -D / 2) d += D;   // 한쪽만 먼저 처음으로 돌아간 순간은 어긋남이 아니다
        if (Math.abs(d) > 0.12) b.currentTime = a.currentTime;
      };
    });
  }

  function countTo(v) {
    const el = $("total"), from = shown, t0 = performance.now(), gen = ++countTo.g;
    const put = n => { el.textContent = n === 0 ? "—" : "-" + usd(n); };
    if (v === null) { el.classList.add("zero"); el.textContent = "Not set"; shown = 0; return; }
    el.classList.toggle("zero", v === 0);
    // 안 그려지는 탭에서는 rAF가 멈춘다 — 세지 말고 바로 박는다
    if (SHOT || document.visibilityState !== "visible") { put(v); shown = v; return; }
    (function step(t) {
      if (gen !== countTo.g) return;
      const p = Math.min(1, (t - t0) / 420), n = from + (v - from) * (1 - Math.pow(1 - p, 3));
      put(p < 1 ? n : v); if (p < 1) requestAnimationFrame(step); else shown = v;
    })(t0);
    setTimeout(() => { if (gen === countTo.g && shown !== v) { put(v); shown = v; } }, 700);
  }
  countTo.g = 0;

  // 지폐 — 애니메이션 끝 이벤트는 안 그려지는 동안 오지 않는다, 시간 백스톱을 같이 건다
  function kill(el, ms) { el.addEventListener("animationend", () => el.remove()); setTimeout(() => el.remove(), ms + 400); }
  function where(el) {  // offset으로 잰다 — 칸이 transform으로 움직이는 중이어도 도착 자리를 잡는다
    const stage = document.querySelector(".stage"); let x = 0, y = 0, e = el;
    while (e && e !== stage) { x += e.offsetLeft; y += e.offsetTop; e = e.offsetParent; }
    return {x: x + el.offsetWidth / 2, y: y + el.offsetHeight / 2, w: el.offsetWidth, h: el.offsetHeight};
  }
  function bills() {
    if (SHOT || !B.money) return;
    const fx = $("fx"), to = where($("total")), from = where($("frame")), n = 5;
    for (let k = 0; k < n; k++) {
      const b = document.createElement("div"), dur = 900 + Math.random() * 260;
      const sx = from.x - from.w * .3 + Math.random() * from.w * .6, sy = from.y - from.h * .28 + Math.random() * from.h * .34;
      b.className = "bill"; b.style.left = sx + "px"; b.style.top = sy + "px";
      b.style.setProperty("--dx", (to.x - sx).toFixed(0) + "px"); b.style.setProperty("--dy", (to.y - sy).toFixed(0) + "px");
      b.style.setProperty("--r0", (Math.random() * 24 - 12).toFixed(0) + "deg"); b.style.setProperty("--r1", (Math.random() * 16 - 8).toFixed(0) + "deg");
      b.style.animation = "billin " + dur + "ms cubic-bezier(.3,.5,.2,1) " + k * 70 + "ms both";
      kill(b, dur + k * 70); fx.appendChild(b);
    }
    const p = document.createElement("div");
    p.className = "pot"; p.innerHTML = "<span>SAVED</span><b>+</b>";
    p.style.left = to.x + "px"; p.style.bottom = (fx.clientHeight - to.y + 40) + "px";
    p.style.animation = "potpop 1200ms ease-out " + (n * 70 + 180) + "ms both";
    kill(p, 1200 + n * 70 + 180); fx.appendChild(p);
  }

  // 디테일 — 무대 가운데 카드에 전·후를 나란히(before·after), 이미 한 장에 붙은 그림이면 img. 옵션을 켰는지와 상관없이 늘 같다
  function closeDetail() { const d = document.querySelector(".detail"); if (d) d.remove(); }
  function openDetail(o) {
    closeDetail();
    const d = o.detail, w = document.createElement("div"), fig = (p, cls, cap) => p && has(p)
      ? '<figure class="' + cls + '">' + img(p) + "<figcaption>" + cap + "</figcaption></figure>" : "";
    w.className = "detail";
    w.innerHTML = '<div class="dcard"><h3>' + esc(d.en || o.en) + '</h3><div class="dpair">' +
      (d.img ? fig(d.img, "one", "") : fig(d.before, "before", "ORIGINAL") + fig(d.after, "after", "COST OPTION")) + '</div><button type="button">Close</button></div>';
    w.querySelector("button").onclick = closeDetail;
    w.onclick = e => { if (e.target === w) closeDetail(); };
    document.querySelector(".stage").appendChild(w);
  }
  addEventListener("keydown", e => { if (e.key === "Escape") closeDetail(); });

  // 무대 바탕색 = 컷 테두리 평균색. 사진 배경은 구석과 가운데 밝기가 달라 한 구석 색만 쓰면 반대편 가장자리가 떴다
  const bgc = {};
  function edgeColor(p) {
    const set = c => document.querySelector(".stage").style.setProperty("--bgc", c);
    if (bgc[p]) return set(bgc[p]);
    const im = new Image();
    im.onload = () => {
      const w = 40, h = 60, cv = document.createElement("canvas"); cv.width = w; cv.height = h;
      const x = cv.getContext("2d"); x.drawImage(im, 0, 0, w, h);
      const d = x.getImageData(0, 0, w, h).data, s = [0, 0, 0]; let n = 0;
      for (let y = 0; y < h; y++) for (let i = 0; i < w; i++) {
        if (y > 1 && y < h - 2 && i > 1 && i < w - 2) continue;  // 바깥 두 줄만
        const k = (y * w + i) * 4; s[0] += d[k]; s[1] += d[k + 1]; s[2] += d[k + 2]; n++;
      }
      bgc[p] = "rgb(" + s.map(v => Math.round(v / n)).join(",") + ")"; set(bgc[p]);
    };
    im.src = U(p);
  }

  let gen = 0;
  function render() {
    const g = ++gen, s = st(), sd = side(), m = motion; motion = null;  // 모션은 render 한 번으로 소진
    const cmp = on.length > 0;
    document.querySelectorAll(".sty").forEach(b => b.setAttribute("aria-selected", b.dataset.g === (s.g || s.c)));
    document.querySelector(".stage").classList.toggle("cmp", cmp);
    brand(s.logo || br.logo);

    // 왼쪽 오리지널 · 오른쪽 옵션
    const baseV = loop([]), optV = loop(on), baseS = still([], sd), optS = still(on, sd);
    const motionMode = !STILL && has(baseV);
    const together = motionMode && cmp && !wait && !m && has(optV);
    let a, b;
    if (motionMode && (!cmp || together)) a = vid(baseV, "loop " + (together ? 'preload="auto"' : "autoplay"), baseS);
    else a = has(baseS) ? img(baseS) : pending(s.b && s.b.en || "Original design");
    if (!cmp) b = "";
    else if (m) b = vid(m.p, 'id="mot" autoplay', still(m.from, sd));
    else if (together) b = vid(optV, 'loop preload="auto"', optS);
    else if (has(optS)) b = img(optS);
    else if (motionMode && has(optV)) b = vid(optV, "loop autoplay", optS);
    else b = pending(on.map(i => s.o[i].en).join(" + ") + (back ? " / back" : " / front"));
    const poster = has(optS) && cmp ? optS : has(still([], "F")) ? still([], "F") : null;
    if (poster) { $("wash").style.backgroundImage = 'url("' + U(poster) + '")'; edgeColor(poster); }
    const na = swap("orig", a), nb = swap("frame", b);
    if (together && (na || nb)) playTogether();
    // 옵션을 켠 직후 — 정지 컷으로 잠깐 선 뒤(모션이 있으면 모션이 끝난 뒤) 두 턴 영상을 같이 출발
    if (cmp && wait && !m) setTimeout(() => { if (g === gen) { wait = false; render(); } }, 700);
    if (m) {
      const mv = $("frame").querySelector(".layer.on #mot");
      if (mv) {
        let done = false;
        const fin = () => { if (done || g !== gen) return; done = true; wait = false; render(); };
        mv.onended = fin;
        const arm = () => setTimeout(fin, (mv.duration || 6) * 1000 + 700);  // 안 그려지면 ended가 안 온다
        if (mv.readyState > 0) arm(); else mv.onloadedmetadata = arm;
      }
    }
    // 앞·뒤 — 턴 영상이 돌면 둘 다 보이니 숨긴다. 뒤 컷이 없는 스타일도 숨긴다
    $("sideWrap").hidden = (motionMode && (!cmp || has(optV))) || !has(still([], "B"));
    $("sF").setAttribute("aria-pressed", !back); $("sB").setAttribute("aria-pressed", back);

    // 옵션 목록
    const row = $("optsRow"); row.innerHTML = "";
    visible().forEach(i => {
      const o = s.o[i], btn = document.createElement("button"), v = saving(o);
      btn.className = "opt"; btn.type = "button"; btn.setAttribute("aria-pressed", on.includes(i));
      const face = o.view === "F" ? "front" : o.view === "B" ? "back" : "front & back";
      btn.innerHTML = '<span class="box"></span><span class="body"><span class="lb">' + esc(o.en) + '</span><span class="mt">' +
        (o.how === "3D" ? "3D option render" : o.how === "AI" ? "AI edit" : esc(o.how || "")) + " / " + face +
        (o.sub && o.sub.en ? " · " + esc(o.sub.en) : "") + "</span></span>" +
        (B.money ? '<span class="amt">' + (v == null ? "—" : "-" + usd(v)) + "</span>" : "") +
        (o.detail ? '<span class="zoombtn" role="button" tabindex="0" aria-label="Close-up: ' + esc(o.detail.en || o.en) +
          '"><svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" aria-hidden="true">' +
          '<circle cx="10.6" cy="10.6" r="6.4"></circle><path d="M15.4 15.4 20.5 20.5"></path></svg></span>' : "");
      const zb = btn.querySelector(".zoombtn");
      if (zb) {
        const open = e => { e.stopPropagation(); e.preventDefault(); openDetail(o); };
        zb.onclick = open; zb.onkeydown = e => { if (e.key === "Enter" || e.key === " ") open(e); };
      }
      btn.onclick = () => toggle(i);
      row.appendChild(btn);
    });
    if (MULTI && visible().length > 1) {
      const rb = document.createElement("button");
      rb.className = "reset"; rb.type = "button"; rb.textContent = "Clear all";
      rb.onclick = () => { on = []; wait = false; render(); };
      row.appendChild(rb);
    }

    // 칸 아래 — 이름·절감액·단가
    const vals = on.map(i => saving(s.o[i])), sum = vals.reduce((x, v) => x + (v || 0), 0);
    const max = visible().reduce((x, i) => x + (saving(s.o[i]) || 0), 0);
    $("nmA").textContent = s.b && s.b.en || "Original design";
    $("saver").hidden = !B.money;
    $("saverT").textContent = MULTI ? "TOTAL SAVING" : "SAVING";
    const fc = B.money && s.k && typeof s.k.fc === "number" ? s.k.fc : null;  // 단가가 있으면 칸 아래 전·후 단가
    $("prA").textContent = fc == null ? "" : "FIRST COST " + usd(fc);
    if (cmp) {  // 비교 중에만 바꾼다 — 닫히며 사라지는 동안 글자가 먼저 비지 않게
      $("nmB").textContent = on.slice().sort((x, y) => x - y).map(i => s.o[i].en).join("\n+ ");
      if (B.money) countTo(vals.includes(null) ? null : sum);
      $("prB").textContent = fc == null || vals.includes(null) ? "" : usd(fc - sum) + " · −" + (sum / fc * 100).toFixed(1) + "%";
      $("bar").style.width = (max > 0 ? Math.min(100, sum / max * 100) : 0) + "%";
    }

    // 컬러 — 같은 묶음의 변형은 칩 버튼
    const gr = groups.find(x => x.g === (s.g || s.c)), chips = $("chips");
    chips.innerHTML = "";
    gr.items.forEach(i => {
      const c = S[i], el = document.createElement(gr.items.length > 1 ? "button" : "span"), ch = "chips/" + c.c + ".jpg";
      el.className = "chip"; el.style.background = has(ch) ? 'center/cover url("' + U(ch) + '")' : (c.hex || "#ccc");
      if (gr.items.length > 1) { el.type = "button"; el.setAttribute("aria-pressed", i === si); el.setAttribute("aria-label", c.col || c.c); el.onclick = () => pick(i); }
      chips.appendChild(el);
    });
    $("cname").textContent = s.col || "—";
    document.body.dataset.pending = document.querySelectorAll(".layer.on .pending").length;  // shots --check
  }

  function toggle(i) {
    closeDetail();
    const p = on.indexOf(i);
    if (p < 0) {
      const before = MULTI ? on.slice() : [];
      on = MULTI ? on.concat([i]) : [i];
      wait = !STILL;
      const o = st().o[i], sd = side();
      if (!STILL && o.view.includes(sd) && has(mot(sd, before, on))) motion = {p: mot(sd, before, on), from: before};  // 켜는 방향만(끄기 모션 없음)
      bills();
      const v = saving(o), f = $("fly");
      if (v != null && B.money) { f.textContent = "-" + usd(v); f.classList.remove("go"); void f.offsetWidth; f.classList.add("go"); }
    } else { on.splice(p, 1); wait = false; }
    render();
  }

  $("sF").onclick = () => { back = false; render(); };
  $("sB").onclick = () => { back = true; render(); };

  // 캡처 상태: #s=1&o=13&b=1
  if (SHOT) {
    const h = new URLSearchParams(location.hash.slice(1)), s = +h.get("s") || 0, o = h.get("o") || "0";
    if (S[s]) si = s;
    on = o === "0" ? [] : o.split("").map(n => +n - 1).filter(i => st().o[i]);
    back = h.get("b") === "1";
  }
  render();
})();
