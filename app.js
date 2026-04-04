(() => {
  "use strict";
  const $ = s => document.querySelector(s);
  const $$ = s => document.querySelectorAll(s);

  const cardsContainer = $("#cardsContainer");
  const loadingState = $("#loadingState");
  const emptyState = $("#emptyState");
  const errorState = $("#errorState");
  const subTabNav = $("#subTabNav");
  const searchInput = $("#searchInput");
  const searchClear = $("#searchClear");
  const tabBtns = $$(".tab-btn");
  const subTabBtns = $$(".sub-tab-btn");

  let data = null;
  let section = "news";
  let subSection = "academic_domestic";
  let query = "";

  const META = {
    news: { icon: "📰", label: "뉴스기사" },
    global_trends: { icon: "🌏", label: "해외동향" },
    policy: { icon: "📋", label: "정책" },
    reports: { icon: "📚", label: "연구보고서" },
    academic_domestic: { icon: "📖", label: "국내학술지" },
    academic_international: { icon: "🌐", label: "해외학술지" },
  };

  async function init() {
    try {
      loadingState.style.display = "flex";
      const r = await fetch("output/cumulative.json");
      if (!r.ok) throw new Error("HTTP " + r.status);
      data = await r.json();
      loadingState.style.display = "none";
      if (data.last_updated) {
        const dt = new Date(data.last_updated);
        $("#lastUpdated").textContent = "마지막 업데이트: " + dt.toLocaleString("ko-KR");
      }
      updateBadges();
      render();
    } catch (e) {
      loadingState.style.display = "none";
      errorState.style.display = "flex";
    }

    tabBtns.forEach(b => b.addEventListener("click", () => switchTab(b.dataset.section)));
    subTabBtns.forEach(b => b.addEventListener("click", () => switchSub(b.dataset.sub)));
    searchInput.addEventListener("input", () => {
      query = searchInput.value.trim().toLowerCase();
      searchClear.style.display = query ? "block" : "none";
      render();
    });
    searchClear.addEventListener("click", () => {
      searchInput.value = ""; query = ""; searchClear.style.display = "none"; render();
    });
  }

  function updateBadges() {
    if (!data) return;
    const s = data.sections || {};
    ["news","global_trends","policy","reports"].forEach(k => {
      const b = $(`#badge-${k}`);
      if (b) b.textContent = (s[k]||[]).length;
    });
    const dom = (s.academic_domestic||[]).length;
    const intl = (s.academic_international||[]).length;
    const ab = $("#badge-academic");
    if (ab) ab.textContent = dom + intl;
    const db = $("#badge-academic_domestic");
    if (db) db.textContent = dom;
    const ib = $("#badge-academic_international");
    if (ib) ib.textContent = intl;
  }

  function switchTab(s) {
    section = s;
    tabBtns.forEach(b => b.classList.toggle("tab-btn--active", b.dataset.section === s));
    subTabNav.style.display = s === "academic" ? "block" : "none";
    render();
  }

  function switchSub(s) {
    subSection = s;
    subTabBtns.forEach(b => b.classList.toggle("sub-tab-btn--active", b.dataset.sub === s));
    render();
  }

  function render() {
    if (!data) return;
    const key = section === "academic" ? subSection : section;
    let items = (data.sections || {})[key] || [];

    // 검색: 전체 섹션 검색
    if (query) {
      let all = [];
      for (const [k, arr] of Object.entries(data.sections || {})) {
        for (const item of arr) {
          const text = `${item.title} ${item.summary||""} ${item.source||""} ${item.author||""} ${item.implications||""}`.toLowerCase();
          if (text.includes(query)) {
            all.push({ ...item, _section: k });
          }
        }
      }
      items = all;
    }

    cardsContainer.innerHTML = "";
    emptyState.style.display = "none";

    if (items.length === 0) {
      emptyState.style.display = "flex";
      return;
    }

    items.forEach((item, i) => cardsContainer.appendChild(createCard(item, i, query)));
    // scroll animation
    const obs = new IntersectionObserver(entries => {
      entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add("card--visible"); obs.unobserve(e.target); } });
    }, { threshold: 0.08 });
    $$(".card").forEach(c => obs.observe(c));
  }

  function createCard(item, i, isSearch) {
    const card = document.createElement("div");
    card.className = "card";
    card.style.animationDelay = i * 60 + "ms";

    const score = item.score || 0;
    const cls = score >= 4.5 ? "score-badge--high" : "score-badge--mid";
    const stars = "★".repeat(Math.round(score)) + "☆".repeat(5 - Math.round(score));

    const hasUrl = item.url && !item.url.includes("scrapmaster");
    const titleHtml = hasUrl
      ? `<a href="${esc(item.url)}" target="_blank">${esc(item.title)}</a>`
      : esc(item.title);

    // NEW 배지
    const newBadge = item.is_new ? '<span class="new-badge">NEW</span>' : '';

    // 수집 날짜
    const collDate = item.collected_date ? `<span class="card__date">수집: ${esc(item.collected_date)}</span>` : '';

    // 검색 시 섹션 표시
    const sectionLabel = isSearch && item._section ? `<span class="card__section-tag">${META[item._section]?.icon || ""} ${META[item._section]?.label || item._section}</span>` : "";

    // 메타
    const meta = [];
    if (item.source) meta.push(`🏢 ${esc(item.source)}`);
    if (item.author) meta.push(`✍️ ${esc(item.author)}`);
    if (item.published_date) meta.push(`📅 ${esc(String(item.published_date))}`);

    const isAcad = (item._section || section) === "academic" ||
                   (item._section || "").startsWith("academic");
    const apaHtml = item.apa_citation ? `<div class="card__apa">${fmtApa(item.apa_citation)}</div>` : "";

    card.innerHTML = `
      <div class="card__header">
        <h3 class="card__title">${titleHtml} ${newBadge}</h3>
        <div class="score-badge ${cls}" title="${score}/5"><span>${stars}</span><span>${score}</span></div>
      </div>
      <div class="card__meta-row">
        ${sectionLabel}
        <div class="card__meta">${meta.join(' <span class="dot">·</span> ')}</div>
        ${collDate}
      </div>
      ${isAcad ? apaHtml : ""}
      <div class="card__summary">${esc(item.summary)}</div>
      ${item.implications ? `
      <div class="accordion" id="acc-${i}">
        <button class="accordion__trigger" onclick="toggleAccordion('acc-${i}')">
          <span>💡 AI미래교육팀 시사점</span><span class="accordion__arrow">▼</span>
        </button>
        <div class="accordion__body"><div class="accordion__content">${fmtImpl(item.implications)}</div></div>
      </div>` : ""}
    `;
    return card;
  }

  window.toggleAccordion = id => {
    const el = document.getElementById(id);
    if (el) el.classList.toggle("accordion--open");
  };

  function esc(s) { if (!s) return ""; const d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

  function fmtImpl(t) {
    if (!t) return "";
    return esc(t)
      .replace(/\[관련업무\]/g, '<strong class="il il--d">[관련업무]</strong>')
      .replace(/\[정책방향\]/g, '<strong class="il il--p">[정책방향]</strong>')
      .replace(/\[참고사항\]/g, '<strong class="il il--n">[참고사항]</strong>')
      .replace(/\n/g, "<br>");
  }

  function fmtApa(t) { return t ? esc(t).replace(/\*([^*]+)\*/g, "<em>$1</em>") : ""; }

  // 잠금
  const PH = "5420dcab71e0fb6328f565ce359ed1e0e601d64b";
  async function sha1(s) {
    const b = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(s));
    return Array.from(new Uint8Array(b)).map(x => x.toString(16).padStart(2,"0")).join("");
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (sessionStorage.getItem("auth") === "1") {
      $("#lockScreen").classList.add("lock-screen--hidden");
      init();
      return;
    }
    $("#lockForm").addEventListener("submit", async e => {
      e.preventDefault();
      const inp = $("#lockPassword");
      if (await sha1(inp.value) === PH) {
        sessionStorage.setItem("auth", "1");
        $("#lockScreen").classList.add("lock-screen--hidden");
        init();
      } else {
        $("#lockError").style.display = "block";
        inp.value = ""; inp.focus();
      }
    });
  });
})();
