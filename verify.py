"""검증 에이전트 — 모든 기능이 정상 작동하는지 확인"""
import json
import sys
from pathlib import Path

OUTPUT = Path("output")
CUMUL = OUTPUT / "cumulative.json"
ERRORS = []


def check(name, condition, msg=""):
    if condition:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name} — {msg}")
        ERRORS.append(f"{name}: {msg}")


def main():
    print("=" * 50)
    print("  검증 에이전트 실행")
    print("=" * 50)

    # 1. 누적 JSON 존재
    check("누적 JSON 파일 존재", CUMUL.exists(), "cumulative.json 없음")
    if not CUMUL.exists():
        print("\n누적 파일이 없어 검증 중단")
        return False

    data = json.load(open(CUMUL, "r", encoding="utf-8"))

    # 2. 필수 섹션 존재
    sections = data.get("sections", {})
    for key in ["news", "global_trends", "policy", "reports", "academic_domestic", "academic_international"]:
        check(f"섹션 '{key}' 존재", key in sections, f"{key} 섹션 없음")

    # 3. 데이터 수집 확인
    total = sum(len(v) for v in sections.values())
    check("총 자료 1건 이상", total > 0, f"총 {total}건")

    # 4. 뉴스 출처 확인 (네이버+ScrapMaster)
    news = sections.get("news", [])
    check("뉴스 데이터 존재", len(news) > 0, f"{len(news)}건")

    # 5. 해외동향 확인
    trends = sections.get("global_trends", [])
    check("해외동향 데이터 존재", len(trends) > 0, f"{len(trends)}건")
    sources = set(a.get("source", "") for a in trends)
    print(f"    해외동향 출처: {sources}")

    # 6. 학술지 확인
    dom = sections.get("academic_domestic", [])
    intl = sections.get("academic_international", [])
    check("국내학술지 데이터 존재", len(dom) > 0, f"{len(dom)}건")
    check("해외학술지 데이터 존재", len(intl) > 0, f"{len(intl)}건")

    # 7. APA 인용 확인
    has_apa = any(a.get("apa_citation") for a in dom + intl)
    check("APA 인용 포함", has_apa, "apa_citation 필드 없음")

    # 8. NEW 배지 확인
    has_new = any(a.get("is_new") for a in sum(sections.values(), []))
    check("NEW 배지 표시 자료 존재", has_new, "is_new=True 없음")

    # 9. collected_date 확인
    has_date = any(a.get("collected_date") for a in sum(sections.values(), []))
    check("수집 날짜(collected_date) 포함", has_date, "collected_date 필드 없음")

    # 10. 시사점 형식 확인
    all_items = sum(sections.values(), [])
    has_impl = any("[관련업무]" in a.get("implications", "") or "[정책방향]" in a.get("implications", "") for a in all_items)
    check("시사점 구조화 형식", has_impl, "[관련업무]/[정책방향] 형식 없음")

    # 11. 주요내용 구체성 (50자 이상)
    summaries = [a.get("summary", "") for a in all_items if a.get("summary")]
    avg_len = sum(len(s) for s in summaries) / max(len(summaries), 1)
    check(f"요약 평균 길이 ({avg_len:.0f}자)", avg_len > 80, f"평균 {avg_len:.0f}자 — 너무 짧음")

    # 12. 프론트엔드 파일 존재
    for f in ["index.html", "app.js", "style.css"]:
        check(f"{f} 존재", Path(f).exists(), f"{f} 없음")

    print("\n" + "=" * 50)
    if ERRORS:
        print(f"  결과: {len(ERRORS)}개 실패")
        for e in ERRORS:
            print(f"    - {e}")
        return False
    else:
        print("  결과: 모든 검증 통과!")
        return True


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
