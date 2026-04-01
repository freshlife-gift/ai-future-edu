/**
 * AI 미래교육 지식의 창 — 프론트엔드 로직
 * ─────────────────────────────────────
 * - JSON 데이터 로드 (output/YYYY-MM-DD.json)
 * - 탭 전환 · 학술지 서브탭 · 날짜 변경
 * - 카드 렌더링 · 아코디언 · 스크롤 애니메이션
 */

(() => {
  "use strict";

  // ── DOM refs ──
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const datePicker     = $("#datePicker");
  const lastUpdated    = $("#lastUpdated");
  const filterInfo     = $("#filterInfo");
  const statsBar       = $("#statsBar");
  const cardsContainer = $("#cardsContainer");
  const loadingState   = $("#loadingState");
  const emptyState     = $("#emptyState");
  const errorState     = $("#errorState");
  const tabBtns        = $$(".tab-btn");
  const subTabNav      = $("#subTabNav");
  const subTabBtns     = $$(".sub-tab-btn");

  // ── 상태 ──
  let currentData = null;
  let currentSection = "news";
  let currentSubSection = "academic_domestic";

  // ── 섹션 메타 ──
  const SECTION_META = {
    news:          { icon: "📰", label: "뉴스기사",   sourceLabel: "📌 출처: 서울시교육청 오늘의 뉴스 (sen.go.kr)" },
    global_trends: { icon: "🌏", label: "해외동향",   sourceLabel: "📌 출처: KEDI 교육정책네트워크 (edpolicy.kedi.re.kr)" },
    policy:        { icon: "📋", label: "정책",       sourceLabel: "📌 출처: KEDI 교육정책네트워크 (edpolicy.kedi.re.kr)" },
    reports:       { icon: "📚", label: "연구보고서", sourceLabel: "📌 출처: KEDI 교육정책네트워크 (edpolicy.kedi.re.kr)" },
    academic_domestic:       { icon: "📖", label: "국내학술지", sourceLabel: "📌 출처: CrossRef (국내 학술지 검색)" },
    academic_international:  { icon: "🌐", label: "해외학술지", sourceLabel: "📌 출처: ERIC (Education Resources Information Center)" },
  };

  // ═══════════════════════════════════════════════
  // 초기화
  // ═══════════════════════════════════════════════
  let availableDates = [];

  async function init() {
    const today = formatDate(new Date());
    datePicker.value = today;
    datePicker.max = today;

    // 사용 가능한 날짜 목록 로드
    try {
      const resp = await fetch("output/dates.json");
      if (resp.ok) availableDates = await resp.json();
    } catch (e) { /* 무시 */ }

    // 이벤트
    datePicker.addEventListener("change", () => loadData(datePicker.value));

    tabBtns.forEach((btn) => {
      btn.addEventListener("click", () => switchTab(btn.dataset.section));
    });

    subTabBtns.forEach((btn) => {
      btn.addEventListener("click", () => switchSubTab(btn.dataset.sub));
    });

    // 첫 로드: 오늘 데이터 없으면 가장 최근 날짜 로드
    const startDate = availableDates.includes(today) ? today : (availableDates[0] || today);
    datePicker.value = startDate;
    loadData(startDate);
  }

  // ═══════════════════════════════════════════════
  // 데이터 로드
  // ═══════════════════════════════════════════════
  async function loadData(dateStr) {
    showLoading();

    try {
      const url = `output/${dateStr}.json`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      currentData = await resp.json();
      renderPage();
    } catch (err) {
      currentData = null;
      hideAll();
      if (err.message.includes("404") || err.message.includes("HTTP")) {
        emptyState.style.display = "flex";
      } else {
        $("#errorMsg").textContent = `데이터를 불러올 수 없습니다: ${err.message}`;
        errorState.style.display = "flex";
      }
    }
  }

  // ═══════════════════════════════════════════════
  // 페이지 렌더
  // ═══════════════════════════════════════════════
  function renderPage() {
    if (!currentData) return;

    hideAll();

    // 업데이트 시간
    if (currentData.updated_at) {
      const dt = new Date(currentData.updated_at);
      lastUpdated.textContent = `마지막 업데이트: ${dt.toLocaleString("ko-KR")}`;
    }

    // 배지 카운트
    const sections = currentData.sections || {};
    for (const key of ["news", "global_trends", "policy", "reports"]) {
      const badge = $(`#badge-${key}`);
      if (badge) badge.textContent = (sections[key] || []).length;
    }

    // 학술지 배지: 국내 + 해외 합계
    const academicBadge = $("#badge-academic");
    if (academicBadge) {
      const domesticCount = (sections.academic_domestic || []).length;
      const internationalCount = (sections.academic_international || []).length;
      academicBadge.textContent = domesticCount + internationalCount;
    }

    // 학술지 서브탭 배지
    const domBadge = $("#badge-academic_domestic");
    if (domBadge) domBadge.textContent = (sections.academic_domestic || []).length;
    const intBadge = $("#badge-academic_international");
    if (intBadge) intBadge.textContent = (sections.academic_international || []).length;

    // 현재 섹션 렌더
    renderCurrentSection();
  }

  function renderCurrentSection() {
    if (currentSection === "academic") {
      renderSection(currentSubSection);
    } else {
      renderSection(currentSection);
    }
  }

  function renderSection(section) {
    if (!currentData) return;

    const items = (currentData.sections || {})[section] || [];
    const meta = SECTION_META[section];

    // 출처 안내
    if (meta && meta.sourceLabel) {
      filterInfo.innerHTML = `<span>${meta.icon}</span> ${meta.sourceLabel}`;
      filterInfo.style.display = "inline-flex";
    } else {
      filterInfo.style.display = "none";
    }

    // 통계
    renderStats(section);

    // 카드들
    cardsContainer.innerHTML = "";
    if (items.length === 0) {
      emptyState.style.display = "flex";
      return;
    }
    emptyState.style.display = "none";

    items.forEach((item, i) => {
      const card = createCard(item, i);
      cardsContainer.appendChild(card);
    });

    observeCards();
  }

  // ═══════════════════════════════════════════════
  // 통계 바
  // ═══════════════════════════════════════════════
  function renderStats(section) {
    if (!currentData || !currentData.stats) {
      statsBar.innerHTML = "";
      return;
    }
    const s = currentData.stats;
    const map = {
      news:                    { collected: s.news_collected, selected: s.news_selected },
      global_trends:           { collected: s.trends_collected, selected: s.trends_selected },
      policy:                  { collected: s.policy_collected, selected: s.policy_selected },
      reports:                 { collected: s.reports_collected, selected: s.reports_selected },
      academic_domestic:       { collected: s.academic_domestic_collected, selected: s.academic_domestic_selected },
      academic_international:  { collected: s.academic_international_collected, selected: s.academic_international_selected },
    };
    const info = map[section] || { collected: 0, selected: 0 };

    const threshold = (section === "academic_domestic" || section === "academic_international")
      ? "상위 2건" : "관련성 4점↑";

    statsBar.innerHTML = `
      <div class="stat-chip">
        🔍 수집 <span class="stat-chip__num">${info.collected || 0}건</span>
      </div>
      <div class="stat-chip">
        ✅ 선별 <span class="stat-chip__num">${info.selected || 0}건</span>
        <span style="color:var(--text-dim)">(${threshold})</span>
      </div>
    `;
  }

  // ═══════════════════════════════════════════════
  // 카드 생성
  // ═══════════════════════════════════════════════
  function createCard(item, index) {
    const card = document.createElement("div");
    card.className = "card";
    card.style.animationDelay = `${index * 80}ms`;

    const score = item.score || 0;
    const scoreClass = score >= 4.5 ? "score-badge--high" : "score-badge--mid";
    const stars = "★".repeat(Math.round(score)) + "☆".repeat(5 - Math.round(score));

    // 출처 메타
    const metaParts = [];
    if (item.source) metaParts.push(`<span class="card__meta-item">🏢 ${esc(item.source)}</span>`);
    if (item.author) metaParts.push(`<span class="card__meta-item">✍️ ${esc(item.author)}</span>`);
    if (item.published_date) metaParts.push(`<span class="card__meta-item">📅 ${esc(item.published_date)}</span>`);
    const metaHtml = metaParts.join('<span class="card__meta-divider"></span>');

    // URL이 없거나 ScrapMaster URL이면 제목만 표시
    const hasUrl = item.url && !item.url.includes("scrapmaster");
    const titleHtml = hasUrl
      ? `<a href="${esc(item.url)}" target="_blank" rel="noopener">${esc(item.title)}</a>`
      : esc(item.title);

    // APA 인용 (학술지만)
    const isAcademic = currentSection === "academic";
    const apaCitationHtml = item.apa_citation
      ? `<div class="card__apa">${formatApa(item.apa_citation)}</div>`
      : "";

    card.innerHTML = `
      <div class="card__header">
        <h3 class="card__title">${titleHtml}</h3>
        <div class="score-badge ${scoreClass}" title="관련성 ${score}/5">
          <span>${stars}</span>
          <span>${score}</span>
        </div>
      </div>

      ${isAcademic ? apaCitationHtml : `<div class="card__meta">${metaHtml}</div>`}

      <div class="card__summary">${esc(item.summary)}</div>

      ${item.implications ? `
      <div class="accordion" id="acc-${index}">
        <button class="accordion__trigger" onclick="toggleAccordion('acc-${index}')">
          <span>💡 AI미래교육팀 시사점</span>
          <span class="accordion__arrow">▼</span>
        </button>
        <div class="accordion__body">
          <div class="accordion__content">${formatImplications(item.implications)}</div>
        </div>
      </div>` : ""}
    `;

    return card;
  }

  // ═══════════════════════════════════════════════
  // 아코디언
  // ═══════════════════════════════════════════════
  window.toggleAccordion = function (id) {
    const el = document.getElementById(id);
    if (el) el.classList.toggle("accordion--open");
  };

  // ═══════════════════════════════════════════════
  // 탭 전환
  // ═══════════════════════════════════════════════
  function switchTab(section) {
    currentSection = section;
    tabBtns.forEach((btn) => {
      btn.classList.toggle("tab-btn--active", btn.dataset.section === section);
    });

    // 학술지 서브탭 표시/숨기기
    subTabNav.style.display = section === "academic" ? "block" : "none";

    if (currentData) {
      hideAll();
      renderCurrentSection();
    }
  }

  function switchSubTab(sub) {
    currentSubSection = sub;
    subTabBtns.forEach((btn) => {
      btn.classList.toggle("sub-tab-btn--active", btn.dataset.sub === sub);
    });

    if (currentData) {
      hideAll();
      renderSection(sub);
    }
  }

  // ═══════════════════════════════════════════════
  // IntersectionObserver (스크롤 애니메이션)
  // ═══════════════════════════════════════════════
  function observeCards() {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("card--visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.08, rootMargin: "0px 0px -40px 0px" }
    );
    $$(".card").forEach((c) => observer.observe(c));
  }

  // ═══════════════════════════════════════════════
  // 유틸
  // ═══════════════════════════════════════════════
  function formatDate(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  function esc(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function formatImplications(text) {
    if (!text) return "";
    // [관련업무], [정책방향], [참고사항] 라벨을 볼드 처리
    return esc(text)
      .replace(/\[관련업무\]/g, '<strong class="impl-label impl-label--duty">[관련업무]</strong>')
      .replace(/\[정책방향\]/g, '<strong class="impl-label impl-label--policy">[정책방향]</strong>')
      .replace(/\[참고사항\]/g, '<strong class="impl-label impl-label--note">[참고사항]</strong>')
      .replace(/\n/g, "<br>");
  }

  function formatApa(text) {
    if (!text) return "";
    // 이탤릭 처리: *text* → <em>text</em>
    return esc(text).replace(/\*([^*]+)\*/g, "<em>$1</em>");
  }

  function showLoading() {
    hideAll();
    loadingState.style.display = "flex";
  }

  function hideAll() {
    loadingState.style.display = "none";
    emptyState.style.display = "none";
    errorState.style.display = "none";
    cardsContainer.innerHTML = "";
    statsBar.innerHTML = "";
  }

  // ═══════════════════════════════════════════════
  // 비밀번호 잠금
  // ═══════════════════════════════════════════════
  const PASS_HASH = "5420dcab71e0fb6328f565ce359ed1e0e601d64b";

  function unlock() {
    const lockScreen = document.getElementById("lockScreen");
    if (lockScreen) lockScreen.classList.add("lock-screen--hidden");
    sessionStorage.setItem("auth", "1");
    init();
  }

  async function sha1(str) {
    const buf = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(str));
    return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("");
  }

  document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("lockForm");
    const input = document.getElementById("lockPassword");
    const error = document.getElementById("lockError");

    if (sessionStorage.getItem("auth") === "1") {
      unlock();
      return;
    }

    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const hash = await sha1(input.value);
        if (hash === PASS_HASH) {
          unlock();
        } else {
          error.style.display = "block";
          input.value = "";
          input.focus();
        }
      });
    }
  });
})();
