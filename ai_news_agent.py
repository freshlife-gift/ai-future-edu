"""
AI 미래교육 지식의 창 — 뉴스 수집·분석 에이전트
=================================================
매일 오전 6:30 자동 실행되어:
1. 서울시교육청 오늘의 뉴스(ScrapMaster)에서 당일 뉴스 수집
2. KEDI 교육정책네트워크에서 해외동향/정책/연구보고서 수집
3. ERIC·KCI에서 국내외 학술지 수집
4. Gemini 2.5 Flash로 관련성 평가 + 요약 + 시사점 생성
5. JSON 파일 저장 + 이메일 알림
"""

import os
import sys
import json
import re
import time
import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# ─── 설정 ───────────────────────────────────────────────
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

# 검색 키워드 풀
KEYWORDS = [
    "AI교육", "AI 교육", "인공지능 교육", "인공지능교육",
    "미래교육", "AI학교", "AI 학교", "에듀테크",
    "디지털교육", "디지털 교육",
]

# AI미래교육팀 담당업무 (시사점 작성 기준)
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

# 지역 키워드 (후순위 처리용)
REGIONAL_KEYWORDS = [
    "경기", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
    "경기도", "부산시", "대구시", "인천시", "광주시", "대전시", "울산시",
    "세종시", "강원도", "충청북도", "충청남도", "전라북도", "전라남도",
    "경상북도", "경상남도", "제주도", "제주특별자치도",
]

