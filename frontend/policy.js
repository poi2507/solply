// 거래 정책 설정 — 로그인한 주체가 자기 에이전트의 판단 경계를 정한다.
// 저장된 값은 백엔드에서 프롬프트의 POLICY 섹션으로 주입된다.

const OWNER_KEY = "solply.owner";

export function currentOwner() {
  return localStorage.getItem(OWNER_KEY);
}

export function signOut() {
  localStorage.removeItem(OWNER_KEY);
  location.reload();
}

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
  return res.json();
}

/** 로그인 — 지점을 고르면 그 주체로 설정 화면이 열린다. */
async function renderSignIn(host) {
  const { owners } = await api("/api/policy/owners");
  host.innerHTML = `
    <div class="gate">
      <h3>누구로 접속할까요</h3>
      <p>선택한 주체의 에이전트 정책을 설정합니다.</p>
      <div class="gate-list">
        ${owners.map((o) => `
          <button class="gate-btn ${o.kind}" data-id="${o.id}">
            <span class="gate-name">${o.name}</span>
            <span class="gate-id">${o.id}</span>
          </button>`).join("")}
      </div>
    </div>`;
  host.querySelectorAll(".gate-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      localStorage.setItem(OWNER_KEY, btn.dataset.id);
      mount(host);
    }),
  );
}

/** 정책 설정 폼 */
async function renderForm(host, ownerId) {
  const { fields } = await api(`/api/policy/${ownerId}`);
  const { owners } = await api("/api/policy/owners");
  const me = owners.find((o) => o.id === ownerId);

  host.innerHTML = `
    <div class="policy">
      <div class="policy-head">
        <div>
          <span class="who">${me?.name ?? ownerId}</span>
          <span class="sub">에이전트가 이 범위 안에서만 스스로 판단합니다</span>
        </div>
        <button class="linkish" id="signout">전환</button>
      </div>
      <form id="policy-form">
        ${fields.map((f) => `
          <label class="field">
            <span class="f-label">${f.label}</span>
            <span class="f-help">${f.help}</span>
            <span class="f-input">
              <input type="number" name="${f.key}" value="${f.value}"
                     min="${f.min}" max="${f.max}" step="${f.unit === "점" || f.unit === "회" ? 1 : 0.5}">
              <em>${f.unit}</em>
            </span>
          </label>`).join("")}
        <div class="policy-actions">
          <button type="submit" class="save">저장</button>
          <span class="saved" id="saved-note"></span>
        </div>
      </form>
    </div>`;

  host.querySelector("#signout").addEventListener("click", () => {
    localStorage.removeItem(OWNER_KEY);
    mount(host);
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
    } catch (err) {
      note.textContent = err.message;
      note.className = "saved err";
    }
    setTimeout(() => (note.textContent = ""), 4000);
  });
}

export function mount(host) {
  const owner = currentOwner();
  (owner ? renderForm(host, owner) : renderSignIn(host)).catch((err) => {
    host.innerHTML = `<div class="empty">정책을 불러오지 못했습니다: ${err.message}</div>`;
  });
}
