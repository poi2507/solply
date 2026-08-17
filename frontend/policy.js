// 거래 정책 — 로그인한 주체가 자기 에이전트의 판단 경계를 정한다.
// 저장된 값은 백엔드에서 프롬프트의 POLICY 섹션으로 주입된다.
//
// 숫자(경계)는 폼에서 바로, 문장(기조·전략)은 미리보기 카드 → 모달 편집기로.
// 긴 글을 사이드바의 작은 칸에 쓰게 하지 않는다 — ChatGPT 맞춤 지침·Notion처럼
// 요약을 보여주고, 편집은 큰 창에서 한다.
//
// 주체 선택(로그인)은 role.js가 전역으로 관리한다. 여기서는 넘겨받은 owner의 폼만 그린다.

async function api(path, options) {
  const token = localStorage.getItem("solply.adminToken");
  if (options && token) options.headers = { ...(options.headers || {}), "X-Admin-Token": token };
  let res = await fetch(path, options);
  if (res.status === 401 && options) {
    const entered = prompt("관리 토큰을 입력하세요 (운영자 전용)");
    if (entered) {
      localStorage.setItem("solply.adminToken", entered.trim());
      options.headers = { ...(options.headers || {}), "X-Admin-Token": entered.trim() };
      res = await fetch(path, options);
    }
  }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
  return res.json();
}

// 사용자 자유 텍스트(지점 사정)는 innerHTML에 그대로 넣으면 안 된다 — shop.js와 같은 규칙
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/** 현재 글이 어느 프리셋과 일치하는지 — 배지와 칩 활성 표시가 같은 기준을 쓴다 */
const presetOf = (field) => (field.presets ?? []).find((p) => p.text === field.value)?.label;

async function renderForm(host, ownerId) {
  const { fields: raw } = await api(`/api/policy/${ownerId}`);
  // 성격(문장)이 먼저, 경계(숫자)가 뒤 — 자주 만지는 건 문장이다
  const fields = [...raw.filter((f) => f.type === "text"), ...raw.filter((f) => f.type !== "text")];

  host.innerHTML = `
    <div class="policy">
      <p class="policy-note">에이전트는 이 범위 안에서만 스스로 판단합니다. 넘으면 사람에게 넘깁니다.</p>
      <form id="policy-form">
        ${fields.map((f) => `
          ${f.type === "text" ? `
          <div class="field wide">
            <span class="f-label">${f.label}
              <em class="p-badge">${esc(presetOf(f) ?? "직접 작성")}</em></span>
            <button type="button" class="p-preview" data-edit="${f.key}"
                    aria-label="${f.label} 크게 편집">
              <span class="p-text">${esc(f.value)}</span>
              <span class="p-open">편집 ›</span>
            </button>
          </div>`
        : `<label class="field">
            <span class="f-label">${f.label}</span>
            <span class="f-help">${f.help}</span>
            <span class="f-input">
              <input type="number" name="${f.key}" value="${f.value}"
                     min="${f.min}" max="${f.max}" step="${f.unit === "점" || f.unit === "회" ? 1 : 0.5}">
              <em>${f.unit}</em>
            </span>
          </label>`}`).join("")}
        <div class="policy-actions">
          <button type="submit" class="save">저장</button>
          <span class="saved" id="saved-note"></span>
        </div>
      </form>
    </div>`;

  // 숫자를 고치면 저장 버튼이 "저장 필요" 상태로 — 바꿔놓고 안 누르는 실수 방지
  const saveBtn = host.querySelector(".save");
  host.querySelector("#policy-form")?.addEventListener("input", () => {
    saveBtn.classList.add("dirty");
    saveBtn.textContent = "저장 (변경됨)";
  });

  host.querySelectorAll(".p-preview").forEach((btn) => {
    btn.addEventListener("click", () => {
      const field = fields.find((f) => f.key === btn.dataset.edit);
      openEditor(field, ownerId, () => renderForm(host, ownerId));
    });
  });

  host.querySelector("#policy-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const note = host.querySelector("#saved-note");
    const values = {};
    new FormData(e.target).forEach((v, k) => (values[k] = Number(v)));
    try {
      await api(`/api/policy/${ownerId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values }),
      });
      note.textContent = "저장됐습니다. 다음 판단부터 적용됩니다.";
      note.className = "saved ok";
      saveBtn.classList.remove("dirty");
      saveBtn.textContent = "저장";
    } catch (err) {
      note.textContent = err.message;
      note.className = "saved err";
    }
    setTimeout(() => (note.textContent = ""), 4000);
  });
}

// ── 문장 편집 모달 — 프리셋 칩 + 큰 입력창 + 글자수 + 자체 저장 ──────

function openEditor(field, ownerId, onSaved) {
  document.getElementById("persona-editor")?.remove();
  const max = field.maxlength ?? 400;
  const wrap = document.createElement("div");
  wrap.className = "modal-backdrop";
  wrap.id = "persona-editor";
  wrap.innerHTML = `
    <div class="modal pm" role="dialog" aria-modal="true" aria-labelledby="pm-title">
      <div class="modal-head">
        <h2 id="pm-title">${esc(field.label)}</h2>
        <button type="button" class="linkish" data-close>닫기 (Esc)</button>
      </div>
      <div class="modal-body pm-body">
        <p class="pm-help">${esc(field.help)}</p>
        <div class="preset-row">
          ${(field.presets ?? []).map((pr) => `
            <button type="button" class="preset${pr.text === field.value ? " on" : ""}"
                    data-text="${esc(pr.text)}">${esc(pr.label)}</button>`).join("")}
        </div>
        <textarea class="pm-text" maxlength="${max}"
                  placeholder="에이전트에게 문장으로 지시하세요 — 숫자 한도는 정책 숫자가 강제합니다">${esc(field.value)}</textarea>
        <div class="pm-foot">
          <span class="pm-count"></span>
          <span class="saved pm-note"></span>
          <button type="button" class="save" data-save>저장</button>
        </div>
      </div>
    </div>`;
  document.body.appendChild(wrap);

  const area = wrap.querySelector(".pm-text");
  const count = wrap.querySelector(".pm-count");
  const note = wrap.querySelector(".pm-note");
  const sync = () => {
    count.textContent = `${area.value.length} / ${max}자`;
    wrap.querySelectorAll(".preset").forEach((b) =>
      b.classList.toggle("on", b.dataset.text === area.value));
  };
  sync();
  area.addEventListener("input", sync);
  wrap.querySelectorAll(".preset").forEach((b) =>
    b.addEventListener("click", () => { area.value = b.dataset.text; sync(); area.focus(); }));

  const close = () => { wrap.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
  wrap.querySelector("[data-close]").addEventListener("click", close);

  wrap.querySelector("[data-save]").addEventListener("click", async () => {
    try {
      await api(`/api/policy/${ownerId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values: { [field.key]: area.value } }),
      });
      close();
      onSaved();   // 미리보기 카드·배지를 새 값으로
    } catch (err) {
      note.textContent = err.message;
      note.className = "saved err pm-note";
    }
  });
  area.focus();
}

/** @param ownerId 정책을 편집할 주체 (hq | store-a …) */
export function mount(host, ownerId) {
  if (!ownerId) {
    host.innerHTML = '<div class="empty">주체가 지정되지 않았습니다</div>';
    return;
  }
  renderForm(host, ownerId).catch((err) => {
    host.innerHTML = `<div class="empty">정책을 불러오지 못했습니다: ${err.message}</div>`;
  });
}