OUTPUT_DIR = Path("output")
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1) 서울시교육청 오늘의 뉴스 수집 (ScrapMaster)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class SenNewsCollector:
    """서울시교육청 ScrapMaster 오늘의 뉴스 스크래핑"""

    VIEWER_URL = "https://premium.scrapmaster.co.kr/server/web_viewer/main.php"

    @staticmethod
    def _has_keyword(title: str) -> bool:
        text = title.lower()
        return any(kw.lower() in text for kw in KEYWORDS)

    @staticmethod
    def _is_regional(title: str) -> bool:
        return any(rk in title for rk in REGIONAL_KEYWORDS)

    def _fetch_edition(self, date_str: str, flag: int) -> list:
        """조간(flag=0) 또는 석간(flag=1) 기사 목록 추출"""
        articles = []
        cate_s = 0

        for _ in range(10):  # 최대 10페이지
            params = {
                "userinfo": "senpr-7",
                "date": date_str,
                "flag": flag,
                "type": "both",
            }
            if cate_s > 0:
                params["cate_s"] = cate_s

            try:
                resp = requests.get(
                    self.VIEWER_URL, params=params, headers=REQUEST_HEADERS, timeout=10
                )
                if resp.status_code != 200:
                    break
                resp.encoding = "utf-8"
                soup = BeautifulSoup(resp.text, "html.parser")

                rows = soup.find_all("tr", {"height": "26"})
                if not rows:
                    break

                for row in rows:
                    tds = row.find_all("td")
                    if len(tds) < 5:
                        continue
                    source = tds[2].get_text(strip=True)
                    title = tds[4].get_text(strip=True)
                    if title and source:
                        articles.append({
                            "title": title,
                            "source": source,
                            "published_date": date_str,
                            "url": f"{self.VIEWER_URL}?userinfo=senpr-7&date={date_str}&flag={flag}&type=both",
                            "body_preview": title,
                        })

                # 다음 페이지 확인
                next_link = soup.find("img", src=re.compile(r"icon_tab_next"))
                if next_link and next_link.parent and next_link.parent.get("href"):
                    href = next_link.parent["href"]
                    m = re.search(r"cate_s=(\d+)", href)
                    if m:
                        cate_s = int(m.group(1))
                        continue
                break
            except Exception as e:
                logger.error(f"  ScrapMaster 스크래핑 오류: {e}")
                break

        return articles

    def collect(self, target_date) -> tuple:
        """당일 뉴스 수집 → 키워드 필터링, (전체수, 필터링된 기사 목록) 반환"""
        date_str = str(target_date)
        all_articles = []

        for flag in [0, 1]:  # 조간, 석간
            edition = self._fetch_edition(date_str, flag)
            all_articles.extend(edition)
            time.sleep(0.3)

        total = len(all_articles)

        # 키워드 필터링
        filtered = [a for a in all_articles if self._has_keyword(a["title"])]

        # 지역 뉴스 후순위 정렬 (비지역 → 지역 순)
        filtered.sort(key=lambda a: self._is_regional(a["title"]))

        logger.info(f"  [뉴스] ScrapMaster 수집: {total}건 → 키워드 필터: {len(filtered)}건")
        return total, filtered


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2) KEDI 교육정책네트워크 수집
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class KEDICollector:
    """KEDI 교육정책네트워크 (edpolicy.kedi.re.kr) 스크래핑"""

    BASE_URL = "https://edpolicy.kedi.re.kr"
    BOARDS = {
        "global_trends": {"id": 30, "label": "해외교육동향"},
        "policy": {"id": 45, "label": "이슈페이퍼/정책"},
        "reports": {"id": 47, "label": "연구보고서"},
    }

    def _scrape_board30(self, max_pages: int = 3) -> list:
        """해외교육동향 (테이블 형태)"""
        articles = []
        for page in range(1, max_pages + 1):
            url = f"{self.BASE_URL}/edpolicy/board/30?pageIndex={page}"
            try:
                resp = requests.get(url, headers=REQUEST_HEADERS, timeout=10)
                if resp.status_code != 200:
                    logger.warning(f"  KEDI board/30 HTTP {resp.status_code} (p{page})")
                    break
                soup = BeautifulSoup(resp.text, "html.parser")
                table = soup.find("table")
                if not table:
                    break
                rows = table.find_all("tr")[1:]  # 헤더 스킵
                for row in rows:
                    tds = row.find_all("td")
                    if len(tds) < 4:
                        continue
                    title_td = tds[1]
                    a_tag = title_td.find("a", onclick=True)
                    title = title_td.get_text(strip=True)
                    source = tds[2].get_text(strip=True)
                    date = tds[3].get_text(strip=True)

                    # onclick에서 seq 추출
                    seq = ""
                    if a_tag:
                        m = re.search(r"view\((\d+)", a_tag.get("onclick", ""))
                        if m:
                            seq = m.group(1)

                    article_url = f"{self.BASE_URL}/edpolicy/board/30/{seq}" if seq else url

                    articles.append({
                        "title": title,
                        "url": article_url,
                        "source": source or "KEDI 교육정책네트워크",
                        "author": "",
                        "published_date": date,
                        "body_preview": title,
                    })
                time.sleep(1)  # IP 차단 방지
            except Exception as e:
                logger.error(f"  KEDI board/30 스크래핑 오류 (p{page}): {e}")
        return articles

    def _scrape_board_cards(self, board_id: int, label: str, max_pages: int = 2) -> list:
        """이슈페이퍼(45) / 연구보고서(47) — 카드 또는 테이블 형태"""
        articles = []
        for page in range(1, max_pages + 1):
            url = f"{self.BASE_URL}/edpolicy/board/{board_id}?pageIndex={page}"
            try:
                resp = requests.get(url, headers=REQUEST_HEADERS, timeout=10)
                if resp.status_code != 200:
                    logger.warning(f"  KEDI board/{board_id} HTTP {resp.status_code} (p{page})")
                    break
                soup = BeautifulSoup(resp.text, "html.parser")

                # 카드 형태: a > h4
                links = soup.select(f'a[href*="/board/{board_id}/"]')
                for a_tag in links:
                    h4 = a_tag.find("h4")
                    if not h4:
                        continue
                    title = h4.get_text(strip=True)
                    href = a_tag.get("href", "")
                    article_url = f"{self.BASE_URL}{href}" if href.startswith("/") else href

                    author = ""
                    pub_date = ""
                    for p_tag in a_tag.find_all("p"):
                        text = p_tag.get_text(strip=True)
                        if "연구책임자" in text or "집필자" in text:
                            author = text.split(":")[-1].strip()
                        if "발행일" in text:
                            pub_date = text.split(":")[-1].strip()
                        if "출판연도" in text and not pub_date:
                            pub_date = text.split(":")[-1].strip()

                    articles.append({
                        "title": title,
                        "url": article_url,
                        "source": "KEDI 교육정책네트워크",
                        "author": author,
                        "published_date": pub_date,
                        "body_preview": title,
                    })

                # 카드가 없으면 테이블 형태 시도
                if not links:
                    table = soup.find("table")
                    if table:
                        for row in table.find_all("tr")[1:]:
                            tds = row.find_all("td")
                            if len(tds) < 3:
                                continue
                            title = tds[1].get_text(strip=True)
                            date = tds[-1].get_text(strip=True) if len(tds) >= 4 else ""
                            a_tag = tds[1].find("a", onclick=True)
                            seq = ""
                            if a_tag:
                                m = re.search(r"view\((\d+)", a_tag.get("onclick", ""))
                                if m:
                                    seq = m.group(1)
                            article_url = f"{self.BASE_URL}/edpolicy/board/{board_id}/{seq}" if seq else url
                            articles.append({
                                "title": title,
                                "url": article_url,
                                "source": "KEDI 교육정책네트워크",
                                "author": "",
                                "published_date": date,
                                "body_preview": title,
                            })

                time.sleep(1)  # IP 차단 방지
            except Exception as e:
                logger.error(f"  KEDI board/{board_id} 스크래핑 오류 (p{page}): {e}")
        return articles

    def _extract_body(self, url: str) -> str:
        """상세 페이지에서 본문 추출 (토큰 절약: 최대 1000자)"""
        try:
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=10)
            if resp.status_code != 200:
                return ""
            soup = BeautifulSoup(resp.text, "html.parser")
            content = soup.find("div", class_=re.compile(r"content|view|detail|body", re.I))
            if content:
                return content.get_text(strip=True)[:1000]
            tag = soup.find("meta", property="og:description")
            if tag:
                return tag.get("content", "")[:1000]
        except Exception:
            pass
        return ""

    def collect(self, category: str) -> tuple:
        """카테고리별 수집 → (전체수, 기사목록) 반환"""
        info = self.BOARDS[category]
        board_id = info["id"]
        label = info["label"]

        if board_id == 30:
            articles = self._scrape_board30()
        else:
            articles = self._scrape_board_cards(board_id, label)

        total = len(articles)

        # 상세 본문 추출 (상위 10건만, 토큰 절약)
        for a in articles[:10]:
            if a["url"] and a["body_preview"] == a["title"]:
                body = self._extract_body(a["url"])
                if body:
                    a["body_preview"] = body
                time.sleep(0.2)

        logger.info(f"  [{label}] KEDI 수집: {total}건")
        return total, articles


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3) 학술지 수집 (ERIC + CrossRef)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class ArticleHistory:
    """사용된 학술 문헌 이력 관리 (중복 방지)"""

    HISTORY_FILE = OUTPUT_DIR / "article_history.json"

    def __init__(self):
        self.used = self._load()

    def _load(self) -> dict:
        if self.HISTORY_FILE.exists():
            try:
                with open(self.HISTORY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"domestic": [], "international": []}

    def save(self):
        OUTPUT_DIR.mkdir(exist_ok=True)
        with open(self.HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.used, f, ensure_ascii=False, indent=2)

    def is_used(self, category: str, doi_or_title: str) -> bool:
        return doi_or_title in self.used.get(category, [])

    def mark_used(self, category: str, doi_or_title: str):
        if category not in self.used:
            self.used[category] = []
        if doi_or_title not in self.used[category]:
            self.used[category].append(doi_or_title)
        # 최대 300건 유지
        if len(self.used[category]) > 300:
            self.used[category] = self.used[category][-300:]


