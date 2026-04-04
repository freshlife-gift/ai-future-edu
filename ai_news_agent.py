"""
AI 미래교육 지식의 창 — 뉴스 수집·분석 에이전트
=================================================
매일 오전 6:30 자동 실행:
1. 서울시교육청 오늘의 뉴스 + 네이버 뉴스 API 수집
2. KEDI + OECD + UNESCO 해외동향/정책/보고서 수집
3. CrossRef/ERIC 국내외 학술지 수집
4. Gemini 2.5 Flash 분석 → 누적 JSON 저장
"""

import os
import sys
import json
import re
import time
import logging
import smtplib
import hashlib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from difflib import SequenceMatcher

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# ─── 설정 ───
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode="w", encoding="utf-8", closefd=False)
        )
    ],
)
logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).date()
YESTERDAY = TODAY - timedelta(days=1)
TODAY_STR = str(TODAY)

# 검색 키워드 (초중고 + 대학 + 성인교육 확대)
KEYWORDS = [
    "AI교육", "AI 교육", "인공지능 교육", "인공지능교육",
    "미래교육", "AI학교", "AI 학교", "에듀테크",
    "디지털교육", "디지털 교육",
    "AI 대학", "AI 대학교육", "AI 평생교육", "AI 성인교육",
    "AI 고등교육", "AI 직업교육",
]

NEWS_QUERIES = [
    "AI교육", "인공지능 교육", "미래교육", "AI 학교", "에듀테크",
    "디지털교육", "AI 대학교육", "AI 평생학습",
]

TEAM_DUTIES = """1. AI·디지털 기반 교육혁신 운영
2. AI·디지털 활용 및 AI 융합교육
3. AI·정보(AI·SW) 교육
4. AI·디지털 리터러시 교육 활성화
5. 디지털 교육 세계화(ODA) 사업(KLIC, 첨단교실)
6.「디벗」교수학습 지원 및 디벗 정책 지원단
7. AI·디지털 기반 수업·평가혁신 전문가 연수
8. AI윤리·디지털 시민성 교육
9. AI·에듀테크 선도교사단 및 AIEDAP
10. 디지털튜터 운영
11. 신나는 AI교실 구축 및 운영"""

REGIONAL_KEYWORDS = [
    "경기", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
]

DOMAIN_SOURCE_MAP = {
    "chosun": "조선일보", "donga": "동아일보", "hani": "한겨레",
    "khan": "경향신문", "joongang": "중앙일보", "hankyung": "한국경제",
    "mk.co": "매일경제", "sedaily": "서울경제", "ytn": "YTN",
    "sbs.co": "SBS", "kbs.co": "KBS", "mbc.co": "MBC",
    "yna.co": "연합뉴스", "newsis": "뉴시스", "edaily": "이데일리",
    "etnews": "전자신문", "zdnet": "ZDNet", "bloter": "블로터",
    "hankookilbo": "한국일보", "munhwa": "문화일보", "seoul.co": "서울신문",
    "mt.co": "머니투데이", "moe.go.kr": "교육부", "sen.go.kr": "서울시교육청",
}

OUTPUT_DIR = Path("output")
CUMULATIVE_FILE = OUTPUT_DIR / "cumulative.json"
HISTORY_FILE = OUTPUT_DIR / "article_history.json"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 유틸
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def _id(title):
    return hashlib.md5(re.sub(r"\s+", "", title).encode()).hexdigest()


def _is_dup(title, seen):
    norm = re.sub(r"\s+", "", title)
    for s in seen:
        if SequenceMatcher(None, norm, s).ratio() > 0.75:
            return True
    seen.add(norm)
    return False


