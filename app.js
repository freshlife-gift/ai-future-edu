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
  const searchBtn = $("#searchBtn");
  const sourceInfo = $("#sourceInfo");
  const tabBtns = $$(".tab-btn");
  const subTabBtns = $$(".sub-tab-btn");

  let data = null;
  let section = "news";
  let subSection = "academic_domestic";
  let query = "";

  const META = {
    news: { icon: "📰", label: "뉴스기사",
      sources: "서울시교육청 오늘의 뉴스 · 네이버 뉴스" },
    global_trends: { icon: "🌏", label: "해외동향",
      sources: 'KEDI 교육정책네트워크 · <a href="https://www.unesco.org/en/education" target="_blank">UNESCO</a> · <a href="https://www.oecd.org/en/about/directorates/directorate-for-education-and-skills.html" target="_blank">OECD</a>' },
    policy: { icon: "📋", label: "정책",
      sources: "KEDI 교육정책네트워크" },
    reports: { icon: "📚", label: "연구보고서",
      sources: "KEDI 교육정책네트워크" },
    academic_domestic: { icon: "📖", label: "국내학술지",
      sources: "CrossRef (국내 학술지)" },
    academic_international: { icon: "🌐", label: "해외학술지",
      sources: "ERIC (Education Resources Information Center)" },
  };

  // 하루 최대 추가 건수는 백엔드에서 제어 (5건)
  // 프론트엔드는 누적된 전체 자료를 표시

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

    // 검색
    const doSearch = () => {
      query = searchInput.value.trim().toLowerCase();
      searchClear.style.display = query ? "block" : "none";
      render();
    };
    searchInput.addEventListener("input", doSearch);
    if (searchBtn) searchBtn.addEventListener("click", doSearch);
    searchClear.addEventListener("click", () => {
      searchInput.value = ""; query = ""; searchClear.style.display = "none"; render();
    });
  }

  function updateBadges() {
    if (!data) return;
    const s = data.sections || {};
    // 배지 = 신규(is_new) 자료 수
    ["news","global_trends","policy","reports"].forEach(k => {
      const b = $(`#badge-${k}`);
      if (b) {
        const newCount = (s[k]||[]).filter(a => a.is_new).length;
        b.textContent = newCount;
        b.style.display = newCount > 0 ? "" : "none";
      }
    });
    const domNew = (s.academic_domestic||[]).filter(a => a.is_new).length;
    const intlNew = (s.academic_international||[]).filter(a => a.is_new).length;
    const ab = $("#badge-academic");
    if (ab) { ab.textContent = domNew + intlNew; ab.style.display = (domNew + intlNew) > 0 ? "" : "none"; }
    const db = $("#badge-academic_domestic");
    if (db) { db.textContent = domNew; db.style.display = domNew > 0 ? "" : "none"; }
    const ib = $("#badge-academic_international");
    if (ib) { ib.textContent = intlNew; ib.style.display = intlNew > 0 ? "" : "none"; }
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

    // 검색 모드: 전체 섹션 검색
    if (query) {
      let all = [];
      for (const [k, arr] of Object.entries(data.sections || {})) {
        for (const item of arr) {
          const text = `${item.title} ${item.summary||""} ${item.source||""} ${item.author||""} ${item.implications||""}`.toLowerCase();
          if (text.includes(query)) all.push({ ...item, _section: k });
        }
      }
      items = all;
    } else {
      // 수집날짜 최신순 → 같은 날짜 내 적합도순
      items = [...items].sort((a, b) => {
        const da = a.collected_date || "0";
        const db = b.collected_date || "0";
        if (da !== db) return db.localeCompare(da);
        return (b.score || 0) - (a.score || 0);
      });
    }

    // 출처 표시
    if (sourceInfo) {
      if (!query) {
        const meta = META[key];
        sourceInfo.innerHTML = meta ? `<span>${meta.icon}</span> 자료출처: ${meta.sources}` : "";
        sourceInfo.style.display = meta ? "inline-flex" : "none";
      } else {
        sourceInfo.style.display = "none";
      }
    }

    cardsContainer.innerHTML = "";
    emptyState.style.display = "none";

    if (items.length === 0) {
      emptyState.style.display = "flex";
      return;
    }

    items.forEach((item, i) => cardsContainer.appendChild(createCard(item, i, !!query)));
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

    const newBadge = item.is_new ? '<span class="new-badge">NEW</span>' : '';
    const collDate = item.collected_date ? `<span class="card__date">수집: ${esc(item.collected_date)}</span>` : '';
    const sectionLabel = isSearch && item._section ? `<span class="card__section-tag">${META[item._section]?.icon||""} ${META[item._section]?.label||""}</span>` : "";

    const metaParts = [];
    if (item.source) metaParts.push(`🏢 ${esc(item.source)}`);
    if (item.author) metaParts.push(`✍️ ${esc(item.author)}`);
    if (item.published_date) metaParts.push(`📅 ${esc(String(item.published_date))}`);

    const isAcad = (item._section || key_for_section()).startsWith("academic");
    const apaHtml = item.apa_citation ? `<div class="card__apa">${fmtApa(item.apa_citation)}</div>` : "";

    card.innerHTML = `
      <div class="card__header">
        <h3 class="card__title">${titleHtml} ${newBadge}</h3>
        <div class="score-badge ${cls}" title="${score}/5"><span>${stars}</span><span>${score}</span></div>
      </div>
      <div class="card__meta-row">
        ${sectionLabel}
        <div class="card__meta">${metaParts.join(' <span class="dot">·</span> ')}</div>
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

  function key_for_section() {
    return section === "academic" ? subSection : section;
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
      .replace(/\[정책제언\]/g, '<strong class="il il--p">[정책제언]</strong>')
      .replace(/\[정책방향\]/g, '<strong class="il il--p">[정책제언]</strong>')
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
      $("#lockScreen").classList.add("lock-screen--hidden"); init(); return;
    }
    $("#lockForm").addEventListener("submit", async e => {
      e.preventDefault();
      const inp = $("#lockPassword");
      if (await sha1(inp.value) === PH) {
        sessionStorage.setItem("auth","1"); $("#lockScreen").classList.add("lock-screen--hidden"); init();
      } else { $("#lockError").style.display = "block"; inp.value = ""; inp.focus(); }
    });
  });
})();