class AcademicCollector:
    """국내학술지(CrossRef) · 해외학술지(ERIC) 수집"""

    ERIC_API = "https://api.ies.ed.gov/eric/"
    CROSSREF_API = "https://api.crossref.org/works"

    def __init__(self):
        self.history = ArticleHistory()

    def collect_international(self) -> list:
        """ERIC API로 해외 학술지 검색 (AI + K-12 교육)"""
        queries = [
            "artificial intelligence education K-12",
            "AI literacy education school",
            "generative AI classroom teaching",
        ]
        all_articles = []
        seen_titles = set()

        for query in queries:
            try:
                params = {
                    "search": query,
                    "format": "json",
                    "rows": 20,
                    "peerreviewed": "T",
                    "sort": "relevance",
                    "start": 0,
                }
                resp = requests.get(self.ERIC_API, params=params, headers=REQUEST_HEADERS, timeout=15)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                docs = data.get("response", {}).get("docs", [])

                for doc in docs:
                    title = doc.get("title", "")
                    if not title or title in seen_titles:
                        continue
                    seen_titles.add(title)

                    eric_id = doc.get("id", "")
                    url = f"https://eric.ed.gov/?id={eric_id}" if eric_id else ""
                    identifier = eric_id or title

                    # 중복 체크
                    if self.history.is_used("international", identifier):
                        continue

                    author_list = doc.get("author", [])
                    author_str = ", ".join(author_list[:3])
                    pub_year = str(doc.get("publicationdateyear", ""))
                    source = doc.get("source", "")

                    # APA 인용 생성
                    apa_authors = ", ".join(author_list[:6])
                    if len(author_list) > 6:
                        apa_authors += f", ... {author_list[-1]}"
                    apa_citation = f"{apa_authors} ({pub_year}). {title}. *{source}*." if source else f"{apa_authors} ({pub_year}). {title}."
                    if eric_id:
                        apa_citation += f" https://eric.ed.gov/?id={eric_id}"

                    all_articles.append({
                        "title": title,
                        "url": url,
                        "source": source,
                        "author": author_str,
                        "published_date": pub_year,
                        "body_preview": doc.get("description", "")[:1000],
                        "identifier": identifier,
                        "apa_citation": apa_citation,
                    })
                time.sleep(0.3)
            except Exception as e:
                logger.error(f"  ERIC API 오류: {e}")

        logger.info(f"  [해외학술지] ERIC 수집: {len(all_articles)}건 (미사용)")
        return all_articles

    def collect_domestic(self) -> list:
        """CrossRef API로 국내 학술지 검색 (AI + 교육)"""
        queries = [
            "AI교육",
            "인공지능 교육 학교",
            "미래교육 디지털",
            "에듀테크 인공지능",
            "AI literacy Korea education",
        ]
        all_articles = []
        seen_dois = set()
        yesterday = str(YESTERDAY)

        for query in queries:
            try:
                params = {
                    "query": query,
                    "rows": 20,
                    "sort": "deposited",
                    "order": "desc",
                    "mailto": "edupolicy@example.com",
                }
                resp = requests.get(
                    self.CROSSREF_API, params=params, headers=REQUEST_HEADERS, timeout=15
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                items = data.get("message", {}).get("items", [])

                for item in items:
                    titles = item.get("title", [])
                    if not titles:
                        continue
                    title = titles[0]
                    # 한글 제목 우선 (original-title 필드)
                    orig_titles = item.get("original-title", [])
                    ko_title = ""
                    for ot in orig_titles:
                        if any(ord(c) >= 0xAC00 and ord(c) <= 0xD7A3 for c in ot):
                            ko_title = ot
                            break
                    display_title = ko_title or title

                    doi = item.get("DOI", "")
                    if doi in seen_dois or (not doi and title in seen_dois):
                        continue
                    seen_dois.add(doi or title)

                    identifier = doi or title
                    if self.history.is_used("domestic", identifier):
                        continue

                    # 저자 (APA: 성, 이름 이니셜)
                    authors = item.get("author", [])
                    author_str = ", ".join(
                        f"{a.get('given', '')} {a.get('family', '')}".strip()
                        for a in authors[:3]
                    )
                    # APA 저자 형식: 성, 이름이니셜.
                    apa_authors = []
                    for a in authors[:6]:
                        family = a.get("family", "")
                        given = a.get("given", "")
                        if family and given:
                            initials = ". ".join(g[0] for g in given.split() if g) + "."
                            apa_authors.append(f"{family}, {initials}")
                        elif family:
                            apa_authors.append(family)
                    if len(authors) > 6:
                        apa_authors = apa_authors[:6] + ["... " + apa_authors[-1]]
                    apa_author_str = ", ".join(apa_authors) if apa_authors else ""

                    # 학술지명
                    journal = (item.get("container-title") or [""])[0]
                    volume = item.get("volume", "")
                    issue = item.get("issue", "")
                    pages = item.get("page", "")

                    # 날짜
                    deposited = item.get("deposited", {}).get("date-parts", [[]])[0]
                    dep_date = "-".join(str(d) for d in deposited) if deposited else ""
                    published = item.get("published-print", item.get("published-online", {}))
                    pub_parts = published.get("date-parts", [[]])[0] if published else []
                    pub_date = "-".join(str(d) for d in pub_parts) if pub_parts else ""
                    pub_year = str(pub_parts[0]) if pub_parts else (str(deposited[0]) if deposited else "")

                    # APA 인용 생성
                    apa_parts = []
                    if apa_author_str:
                        apa_parts.append(apa_author_str)
                    apa_parts.append(f"({pub_year})." if pub_year else "(n.d.).")
                    apa_parts.append(f"{display_title}.")
                    if journal:
                        vol_info = f", {volume}" if volume else ""
                        issue_info = f"({issue})" if issue else ""
                        page_info = f", {pages}" if pages else ""
                        apa_parts.append(f"*{journal}*{vol_info}{issue_info}{page_info}.")
                    if doi:
                        apa_parts.append(f"https://doi.org/{doi}")
                    apa_citation = " ".join(apa_parts)

                    # 초록
                    abstract = item.get("abstract", "")
                    if abstract:
                        abstract = re.sub(r"<[^>]+>", "", abstract)[:1000]

                    url = f"https://doi.org/{doi}" if doi else ""

                    all_articles.append({
                        "title": display_title,
                        "original_title": title if ko_title else "",
                        "url": url,
                        "source": journal,
                        "author": author_str,
                        "published_date": pub_year or pub_date or dep_date,
                        "deposited_date": dep_date,
                        "body_preview": abstract or display_title,
                        "identifier": identifier,
                        "is_yesterday": dep_date == yesterday,
                        "apa_citation": apa_citation,
                    })
                time.sleep(0.3)
            except Exception as e:
                logger.error(f"  CrossRef API 오류 ({query}): {e}")

        # 전날 업로드 자료 우선, 그 외는 관련성/최신순 정렬
        yesterday_articles = [a for a in all_articles if a.get("is_yesterday")]
        other_articles = [a for a in all_articles if not a.get("is_yesterday")]

        if yesterday_articles:
            logger.info(f"  [국내학술지] 전날 업로드: {len(yesterday_articles)}건")
            result = yesterday_articles + other_articles
        else:
            logger.info(f"  [국내학술지] 전날 업로드 없음 → 미사용 문헌 중 선별")
            result = other_articles

        logger.info(f"  [국내학술지] CrossRef 수집: {len(result)}건 (미사용)")
        return result

    def mark_selected(self, category: str, selected: list):
        """선별된 문헌을 이력에 기록"""
        for article in selected:
            identifier = article.get("identifier") or article.get("title", "")
            self.history.mark_used(category, identifier)
        self.history.save()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AI 분석기
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class GeminiAnalyzer:
    """Gemini 2.5 Flash 배치 분석"""

    def __init__(self):
        self.model = None
        api_key = os.getenv("GEMINI_API_KEY", "")
        if api_key and HAS_GENAI:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel("gemini-2.5-flash")
        else:
            logger.warning("Gemini API를 사용할 수 없습니다.")

    def analyze_news(self, articles: list) -> list:
        """뉴스 기사 분석 — 4점 이상, 최대 3건, 지역 사례 후순위"""
        if not self.model or not articles:
            return []

        entries = "\n".join(
            f"---기사{i}---\n제목: {a['title']}\n출처: {a['source']}\n본문: {a.get('body_preview', '')[:800]}"
            for i, a in enumerate(articles[:20])
        )

        prompt = f"""서울시교육청 AI미래교육팀 뉴스 분석가로서, 아래 뉴스를 분석하세요.

## 평가 기준
- 관련성: AI교육, 인공지능 교육, 미래교육, 에듀테크, 디지털교육 관련성 (5점 만점)
- K-12 교육 현장 적용 가능성
- 4점 이상만 선별, 최대 3건
- **특정 지역(시/도) 사례는 감점(-0.5점)하여 후순위 처리** (서울 제외)

## AI미래교육팀 업무
{TEAM_DUTIES}

## 자료
{entries}

## 시사점 작성 형식
- 관련 업무를 간략히 명시
- 마련해야 할 정책 방향 제시
- 정책 추진 시 참고사항 포함
- 핵심적이고 실행 가능한 내용 중심으로 작성

## JSON만 출력 (마크다운 코드블록 없이, 순수 JSON 배열만)
[{{"index":0,"score":4.5,"summary":"3~5문장 요약","implications":"[관련업무] 업무명\\n[정책방향] 내용\\n[참고사항] 내용"}}]"""

        return self._call_gemini(prompt, articles, "뉴스", max_items=3)

    def analyze_kedi(self, articles: list, category: str) -> list:
        """KEDI 자료 분석 — 4점 이상, 최대 3건"""
        if not self.model or not articles:
            return []

        entries = "\n".join(
            f"---자료{i}---\n제목: {a['title']}\n출처: {a['source']}\n본문: {a.get('body_preview', '')[:800]}"
            for i, a in enumerate(articles[:15])
        )

        prompt = f"""서울시교육청 AI미래교육팀 정책 분석가로서, 아래 [{category}] 자료를 분석하세요.

## 평가 기준
- AI교육, 인공지능, 미래교육, 에듀테크, 디지털교육과의 관련성 (5점 만점)
- K-12 교육 현장 적용 가능성
- 4점 이상만 선별, 최대 3건

## AI미래교육팀 업무
{TEAM_DUTIES}

## 자료
{entries}

## 시사점 작성 형식
- 관련 업무를 간략히 명시
- 마련해야 할 정책 방향 제시
- 정책 추진 시 참고사항 포함
- 핵심적이고 실행 가능한 내용 중심으로 작성

## JSON만 출력 (마크다운 코드블록 없이, 순수 JSON 배열만)
[{{"index":0,"score":4.5,"summary":"3~5문장 요약","implications":"[관련업무] 업무명\\n[정책방향] 내용\\n[참고사항] 내용"}}]"""

        return self._call_gemini(prompt, articles, category, max_items=3)

    def analyze_academic(self, articles: list, category: str, max_items: int = 2) -> list:
        """학술지 분석 — 핵심내용 + 시사점"""
        if not self.model or not articles:
            return []

        entries = "\n".join(
            f"---논문{i}---\n제목: {a['title']}\n저자: {a.get('author', '')}\n"
            f"학술지: {a['source']}\n초록: {a.get('body_preview', '')[:800]}"
            for i, a in enumerate(articles[:20])
        )

        prompt = f"""서울시교육청 AI미래교육팀 학술 분석가로서, 아래 [{category}] 학술논문을 분석하세요.

## 선정 기준
- AI교육, 인공지능 교육, 미래교육, 에듀테크, 디지털교육 키워드와의 직접적 관련성
- 초·중·고(K-12) 교육과의 직접적 관련성
- 출처의 정확성, 신뢰성, 인용률이 높은 문헌 우선
- **상위 수준의 문헌 최대 {max_items}건만 선정**

## 요약 작성 시 주의사항
- **연구결과의 핵심이 잘 드러나도록** 요약할 것
- 연구 목적, 주요 방법론, 핵심 발견/결론을 포함하여 4~6문장으로 작성
- 구체적인 수치나 결과가 있다면 반드시 포함

## AI미래교육팀 업무
{TEAM_DUTIES}

## 자료
{entries}

## 시사점 작성 형식
- 관련 업무를 간략히 명시
- 마련해야 할 정책 방향 제시
- 정책 추진 시 참고사항 포함
- 핵심적이고 실행 가능한 내용 중심으로 작성

## JSON만 출력 (마크다운 코드블록 없이, 순수 JSON 배열만)
[{{"index":0,"score":4.5,"summary":"연구결과 핵심내용 4~6문장 요약","implications":"[관련업무] 업무명\\n[정책방향] 내용\\n[참고사항] 내용"}}]"""

        return self._call_gemini(prompt, articles, category, max_items=max_items)

    def _call_gemini(self, prompt: str, articles: list, label: str, max_items: int) -> list:
        """Gemini API 호출 공통"""
        try:
            resp = self.model.generate_content(prompt)
            text = resp.text.strip()
            m = re.search(r"\[.*\]", text, re.DOTALL)
            if not m:
                logger.error(f"  [{label}] JSON 파싱 실패")
                return []
            results = json.loads(m.group())

            analyzed = []
            for r in sorted(results, key=lambda x: x.get("score", 0), reverse=True):
                idx = r.get("index", -1)
                if idx < 0 or idx >= len(articles):
                    continue
                if r.get("score", 0) < 4.0:
                    continue
                a = articles[idx]
                entry = {
                    "title": a["title"],
                    "url": a.get("url", ""),
                    "source": a["source"],
                    "author": a.get("author", ""),
                    "published_date": a.get("published_date", ""),
                    "summary": r.get("summary", ""),
                    "score": round(r.get("score", 0), 1),
                    "implications": r.get("implications", ""),
                }
                if a.get("apa_citation"):
                    entry["apa_citation"] = a["apa_citation"]
                if a.get("identifier"):
                    entry["identifier"] = a["identifier"]
                analyzed.append(entry)
                if len(analyzed) >= max_items:
                    break
            logger.info(f"  [{label}] 분석 완료: {len(analyzed)}건 선별")
            return analyzed

        except Exception as e:
            logger.error(f"  [{label}] Gemini 분석 오류: {e}")
            return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 이메일 발송
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
class EmailSender:
    """Gmail SMTP 알림"""

    def __init__(self):
        self.user = os.getenv("GMAIL_USER", "")
        self.pw = os.getenv("GMAIL_APP_PASSWORD", "")
        self.site = os.getenv("SITE_URL", "")

    def send(self, date_str: str, counts: dict) -> bool:
        if not self.user or not self.pw:
            logger.warning("이메일 설정 없음 -> 알림 건너뜀")
            return False

        total = sum(counts.values())
        rows = "".join(
            f'<tr><td style="padding:8px 16px;border:1px solid #e5e7eb">{icon} {name}</td>'
            f'<td style="padding:8px 16px;border:1px solid #e5e7eb;text-align:center">{cnt}건</td></tr>'
            for icon, name, cnt in [
                ("📰", "뉴스기사", counts.get("news", 0)),
                ("🌏", "해외동향", counts.get("global_trends", 0)),
                ("📋", "정책", counts.get("policy", 0)),
                ("📚", "연구보고서", counts.get("reports", 0)),
                ("📖", "국내학술지", counts.get("academic_domestic", 0)),
                ("🌐", "해외학술지", counts.get("academic_international", 0)),
            ]
        )

        html = f"""<html><body style="font-family:'Noto Sans KR',sans-serif;padding:20px">
<h2 style="color:#4f46e5">AI 미래교육 지식의 창</h2>
<p><strong>{date_str}</strong> 자료가 업데이트되었습니다. (총 {total}건)</p>
<table style="border-collapse:collapse;margin:16px 0">
<tr style="background:#f3f4f6"><th style="padding:8px 16px;border:1px solid #e5e7eb">카테고리</th>
<th style="padding:8px 16px;border:1px solid #e5e7eb">건수</th></tr>
{rows}</table>
<p><a href="{self.site}" style="color:#4f46e5">웹페이지에서 보기</a></p>
<hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0">
<p style="color:#9ca3af;font-size:12px">서울특별시교육청 창의미래교육과 AI미래교육팀<br>
본 이메일은 자동 발송되었습니다.</p></body></html>"""

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[AI 미래교육 지식의 창] {date_str} 업데이트 완료"
            msg["From"] = self.user
            msg["To"] = self.user
            msg.attach(MIMEText(html, "html", "utf-8"))
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
                s.login(self.user, self.pw)
                s.sendmail(self.user, [self.user], msg.as_string())
            logger.info(f"  알림 이메일 발송 완료 -> {self.user}")
            return True
        except Exception as e:
            logger.error(f"  이메일 발송 실패: {e}")
            return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 메인 실행
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def main():
    logger.info("=" * 60)
    logger.info("  AI 미래교육 지식의 창 -- 수집/분석 에이전트")
    logger.info(f"  오늘: {TODAY}  |  어제: {YESTERDAY}")
    logger.info("=" * 60)

    OUTPUT_DIR.mkdir(exist_ok=True)
    sen_collector = SenNewsCollector()
    kedi_collector = KEDICollector()
    academic_collector = AcademicCollector()
    analyzer = GeminiAnalyzer()

    # ── 1) 뉴스 수집 (서울시교육청 오늘의 뉴스) ──
    logger.info("[1/6] 뉴스기사 수집 (서울시교육청 오늘의 뉴스)...")
    news_total, news_raw = sen_collector.collect(TODAY)

    # ── 2) 해외동향 수집 (KEDI) ──
    logger.info("[2/6] 해외동향 수집 (KEDI 교육정책네트워크)...")
    trends_total, trends_raw = kedi_collector.collect("global_trends")

    # ── 3) 정책 수집 (KEDI) ──
    logger.info("[3/6] 정책 자료 수집 (KEDI 교육정책네트워크)...")
    policy_total, policy_raw = kedi_collector.collect("policy")

    # ── 4) 보고서 수집 (KEDI) ──
    logger.info("[4/6] 연구보고서 수집 (KEDI 교육정책네트워크)...")
    reports_total, reports_raw = kedi_collector.collect("reports")

    # ── 5) 국내학술지 수집 (CrossRef) ──
    logger.info("[5/6] 국내학술지 수집 (CrossRef)...")
    domestic_raw = academic_collector.collect_domestic()

    # ── 6) 해외학술지 수집 (ERIC) ──
    logger.info("[6/6] 해외학술지 수집 (ERIC)...")
    international_raw = academic_collector.collect_international()

    # ── AI 분석 (Gemini) ──
    logger.info("Gemini 2.5 Flash 분석 중...")
    news_out = analyzer.analyze_news(news_raw)
    time.sleep(2)
    trends_out = analyzer.analyze_kedi(trends_raw, "해외동향")
    time.sleep(2)
    policy_out = analyzer.analyze_kedi(policy_raw, "정책")
    time.sleep(2)
    reports_out = analyzer.analyze_kedi(reports_raw, "연구보고서")
    time.sleep(2)
    domestic_out = analyzer.analyze_academic(domestic_raw, "국내학술지", max_items=3)
    time.sleep(2)
    international_out = analyzer.analyze_academic(international_raw, "해외학술지", max_items=2)

    # ── 선별된 학술 문헌 이력 기록 ──
    academic_collector.mark_selected("domestic", domestic_out)
    academic_collector.mark_selected("international", international_out)

    # ── JSON 저장 ──
    now = datetime.now(KST)
    result = {
        "date": str(TODAY),
        "updated_at": now.isoformat(),
        "sections": {
            "news": news_out,
            "global_trends": trends_out,
            "policy": policy_out,
            "reports": reports_out,
            "academic_domestic": domestic_out,
            "academic_international": international_out,
        },
        "filter_info": {
            "news_source": "서울시교육청 오늘의 뉴스 (sen.go.kr)",
            "kedi_source": "KEDI 교육정책네트워크 (edpolicy.kedi.re.kr)",
            "academic_domestic_source": "CrossRef (국내 학술지 검색)",
            "academic_international_source": "ERIC (Education Resources Information Center)",
        },
        "stats": {
            "news_collected": news_total,
            "news_selected": len(news_out),
            "trends_collected": trends_total,
            "trends_selected": len(trends_out),
            "policy_collected": policy_total,
            "policy_selected": len(policy_out),
            "reports_collected": reports_total,
            "reports_selected": len(reports_out),
            "academic_domestic_collected": len(domestic_raw),
            "academic_domestic_selected": len(domestic_out),
            "academic_international_collected": len(international_raw),
            "academic_international_selected": len(international_out),
        },
    }

    out_file = OUTPUT_DIR / f"{TODAY}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info(f"저장 완료: {out_file}")

    # ── 날짜 인덱스 갱신 ──
    index_file = OUTPUT_DIR / "dates.json"
    existing_dates = []
    if index_file.exists():
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                existing_dates = json.load(f)
        except Exception:
            pass
    if str(TODAY) not in existing_dates:
        existing_dates.append(str(TODAY))
        existing_dates.sort(reverse=True)
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(existing_dates, f)
    logger.info(f"날짜 인덱스 갱신: {len(existing_dates)}개 날짜")

    # ── 이메일 알림 ──
    counts = {
        "news": len(news_out),
        "global_trends": len(trends_out),
        "policy": len(policy_out),
        "reports": len(reports_out),
        "academic_domestic": len(domestic_out),
        "academic_international": len(international_out),
    }
    EmailSender().send(str(TODAY), counts)

    # ── 요약 ──
    total = sum(counts.values())
    logger.info("=" * 60)
    logger.info(f"  완료! 총 {total}건 선별")
    for k, v in counts.items():
        logger.info(f"     {k}: {v}건")
    logger.info("=" * 60)
    return result


if __name__ == "__main__":
    main()
