// 거래 정책 — 로그인한 주체가 자기 에이전트의 판단 경계를 정한다.
// 저장된 값은 백엔드에서 프롬프트의 POLICY 섹션으로 주입된다.
//
// 주체 선택(로그인)은 role.js가 전역으로 관리한다. 여기서는 넘겨받은 owner의 폼만 그린다.

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? res.statusText);
  return res.json();
}

async function renderForm(host, ownerId) {
  const { fields } = await api(`/api/policy/${ownerId}`);

  host.innerHTML = `
    <div class="policy">
      <p class="policy-note">에이전트는 이 범위 안에서만 스스로 판단합니다. 넘으면 사람에게 넘깁니다.</p>
      <form id="policy-form">
        ${fields.map((f) => `
          <label class="field${f.type === "text" ? " wide" : ""}">
            <span class="f-label">${f.label}</span>
            <span class="f-help">${f.help}</span>
            ${f.type === "text" ? `
              <textarea class="f-text" name="${f.key}" rows="4"
                        maxlength="${f.maxlength ?? 400}">${f.value ?? ""}</textarea>`
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
