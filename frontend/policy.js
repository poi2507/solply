// 거래 정책 — 로그인한 주체가 자기 에이전트의 판단 경계를 정한다.
// 저장된 값은 백엔드에서 프롬프트의 POLICY 섹션으로 주입된다.
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

async function renderForm(host, ownerId) {
  const { fields: raw } = await api(`/api/policy/${ownerId}`);
  // 성격(문장)이 먼저, 경계(숫자)가 뒤 — 시연·일상 모두 자주 만지는 건 문장이다
  const fields = [...raw.filter((f) => f.type === "text"), ...raw.filter((f) => f.type !== "text")];

  host.innerHTML = `
    <div class="policy">
      <p class="policy-note">에이전트는 이 범위 안에서만 스스로 판단합니다. 넘으면 사람에게 넘깁니다.</p>
      <form id="policy-form">
        ${fields.map((f) => `
          <label class="field${f.type === "text" ? " wide" : ""}">
            <span class="f-label">${f.label}</span>
            <span class="f-help">${f.help}</span>
            ${f.type === "text" ? `
              ${(f.presets ?? []).length ? `
              <span class="preset-row" data-for="${f.key}">
                ${f.presets.map((pr) => `
                  <button type="button" class="preset${pr.text === f.value ? " on" : ""}"
                          data-key="${f.key}" data-text="${esc(pr.text)}">${esc(pr.label)}</button>`).join("")}
              </span>` : ""}
              <textarea class="f-text" name="${f.key}" rows="4"
                        maxlength="${f.maxlength ?? 400}">${esc(f.value)}</textarea>`
            : `<span class="f-input">
              <input type="number" name="${f.key}" value="${f.value}"
                     min="${f.min}" max="${f.max}" step="${f.unit === "점" || f.unit === "회" ? 1 : 0.5}">
              <em>${f.unit}</em>
            </span>`}
          </label>`).join("")}
        <div class="policy-actions">
          <button type="submit" class="save">저장</button>
          <span class="saved" id="saved-note"></span>
        </div>
      </form>
    </div>`;

  // 프리셋 클릭 → 글이 채워지고, 이후 자유 수정 가능 (저장 대상은 최종 글)
  host.querySelectorAll(".preset").forEach((btn) => {
    btn.addEventListener("click", () => {
      const area = host.querySelector(`textarea[name="${btn.dataset.key}"]`);
      area.value = btn.dataset.text;
      host.querySelectorAll(`.preset[data-key="${btn.dataset.key}"]`).forEach((b) =>
        b.classList.toggle("on", b === btn));
      host.querySelector(".save").classList.add("dirty");
      host.querySelector(".save").textContent = "저장 (변경됨)";
      area.focus();
    });
  });
  // 무엇이든 고치면 저장 버튼이 "저장 필요" 상태로 바뀐다 — 바꿔놓고 안 누르는 실수 방지
  const saveBtn = host.querySelector(".save");
  host.querySelector("#policy-form")?.addEventListener("input", (e) => {
    saveBtn.classList.add("dirty");
    saveBtn.textContent = "저장 (변경됨)";
    if (e.target.matches(".f-text")) {
      host.querySelectorAll(`.preset[data-key="${e.target.name}"]`).forEach((b) =>
        b.classList.toggle("on", b.dataset.text === e.target.value));
    }
  });

  host.querySelector("#policy-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const note = host.querySelector("#saved-note");
    const values = {};
    const textKeys = new Set(fields.filter((f) => f.type === "text").map((f) => f.key));
    new FormData(e.target).forEach((v, k) => (values[k] = textKeys.has(k) ? String(v) : Number(v)));
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