def _clean(html):
    return re.sub(r"<[^>]+>", "", html).strip()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1) 뉴스 수집 — ScrapMaster + 네이버 API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class NewsCollector:
    VIEWER_URL = "https://premium.scrapmaster.co.kr/server/web_viewer/main.php"
    NAVER_API = "https://openapi.naver.com/v1/search/news.json"

    def __init__(self):
        self.naver_id = os.getenv("NAVER_CLIENT_ID", "")
        self.naver_secret = os.getenv("NAVER_CLIENT_SECRET", "")

    def collect(self, target_date) -> tuple:
        articles, seen = [], set()

        # ScrapMaster
        sm = self._scrapmaster(str(target_date))
        for a in sm:
            if not _is_dup(a["title"], seen):
                articles.append(a)

        # 네이버 뉴스
        if self.naver_id:
            nv = self._naver(target_date)
            for a in nv:
                if not _is_dup(a["title"], seen):
                    articles.append(a)

        total = len(articles)
        # 키워드 필터
        filtered = [a for a in articles if any(k.lower() in a["title"].lower() for k in KEYWORDS)]
        # 지역 후순위
        filtered.sort(key=lambda a: any(r in a["title"] for r in REGIONAL_KEYWORDS))

        logger.info(f"  [뉴스] 수집: {total}건 → 키워드 필터: {len(filtered)}건")
        return total, filtered

    def _scrapmaster(self, date_str):
        articles = []
        for flag in [0, 1]:
            try:
                resp = requests.get(self.VIEWER_URL, params={
                    "userinfo": "senpr-7", "date": date_str, "flag": flag, "type": "both"
                }, headers=HDR, timeout=10)
                if resp.status_code != 200:
                    continue
                resp.encoding = "utf-8"
                soup = BeautifulSoup(resp.text, "html.parser")
                for row in soup.find_all("tr", {"height": "26"}):
                    tds = row.find_all("td")
                    if len(tds) < 5:
                        continue
                    source, title = tds[2].get_text(strip=True), tds[4].get_text(strip=True)
                    if title and source:
                        articles.append({
                            "title": title, "source": source,
                            "url": "", "author": "",
                            "published_date": date_str,
                            "body_preview": title,
                        })
            except Exception as e:
                logger.error(f"  ScrapMaster 오류: {e}")
            time.sleep(0.3)
        return articles

    def _naver(self, target_date):
        articles = []
        headers = {"X-Naver-Client-Id": self.naver_id, "X-Naver-Client-Secret": self.naver_secret}
        for q in NEWS_QUERIES:
            try:
                r = requests.get(self.NAVER_API, headers=headers,
                                 params={"query": q, "display": 100, "sort": "date"}, timeout=10)
                if r.status_code != 200:
                    continue
                for item in r.json().get("items", []):
                    title = _clean(item.get("title", ""))
                    desc = _clean(item.get("description", ""))
                    try:
                        pub = datetime.strptime(item.get("pubDate", ""), "%a, %d %b %Y %H:%M:%S %z").astimezone(KST).date()
                    except Exception:
                        continue
                    if pub != target_date:
                        continue
                    orig = item.get("originallink") or item.get("link", "")
                    source = ""
                    for frag, name in DOMAIN_SOURCE_MAP.items():
                        if frag in orig.lower():
                            source = name
                            break
                    articles.append({
                        "title": title, "url": orig,
                        "source": source or "네이버뉴스", "author": "",
                        "published_date": str(target_date),
                        "body_preview": desc[:800] or title,
                    })
                time.sleep(0.15)
            except Exception as e:
                logger.error(f"  네이버 API 오류 ({q}): {e}")
        return articles


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2) KEDI + OECD + UNESCO
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class TrendsCollector:
    KEDI_BASE = "https://edpolicy.kedi.re.kr"

    def collect_kedi(self, max_pages=3) -> list:
        articles = []
        for page in range(1, max_pages + 1):
            try:
                resp = requests.get(f"{self.KEDI_BASE}/edpolicy/board/30?pageIndex={page}", headers=HDR, timeout=10)
                if resp.status_code != 200:
                    break
                soup = BeautifulSoup(resp.text, "html.parser")
                table = soup.find("table")
                if not table:
                    break
                for row in table.find_all("tr")[1:]:
                    tds = row.find_all("td")
                    if len(tds) < 4:
                        continue
                    title = tds[1].get_text(strip=True)
                    source = tds[2].get_text(strip=True)
                    date = tds[3].get_text(strip=True)
                    a_tag = tds[1].find("a", onclick=True)
                    seq = ""
                    if a_tag:
                        m = re.search(r"view\((\d+)", a_tag.get("onclick", ""))
                        if m:
                            seq = m.group(1)
                    url = f"{self.KEDI_BASE}/edpolicy/board/30/{seq}" if seq else ""
                    articles.append({
                        "title": title, "url": url,
                        "source": source or "KEDI", "author": "",
                        "published_date": date, "body_preview": title,
                    })
                time.sleep(1)
            except Exception as e:
                logger.error(f"  KEDI 오류 (p{page}): {e}")
        logger.info(f"  [해외동향-KEDI] 수집: {len(articles)}건")
        return articles

    def collect_oecd(self) -> list:
        """OECD는 Cloudflare 차단으로 자동 수집 불가 → 참조 링크"""
        logger.info("  [해외동향-OECD] Cloudflare 차단 → 참조 링크 제공")
        return []

    def collect_unesco(self) -> list:
        articles = []
        try:
            url = "https://www.unesco.org/en/education"
            resp = requests.get(url, headers=HDR, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    text = a.get_text(strip=True)
                    href = a["href"]
                    if len(text) > 20 and any(k.lower() in text.lower() for k in ["education", "AI", "digital", "learning"]):
                        full_url = href if href.startswith("http") else f"https://www.unesco.org{href}"
                        articles.append({
                            "title": text, "url": full_url,
                            "source": "UNESCO", "author": "",
                            "published_date": TODAY_STR, "body_preview": text,
                        })
                        if len(articles) >= 10:
                            break
        except Exception as e:
            logger.error(f"  UNESCO 오류: {e}")
        logger.info(f"  [해외동향-UNESCO] 수집: {len(articles)}건")
        return articles

    def collect_kedi_policy(self, board_id, label, max_pages=2) -> list:
        articles = []
        for page in range(1, max_pages + 1):
            try:
                url = f"{self.KEDI_BASE}/edpolicy/board/{board_id}?pageIndex={page}"
                resp = requests.get(url, headers=HDR, timeout=10)
                if resp.status_code != 200:
                    break
                soup = BeautifulSoup(resp.text, "html.parser")
                # 카드 형태
                for a_tag in soup.select(f'a[href*="/board/{board_id}/"]'):
                    h4 = a_tag.find("h4")
                    if not h4:
                        continue
                    title = h4.get_text(strip=True)
                    href = a_tag.get("href", "")
                    article_url = f"{self.KEDI_BASE}{href}" if href.startswith("/") else href
                    author, pub_date = "", ""
                    for p in a_tag.find_all("p"):
                        t = p.get_text(strip=True)
                        if "집필자" in t or "연구책임자" in t:
                            author = t.split(":")[-1].strip()
                        if "발행일" in t or "출판연도" in t:
                            pub_date = t.split(":")[-1].strip()
                    articles.append({
                        "title": title, "url": article_url,
                        "source": "KEDI", "author": author,
                        "published_date": pub_date, "body_preview": title,
                    })
                # 테이블 형태
                if not articles:
                    table = soup.find("table")
                    if table:
                        for row in table.find_all("tr")[1:]:
                            tds = row.find_all("td")
                            if len(tds) < 3:
                                continue
                            title = tds[1].get_text(strip=True)
                            date = tds[-1].get_text(strip=True) if len(tds) >= 4 else ""
                            articles.append({
                                "title": title, "url": "", "source": "KEDI",
                                "author": "", "published_date": date, "body_preview": title,
                            })
                time.sleep(1)
            except Exception as e:
                logger.error(f"  KEDI board/{board_id} 오류: {e}")
        logger.info(f"  [{label}] KEDI 수집: {len(articles)}건")
        return articles


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3) 학술지 (CrossRef + ERIC) + 중복방지
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class ArticleHistory:
    def __init__(self):
        self.used = self._load()

    def _load(self):
        if HISTORY_FILE.exists():
            try:
                return json.load(open(HISTORY_FILE, "r", encoding="utf-8"))
            except Exception:
                pass
        return {"domestic": [], "international": []}

    def save(self):
        OUTPUT_DIR.mkdir(exist_ok=True)
        json.dump(self.used, open(HISTORY_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    def is_used(self, cat, key):
        return key in self.used.get(cat, [])

    def mark(self, cat, key):
        if cat not in self.used:
            self.used[cat] = []
        if key not in self.used[cat]:
            self.used[cat].append(key)
        if len(self.used[cat]) > 300:
            self.used[cat] = self.used[cat][-300:]


class AcademicCollector:
    ERIC_API = "https://api.ies.ed.gov/eric/"
    CROSSREF_API = "https://api.crossref.org/works"

    def __init__(self):
        self.history = ArticleHistory()

    def collect_international(self):
        articles, seen = [], set()
        for q in ["artificial intelligence education K-12", "AI literacy education school", "generative AI classroom teaching"]:
            try:
                r = requests.get(self.ERIC_API, params={
                    "search": q, "format": "json", "rows": 20, "peerreviewed": "T", "sort": "relevance"
                }, headers=HDR, timeout=15)
                if r.status_code != 200:
                    continue
                for doc in r.json().get("response", {}).get("docs", []):
                    title = doc.get("title", "")
                    if not title or title in seen:
                        continue
                    seen.add(title)
                    eid = doc.get("id", "")
                    if self.history.is_used("international", eid or title):
                        continue
                    author_list = doc.get("author", [])
                    src = doc.get("source", "")
                    yr = str(doc.get("publicationdateyear", ""))
                    apa = f"{', '.join(author_list[:6])} ({yr}). {title}. *{src}*." if src else f"{', '.join(author_list[:6])} ({yr}). {title}."
                    if eid:
                        apa += f" https://eric.ed.gov/?id={eid}"
                    articles.append({
                        "title": title, "url": f"https://eric.ed.gov/?id={eid}" if eid else "",
                        "source": src, "author": ", ".join(author_list[:3]),
                        "published_date": yr,
                        "body_preview": doc.get("description", "")[:1000],
                        "identifier": eid or title, "apa_citation": apa,
                    })
                time.sleep(0.3)
            except Exception as e:
                logger.error(f"  ERIC 오류: {e}")
        logger.info(f"  [해외학술지] ERIC: {len(articles)}건")
        return articles

    def collect_domestic(self):
        articles, seen = [], set()
        yesterday = str(YESTERDAY)
        for q in ["AI교육", "인공지능 교육 학교", "미래교육 디지털", "에듀테크 인공지능", "AI literacy Korea education"]:
            try:
                r = requests.get(self.CROSSREF_API, params={
                    "query": q, "rows": 20, "sort": "deposited", "order": "desc", "mailto": "edupolicy@example.com"
                }, headers=HDR, timeout=15)
                if r.status_code != 200:
                    continue
                for item in r.json().get("message", {}).get("items", []):
                    titles = item.get("title", [])
                    if not titles:
                        continue
                    title = titles[0]
                    orig = item.get("original-title", [])
                    ko = next((t for t in orig if any(0xAC00 <= ord(c) <= 0xD7A3 for c in t)), "")
                    display = ko or title
                    doi = item.get("DOI", "")
                    key = doi or title
                    if key in seen or self.history.is_used("domestic", key):
                        continue
                    seen.add(key)
                    authors = item.get("author", [])
                    apa_auth = ", ".join(f"{a.get('family','')}, {'. '.join(g[0] for g in a.get('given','').split() if g)}." for a in authors[:6] if a.get('family'))
                    journal = (item.get("container-title") or [""])[0]
                    vol = item.get("volume", "")
                    issue = item.get("issue", "")
                    dep = item.get("deposited", {}).get("date-parts", [[]])[0]
                    dep_date = "-".join(str(d) for d in dep) if dep else ""
                    pub = item.get("published-print", item.get("published-online", {}))
                    pub_parts = pub.get("date-parts", [[]])[0] if pub else []
                    yr = str(pub_parts[0]) if pub_parts else (str(dep[0]) if dep else "")
                    vol_info = f", {vol}" if vol else ""
                    iss_info = f"({issue})" if issue else ""
                    apa = f"{apa_auth} ({yr}). {display}. *{journal}*{vol_info}{iss_info}." if journal else f"{apa_auth} ({yr}). {display}."
                    if doi:
                        apa += f" https://doi.org/{doi}"
                    abstract = re.sub(r"<[^>]+>", "", item.get("abstract", ""))[:1000]
                    articles.append({
                        "title": display, "url": f"https://doi.org/{doi}" if doi else "",
                        "source": journal, "author": ", ".join(f"{a.get('given','')} {a.get('family','')}".strip() for a in authors[:3]),
                        "published_date": yr, "body_preview": abstract or display,
                        "identifier": key, "apa_citation": apa,
                        "is_yesterday": dep_date == yesterday,
                    })
                time.sleep(0.3)
            except Exception as e:
                logger.error(f"  CrossRef 오류: {e}")
        yest = [a for a in articles if a.get("is_yesterday")]
        other = [a for a in articles if not a.get("is_yesterday")]
        if yest:
            logger.info(f"  [국내학술지] 전날 업로드: {len(yest)}건")
        logger.info(f"  [국내학술지] CrossRef: {len(articles)}건")
        return yest + other if yest else other

    def mark_selected(self, cat, selected):
        for a in selected:
            self.history.mark(cat, a.get("identifier") or a.get("title", ""))
        self.history.save()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AI 분석기
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class GeminiAnalyzer:
    def __init__(self):
        self.model = None
        key = os.getenv("GEMINI_API_KEY", "")
        if key and HAS_GENAI:
            genai.configure(api_key=key)
            self.model = genai.GenerativeModel("gemini-2.5-flash")

    def analyze(self, articles, category, max_items=3):
        if not self.model or not articles:
            return []
        entries = "\n".join(
            f"---자료{i}---\n제목: {a['title']}\n출처: {a['source']}\n본문: {a.get('body_preview','')[:800]}"
            for i, a in enumerate(articles[:20])
        )
        is_academic = "학술" in category
        summary_guide = "연구 목적, 방법론, 핵심 발견/결론, 구체적 수치를 포함하여 4~6문장" if is_academic else "구체적인 사실, 수치, 정책내용을 포함하여 3~5문장"
        regional = "\n- **특정 지역(시/도) 사례는 감점(-0.5점)** (서울 제외)" if category == "뉴스기사" else ""

        prompt = f"""서울시교육청 AI미래교육팀 분석가로서, [{category}] 자료를 분석하세요.

## 평가 기준
- AI교육, 인공지능, 미래교육, 에듀테크, 디지털교육 관련성 (5점 만점)
- K-12 및 고등/성인 교육 현장 적용 가능성
- 4점 이상만 선별, 최대 {max_items}건{regional}

## 요약 작성
- {summary_guide}으로 작성
- **일반적 서술 금지**: 구체적인 내용, 수치, 사례, 정책명 등을 반드시 포함
- 핵심 결과와 의미가 명확히 드러나도록 작성

## AI미래교육팀 업무
{TEAM_DUTIES}

## 자료
{entries}

## 시사점 작성 형식
- [관련업무] 해당 업무를 간략히 명시
- [정책방향] 마련해야 할 구체적 정책 방향
- [참고사항] 정책 추진 시 참고할 핵심 포인트

## JSON만 출력 (마크다운 코드블록 없이)
[{{"index":0,"score":4.5,"summary":"구체적 요약","implications":"[관련업무] 업무명\\n[정책방향] 내용\\n[참고사항] 내용"}}]"""

        try:
            resp = self.model.generate_content(prompt)
            m = re.search(r"\[.*\]", resp.text.strip(), re.DOTALL)
            if not m:
                return []
            results = json.loads(m.group())
            analyzed = []
            for r in sorted(results, key=lambda x: x.get("score", 0), reverse=True):
                idx = r.get("index", -1)
                if idx < 0 or idx >= len(articles) or r.get("score", 0) < 4.0:
                    continue
                a = articles[idx]
                entry = {
                    "title": a["title"], "url": a.get("url", ""),
                    "source": a["source"], "author": a.get("author", ""),
                    "published_date": a.get("published_date", ""),
                    "summary": r.get("summary", ""), "score": round(r.get("score", 0), 1),
                    "implications": r.get("implications", ""),
                    "collected_date": TODAY_STR,
                }
                if a.get("apa_citation"):
                    entry["apa_citation"] = a["apa_citation"]
                if a.get("identifier"):
                    entry["identifier"] = a["identifier"]
                analyzed.append(entry)
                if len(analyzed) >= max_items:
                    break
            logger.info(f"  [{category}] 분석: {len(analyzed)}건 선별")
            return analyzed
        except Exception as e:
            logger.error(f"  [{category}] Gemini 오류: {e}")
            return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 이메일
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class EmailSender:
    def __init__(self):
        self.user = os.getenv("GMAIL_USER", "")
        self.pw = os.getenv("GMAIL_APP_PASSWORD", "")
        self.site = os.getenv("SITE_URL", "")

    def send(self, date_str, counts):
        if not self.user or not self.pw:
            logger.warning("이메일 설정 없음 -> 건너뜀")
            return False
        total = sum(counts.values())
        if total == 0:
            return False
        html = f"""<html><body style="font-family:sans-serif;padding:20px">
<h2 style="color:#4f46e5">AI 미래교육 지식의 창</h2>
<p>AI 미래교육 지식의 창에 자료가 업로드 되었습니다.</p>
<p>{date_str} 기준 총 {total}건의 새 자료가 추가되었습니다.</p>
<p><a href="{self.site}" style="color:#4f46e5">웹페이지에서 보기</a></p>
</body></html>"""
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "AI 미래교육 지식의 창에 자료가 업로드 되었습니다."
            msg["From"] = self.user
            msg["To"] = self.user
            msg.attach(MIMEText(html, "html", "utf-8"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
                s.login(self.user, self.pw)
                s.sendmail(self.user, [self.user], msg.as_string())
            logger.info(f"  이메일 발송 완료 -> {self.user}")
            return True
        except Exception as e:
            logger.error(f"  이메일 오류: {e}")
            return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 누적 데이터 관리
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def load_cumulative():
    if CUMULATIVE_FILE.exists():
        try:
            return json.load(open(CUMULATIVE_FILE, "r", encoding="utf-8"))
        except Exception:
            pass
    return {"last_updated": "", "sections": {
        "news": [], "global_trends": [], "policy": [], "reports": [],
        "academic_domestic": [], "academic_international": [],
    }}


def merge_cumulative(existing, new_items, section, max_daily=5):
    """새 항목을 하루 최대 max_daily건 추가. 기존 자료 유지. NEW는 오늘 것만."""
    current = existing.get("sections", {}).get(section, [])
    existing_ids = {_id(a["title"]) for a in current}

    # 기존 항목 is_new 해제 (오늘 것만 NEW)
    for item in current:
        if item.get("collected_date") != TODAY_STR:
            item["is_new"] = False

    # 신규 항목 추가 (하루 최대 max_daily건)
    added = 0
    for item in new_items:
        if added >= max_daily:
            break
        item_id = _id(item["title"])
        if item_id not in existing_ids:
            item["is_new"] = True
            current.insert(0, item)
            existing_ids.add(item_id)
            added += 1

    existing["sections"][section] = current
    return added


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main():
    logger.info("=" * 60)
    logger.info(f"  AI 미래교육 지식의 창 | {TODAY}")
    logger.info("=" * 60)

    OUTPUT_DIR.mkdir(exist_ok=True)
    news_col = NewsCollector()
    trends_col = TrendsCollector()
    acad_col = AcademicCollector()
    analyzer = GeminiAnalyzer()

    # 1) 뉴스
    logger.info("[1/6] 뉴스 수집...")
    news_total, news_raw = news_col.collect(TODAY)

    # 2) 해외동향 (KEDI + OECD + UNESCO)
    logger.info("[2/6] 해외동향 수집...")
    trends_raw = trends_col.collect_kedi()
    trends_raw += trends_col.collect_oecd()
    trends_raw += trends_col.collect_unesco()

    # 3) 정책
    logger.info("[3/6] 정책 수집...")
    policy_raw = trends_col.collect_kedi_policy(45, "정책")

    # 4) 보고서
    logger.info("[4/6] 연구보고서 수집...")
    reports_raw = trends_col.collect_kedi_policy(47, "연구보고서")

    # 5) 국내학술지
    logger.info("[5/6] 국내학술지 수집...")
    domestic_raw = acad_col.collect_domestic()

    # 6) 해외학술지
    logger.info("[6/6] 해외학술지 수집...")
    international_raw = acad_col.collect_international()

    # AI 분석 (배치 최적화: 호출 횟수 최소화)
    logger.info("Gemini 분석 중 (배치 모드)...")
    # 1차 호출: 뉴스 + 해외동향 + 정책 + 보고서 통합
    all_general = []
    labels = []
    for name, raw, mx in [("뉴스기사", news_raw, 3), ("해외동향", trends_raw, 3),
                           ("정책", policy_raw, 3), ("연구보고서", reports_raw, 3)]:
        if raw:
            all_general.append((name, raw, mx))
            labels.append(name)

    news_out, trends_out, policy_out, reports_out = [], [], [], []
    for name, raw, mx in all_general:
        result = analyzer.analyze(raw, name, mx)
        if name == "뉴스기사":
            news_out = result
        elif name == "해외동향":
            trends_out = result
        elif name == "정책":
            policy_out = result
        elif name == "연구보고서":
            reports_out = result
        time.sleep(1)

    # 2차 호출: 학술지
    domestic_out = analyzer.analyze(domestic_raw, "국내학술지", 3)
    time.sleep(1)
    international_out = analyzer.analyze(international_raw, "해외학술지", 2)

    acad_col.mark_selected("domestic", domestic_out)
    acad_col.mark_selected("international", international_out)

    # 누적 데이터 병합
    cumul = load_cumulative()
    new_counts = {}
    for section, items in [
        ("news", news_out), ("global_trends", trends_out),
        ("policy", policy_out), ("reports", reports_out),
        ("academic_domestic", domestic_out), ("academic_international", international_out),
    ]:
        new_counts[section] = merge_cumulative(cumul, items, section)

    cumul["last_updated"] = datetime.now(KST).isoformat()
    with open(CUMULATIVE_FILE, "w", encoding="utf-8") as f:
        json.dump(cumul, f, ensure_ascii=False, indent=2)
    logger.info(f"누적 데이터 저장 완료")

    # 일별 백업도 저장
    daily = {"date": TODAY_STR, "updated_at": cumul["last_updated"],
             "new_counts": new_counts,
             "sections": {k: [a for a in v if a.get("collected_date") == TODAY_STR]
                          for k, v in cumul["sections"].items()}}
    with open(OUTPUT_DIR / f"{TODAY}.json", "w", encoding="utf-8") as f:
        json.dump(daily, f, ensure_ascii=False, indent=2)

    # 이메일
    EmailSender().send(TODAY_STR, new_counts)

    total = sum(new_counts.values())
    logger.info(f"  완료! 오늘 추가: {total}건")
    for k, v in new_counts.items():
        logger.info(f"     {k}: +{v}건")
    return cumul


if __name__ == "__main__":
    main()
