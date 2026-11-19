"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
let current = null; // last project view from the API
let pollTimer = null;

const STATE_LABEL = {
  ingested: "입력됨", scripted: "대본 생성됨", reviewing: "검토 중", approved: "승인됨",
  rendering: "렌더링 중…", render_failed: "렌더 실패", rendered: "렌더 완료",
  uploading: "업로드 중…", upload_failed: "업로드 실패", uploaded: "업로드 완료",
};

async function api(method, path, body) {
  const opts = { method, headers: { "X-Shortsgen": "1" } };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : res.statusText);
  return data;
}

function showMessage(text, info = false) {
  const m = $("#message");
  m.hidden = !text;
  m.textContent = text || "";
  m.classList.toggle("info", info);
}

async function run(fn, busyText) {
  document.querySelectorAll("button").forEach(b => (b.disabled = true));
  if (busyText) showMessage(busyText, true);
  try {
    const view = await fn();
    showMessage("");
    if (view && view.project) render(view);
  } catch (e) {
    showMessage(e.message);
    if (current) render(current);
  } finally {
    document.querySelectorAll("button").forEach(b => (b.disabled = false));
    if (current) updateButtons(current);
  }
}

async function loadList() {
  const items = await api("GET", "/api/projects");
  const ul = $("#project-list");
  ul.innerHTML = "";
  for (const it of items) {
    const li = document.createElement("li");
    li.innerHTML = `<span></span><small></small>`;
    li.firstChild.textContent = it.title;
    li.lastChild.textContent = STATE_LABEL[it.state] || it.state;
    li.classList.toggle("active", current && current.project.id === it.id);
    li.onclick = () => open(it.id);
    ul.appendChild(li);
  }
}

async function open(id) {
  await run(() => api("GET", `/api/projects/${id}`));
  loadList();
}

function updateButtons(v) {
  const s = v.project.state;
  const busy = s === "rendering" || s === "uploading";
  const act = a => document.querySelector(`[data-act="${a}"]`);
  act("images").disabled = busy;
  act("tts").disabled = busy;
  act("approve").disabled = busy || !["scripted", "reviewing"].includes(s);
  act("render").disabled = !["approved", "render_failed"].includes(s);
  act("upload").disabled = !!v.project.video_id || !["rendered", "upload_failed"].includes(s);
}

function render(v) {
  current = v;
  const p = v.project;
  $("#empty").hidden = true;
  $("#project").hidden = false;
  $("#state").textContent = STATE_LABEL[p.state] || p.state;

  const d = $("#duration");
  const [lo, hi] = v.duration_range;
  if (v.predicted_seconds == null) { d.textContent = "예상 길이: 음성 생성 필요"; d.className = "meter"; }
  else {
    const ok = v.predicted_seconds >= lo && v.predicted_seconds <= hi;
    d.textContent = `예상 길이 ${v.predicted_seconds.toFixed(1)}초 (${lo}~${hi}초)`;
    d.className = "meter " + (ok ? "good" : "bad");
  }
  $("#cost").textContent = `비용 ${v.cost_krw}원 / 상한 ${v.cost_ceiling_krw}원`;

  const issues = $("#issues");
  issues.innerHTML = "";
  for (const i of v.issues) { const li = document.createElement("li"); li.textContent = i; issues.appendChild(li); }

  if (p.error) showMessage(p.error);
  const result = $("#result");
  result.hidden = !(v.has_video || v.video_url);
  result.innerHTML = "";
  if (v.video_url) {
    const a = document.createElement("a");
    a.href = v.video_url; a.target = "_blank"; a.textContent = `YouTube (비공개): ${v.video_url}`;
    result.appendChild(a);
  }
  if (v.has_video) {
    const vid = document.createElement("video");
    vid.controls = true; vid.src = `/api/projects/${p.id}/video.mp4?t=${Date.now()}`;
    result.appendChild(vid);
  }

  if (p.script) {
    $("#meta-title").value = p.script.title;
    $("#meta-desc").value = p.script.description;
    $("#meta-tags").value = p.script.hashtags.join(" ");
  }
  renderScenes(v);
  updateButtons(v);
  schedulePoll(v);
}

function codeView(pre, block, start, end) {
  pre.innerHTML = "";
  if (!block) { pre.textContent = "(코드 없음)"; return; }
  block.content.split("\n").forEach((line, i) => {
    const n = i + 1;
    const row = document.createElement("span");
    row.className = n >= start && n <= end ? "in" : "";
    row.style.display = "block";
    const ln = document.createElement("span");
    ln.className = "ln"; ln.textContent = String(n);
    row.appendChild(ln);
    row.appendChild(document.createTextNode(line || " "));
    pre.appendChild(row);
  });
}

function sentenceRow(container, s) {
  const row = document.createElement("div");
  row.className = "sentence";
  row.innerHTML = `<input class="text" maxlength="80" placeholder="내레이션 문장"><input class="hl" type="number" min="1" placeholder="강조줄" title="말할 때 강조할 코드 줄"><button type="button" title="삭제">✕</button>`;
  $(".text", row).value = s.text || "";
  $(".hl", row).value = s.highlight_line ?? "";
  row.querySelector("button").onclick = () => row.remove();
  container.appendChild(row);
}

function renderScenes(v) {
  const p = v.project;
  const root = $("#scenes");
  root.innerHTML = "";
  if (!p.script) return;
  const tpl = $("#scene-tpl");
  for (const sc of p.script.scenes) {
    const el = tpl.content.firstElementChild.cloneNode(true);
    const st = v.scene_status[sc.id] || {};
    $("h3", el).textContent = `장면 ${sc.id}`;
    $(".flags", el).innerHTML =
      `<span class="${st.image_fresh ? "fresh" : "stale"}">이미지 ${st.image_fresh ? "✓" : "필요"}</span>` +
      `<span class="${st.tts_fresh ? "fresh" : "stale"}">음성 ${st.tts_fresh ? "✓" : "필요"}</span>`;
    const img = $("img", el);
    const rec = p.assets[`image:${sc.id}`];
    if (rec) img.src = `/api/projects/${p.id}/assets/${rec.path.split("/").pop()}?h=${rec.source_hash.slice(0, 8)}&t=${Date.now()}`;
    $(".on-screen", el).value = sc.on_screen_text;
    $(".image-prompt", el).value = sc.image_prompt;
    const sents = $(".sentences", el);
    sc.narration.forEach(s => sentenceRow(sents, s));
    $(".add-sentence", el).onclick = () => sentenceRow(sents, { text: "" });

    const sel = $(".block", el);
    sel.innerHTML = `<option value="">(코드 없음)</option>` + p.doc.code_blocks
      .map(b => `<option value="${b.id}">${b.id} · ${b.language || "text"} · ${b.content.split("\n").length}줄</option>`).join("");
    sel.value = sc.code ? sc.code.block_id : "";
    $(".start", el).value = sc.code ? sc.code.start_line : 1;
    $(".end", el).value = sc.code ? sc.code.end_line : 1;
    const refresh = () => codeView($(".code-view", el), p.doc.code_blocks.find(b => b.id === sel.value),
      +$(".start", el).value, +$(".end", el).value);
    sel.onchange = refresh; $(".start", el).oninput = refresh; $(".end", el).oninput = refresh;
    refresh();

    $(".save", el).onclick = () => run(() => api("PUT", `/api/projects/${p.id}/scenes/${sc.id}`, {
      on_screen_text: $(".on-screen", el).value,
      image_prompt: $(".image-prompt", el).value,
      narration: [...el.querySelectorAll(".sentence")].map(r => ({
        text: $(".text", r).value.trim(),
        highlight_line: $(".hl", r).value ? +$(".hl", r).value : null,
      })).filter(s => s.text),
      code: sel.value ? { block_id: sel.value, start_line: +$(".start", el).value, end_line: +$(".end", el).value } : null,
    }));
    el.querySelector('[data-sact="image"]').onclick = () => run(() => api("POST", `/api/projects/${p.id}/scenes/${sc.id}/image`), "이미지 생성 중…");
    const video = $("video", el);
    if (v.previews[sc.id]) { video.hidden = false; video.src = `/api/projects/${p.id}/scenes/${sc.id}/preview.mp4?t=${Date.now()}`; }
    el.querySelector('[data-sact="preview"]').onclick = () => run(async () => {
      const r = await api("POST", `/api/projects/${p.id}/scenes/${sc.id}/preview`);
      if (r.status === "building") waitPreview(p.id, sc.id);
      return api("GET", `/api/projects/${p.id}`);
    }, "미리보기 만드는 중…");
    root.appendChild(el);
  }
}

function waitPreview(pid, sid, tries = 0) {
  setTimeout(async () => {
    const v = await api("GET", `/api/projects/${pid}`);
    if (v.previews[sid]) { render(v); showMessage(""); }
    else if (tries < 60) waitPreview(pid, sid, tries + 1);
  }, 2000);
}

function schedulePoll(v) {
  clearTimeout(pollTimer);
  if (["rendering", "uploading"].includes(v.project.state)) {
    pollTimer = setTimeout(async () => { render(await api("GET", `/api/projects/${v.project.id}`)); loadList(); }, 2000);
  }
}

$("#new-form").onsubmit = e => {
  e.preventDefault();
  const fd = new FormData(e.target);
  if (!fd.get("file") || !fd.get("file").name) fd.delete("file");
  run(async () => { const v = await api("POST", "/api/projects", fd); loadList(); return v; }, "문서를 읽고 대본을 만드는 중… (30초 정도 걸릴 수 있습니다)");
};

document.querySelectorAll("[data-act]").forEach(btn => {
  btn.onclick = () => {
    const pid = current.project.id;
    const act = btn.dataset.act;
    const msgs = { images: "이미지 생성 중…", tts: "음성 생성 중…", approve: "", render: "렌더링 시작…", upload: "업로드 시작… (처음이면 브라우저에서 Google 로그인 창이 열립니다)" };
    run(() => api("POST", `/api/projects/${pid}/${act}`), msgs[act]);
  };
});

$("#meta-save").onclick = () => run(() => api("PUT", `/api/projects/${current.project.id}/metadata`, {
  title: $("#meta-title").value,
  description: $("#meta-desc").value,
  hashtags: $("#meta-tags").value.split(/\s+/).filter(Boolean),
}));

loadList();
