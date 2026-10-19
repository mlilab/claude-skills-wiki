#!/usr/bin/env python3
"""
푸드박스 식단표 이미지 가져오기.

사이트(아임웹 호스팅)는 봇 요청을 차단하므로 브라우저 User-Agent로 요청.
/menu 페이지의 콘텐츠 이미지(cdn.imweb.me 등) 중 식단표 이미지를 찾아
가장 최근 것을 다운로드해서 로컬 경로를 반환한다.

standalone 테스트:
    python3 menu_fetch.py            # 이미지 다운로드만
    python3 menu_fetch.py --ocr      # + 로컬 OCR (easyocr 설치 필요)
"""

import datetime as dt
import itertools
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

MENU_URL = "https://www.foodboxkr.co.kr/menu"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://www.foodboxkr.co.kr/",
}
DOWNLOAD_DIR = Path(__file__).parent / "menu_images"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

# 로고/아이콘/배너를 거르기 위한 휴리스틱
SKIP_PATTERNS = re.compile(r"(logo|icon|banner|btn|favicon)", re.I)


def find_menu_image_urls(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for img in soup.find_all("img"):
        # 아임웹은 lazy-load로 data-src / data-original을 쓰는 경우가 많음
        src = (
            img.get("data-src")
            or img.get("data-original")
            or img.get("src")
            or ""
        )
        if not src:
            continue
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = "https://www.foodboxkr.co.kr" + src
        if SKIP_PATTERNS.search(src):
            continue
        # 콘텐츠 이미지는 보통 CDN(cdn.imweb.me)에 올라감
        if "imweb" in src or "foodboxkr" in src:
            urls.append(src)

    # fallback: <img> 태그로 못 잡는 경우 (JS 렌더링, background-image, srcset 등)
    # raw HTML 전체에서 imweb CDN 이미지 URL을 정규식으로 수집
    if not urls:
        raw = re.findall(
            r'https?:(?://|\\/\\/)cdn\.imweb\.me[^\s"\')]+?\.(?:jpe?g|png|webp)',
            html, re.I,
        )
        urls = [u.replace("\\/", "/") for u in raw if not SKIP_PATTERNS.search(u)]

    # 순서 유지하며 중복 제거
    seen: set[str] = set()
    return [u for u in urls if not (u in seen or seen.add(u))]




# ---------------------------------------------------------------- date matching

# OCR/URL 텍스트에서 (월, 일) 패턴 추출: "8월 17일", "8.17", "8/17", "08-17" 모두 커버
# "(?!\s*주)" : "8월 3주차" 의 (8,3) 오탐 방지
DATE_PAT = re.compile(r"(\d{1,2})\s*[월./\-]\s*(\d{1,2})\s*일?(?!\s*주)")
# URL/파일명용 압축 표기: "0817", "20260817" -> (8, 17)
COMPACT_PAT = re.compile(r"(?<!\d)(?:20\d{2})?(0[1-9]|1[0-2])([0-2]\d|3[01])(?!\d)")
WEEKDAY_KR = "월화수목금토일"


def extract_month_days(text: str) -> list[tuple[int, int]]:
    out = []
    for m, d in DATE_PAT.findall(text):
        m, d = int(m), int(d)
        if 1 <= m <= 12 and 1 <= d <= 31:
            out.append((m, d))
    if not out:  # 구분자 있는 날짜가 없을 때만 압축 표기 시도 (오탐 최소화)
        for m, d in COMPACT_PAT.findall(text):
            out.append((int(m), int(d)))
    return out


def nearest_date(month: int, day: int, target):
    """연도 없는 (월, 일) 을 target 에 가장 가까운 실제 날짜로 해석. 없으면 None."""
    for year in (target.year, target.year - 1, target.year + 1):
        try:
            cand = dt.date(year, month, day)
        except ValueError:
            continue
        if abs((cand - target).days) <= 183:
            return cand
    return None


def covers_target(month_days: list[tuple[int, int]], target) -> bool:
    """추출된 날짜들(예: 시작일~종료일)이 target 날짜를 포함하는가."""
    dates = [d for d in (nearest_date(m, day, target) for m, day in month_days) if d]
    if not dates:
        return False
    if target in dates:
        return True
    return min(dates) <= target <= max(dates)


# ------------------------------------------------------------- 주간표 레이아웃
# 푸드박스 주간표는 살구색 날짜 헤더 띠 + 그 아래 요일별 5열 구조이고, 한 이미지에
# 여러 주가 세로로 쌓여 있을 수 있다 (지난 주 위 / 이번 주 아래, 또는 그 반대).
# 아래 함수들은 "몇 번째 띠가 target 주인지"를 찾아 그 주만 잘라내기 위한 것.

HEADER_ROW_RATIO = 0.5      # 헤더 띠로 볼 가로 채움 비율
HEADER_COL_RATIO = 0.08     # 열 헤더 최소 폭 (이미지 폭 대비)


def _is_header_px(pixel) -> bool:
    """날짜 헤더의 살구색(≈#F6BEA1) 픽셀인가."""
    r, g, b = pixel[:3]
    return r >= 200 and r - b >= 35 and r - g >= 15 and g >= b


def header_bands(image) -> list[tuple[int, int, list[tuple[int, int]]]]:
    """날짜 헤더 띠 목록: (위 y, 아래 y, [열 x 범위 …]) - 위에서 아래 순서."""
    width, height = image.size
    px = image.load()
    xs = list(range(0, width, max(1, width // 400)))
    filled = [sum(1 for x in xs if _is_header_px(px[x, y])) / len(xs)
              for y in range(height)]
    spans, start = [], None
    for y, ratio in enumerate(filled + [0.0]):
        if ratio >= HEADER_ROW_RATIO:
            start = y if start is None else start
        elif start is not None:
            if y - start >= max(4, height * 0.005):
                spans.append((start, y - 1))
            start = None

    bands = []
    for top, bottom in spans:
        ys = list(range(top, bottom + 1, max(1, (bottom - top) // 20)))
        runs: list[list[int]] = []
        for x in range(width):
            if sum(1 for y in ys if _is_header_px(px[x, y])) < len(ys) * 0.5:
                continue        # 글자 픽셀 때문에 한 행만 보면 열이 쪼개진다
            if runs and x == runs[-1][-1] + 1:
                runs[-1].append(x)
            else:
                runs.append([x])
        cols = [(r[0], r[-1] + 1) for r in runs if len(r) >= width * HEADER_COL_RATIO]
        if cols:
            bands.append((top, bottom, cols))
    return bands


def _block_bottom(image, band, col: tuple[int, int]) -> int:
    """헤더 띠 아래 메뉴 칸이 끝나는 y. 칸 배경은 흰색이 아니라서 흰 줄이 경계."""
    _top, bottom, _cols = band
    _width, height = image.size
    px = image.load()
    x0, x1 = col
    xs = list(range(x0 + 4, max(x0 + 5, x1 - 4), max(1, (x1 - x0) // 40)))

    def inked(y: int) -> bool:
        return sum(1 for x in xs if min(px[x, y][:3]) < 250) >= len(xs) * 0.5

    start = bottom + 1
    limit = min(height, start + max(6, round(height * 0.02)))
    y = start
    while y < limit and inked(y):
        y += 1                     # 헤더 띠 경계에 남은 색 픽셀
    if y < limit:
        while y < limit and not inked(y):
            y += 1                 # 헤더와 메뉴 칸 사이의 얇은 흰 여백
    else:
        y = start                  # 여백 없이 곧바로 메뉴 칸이 이어지는 경우
    while y < height and inked(y):
        y += 1
    return y


def _ocr_reader():
    import easyocr

    if not hasattr(ocr_texts, "_reader"):
        ocr_texts._reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
    return ocr_texts._reader


def band_monday(image, band, target):
    """헤더 띠에 적힌 날짜들로 그 주의 월요일을 추정. 못 읽으면 None.

    OCR 은 1과 7을 곧잘 헷갈리므로(10/1 -> "10/7", 10/20 -> "70/20") 날짜 하나를
    그대로 믿지 않고, 열마다 "월요일 = 읽은 날짜 - 열 번호" 를 계산해 최빈값을 쓴다.
    읽은 글자의 7을 1로 바꾼 변형도 후보로 넣되, 계산 결과가 실제 월요일인 것만 센다.
    """
    import numpy as np

    top, bottom, cols = band
    width, _height = image.size
    strip = image.crop((0, max(0, top - 6), width, bottom + 7))
    try:
        boxes = _ocr_reader().readtext(np.array(strip))
    except ImportError:
        print("easyocr not installed -> 주차 판별 불가 (pip install easyocr)")
        return None
    except Exception as e:
        print(f"menu header OCR failed: {e}")
        return None

    votes: dict[dt.date, int] = {}
    for quad, text, _conf in boxes:
        cx = sum(p[0] for p in quad) / 4
        index = next((i for i, (x0, x1) in enumerate(cols) if x0 <= cx <= x1), None)
        if index is None:
            continue
        for monday in _column_mondays(text, index, target):
            votes[monday] = votes.get(monday, 0) + 1
    if not votes:
        return None
    return max(votes, key=lambda d: (votes[d], -abs((d - target).days)))


def _column_mondays(text: str, index: int, target) -> set:
    """열 index 의 헤더 글자가 가리킬 수 있는 월요일들 (7<->1 오인식 보정 포함)."""
    sevens = [i for i, c in enumerate(text) if c == "7"][:4]
    mondays = set()
    for swap in itertools.product((False, True), repeat=len(sevens)):
        chars = list(text)
        for i, on in zip(sevens, swap):
            if on:
                chars[i] = "1"
        found = extract_month_days("".join(chars))
        if len(found) != 1:
            continue
        day = nearest_date(*found[0], target)
        if day and (day - dt.timedelta(days=index)).weekday() == 0:
            mondays.add(day - dt.timedelta(days=index))
    return mondays


def week_band(image, target):
    """target 이 속한 주의 헤더 띠 (top, bottom, cols). 못 찾으면 None."""
    monday = target - dt.timedelta(days=target.weekday())
    for band in header_bands(image):
        if band_monday(image, band, target) == monday:
            return band
    return None


def ocr_texts(path: Path) -> str:
    """이미지에서 텍스트 추출 (easyocr). 미설치/실패 시 빈 문자열."""
    try:
        import easyocr
    except ImportError:
        print("easyocr not installed -> OCR date matching skipped "
              "(pip install easyocr)")
        return ""
    try:
        if not hasattr(ocr_texts, "_reader"):
            ocr_texts._reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
        return " ".join(ocr_texts._reader.readtext(str(path), detail=0))
    except Exception as e:
        print(f"OCR failed on {path.name}: {e}")
        return ""


def has_week_of(path: Path, target) -> bool:
    """이미지 안에 target 주의 날짜 헤더 띠가 있는가 (식단표가 아니면 False)."""
    try:
        from PIL import Image

        with Image.open(path) as image:
            return week_band(image.convert("RGB"), target) is not None
    except Exception:
        return False


def pick_for_date(candidates: list[tuple[str, Path]], target) -> Path | None:
    """(url, path) 후보들 중 target 날짜(내일 점심)에 해당하는 식단표 선택.

    1순위: 이미지 안 날짜 헤더 띠 -> target 주를 담고 있는 식단표
    2순위: URL에 박힌 날짜 (업로드 경로에 날짜가 있는 경우가 많음)
    3순위: 이미지 안 텍스트 OCR -> 날짜 범위 매칭
    실패 시: 가장 용량 큰 이미지 (기존 동작) + 경고
    """
    for _url, path in candidates:
        if has_week_of(path, target):
            print(f"date match via week header: {path.name}")
            return path
    for url, path in candidates:
        if covers_target(extract_month_days(url), target):
            print(f"date match via URL: {url}")
            return path
    for url, path in candidates:
        text = ocr_texts(path)
        mds = extract_month_days(text)
        if mds:
            print(f"{path.name}: OCR dates -> {mds}")
        if covers_target(mds, target):
            print(f"date match via OCR: {path.name}")
            return path
    print(f"WARNING: no image matched {target}; falling back to largest image")
    biggest = max(candidates, key=lambda c: c[1].stat().st_size, default=None)
    return biggest[1] if biggest else None


def extract_day_menu_text(path: Path, target) -> str | None:
    """주간 식단표 이미지에서 target 날짜 열(column)의 메뉴만 텍스트로 추출.

    OCR 박스 중 날짜 헤더들을 찾아 인접 헤더와의 중간점으로 열 경계를 잡고,
    target 날짜 헤더 아래·같은 열의 텍스트를 위에서 아래로 모은다.
    easyocr 미설치 / OCR 실패 / target 헤더 미발견이면 None
    (호출부는 이미지 업로드로 폴백).
    """
    try:
        import easyocr  # noqa: F401
    except ImportError:
        print("easyocr not installed -> menu text extraction skipped")
        return None
    try:
        if not hasattr(ocr_texts, "_reader"):
            import easyocr
            ocr_texts._reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
        boxes = ocr_texts._reader.readtext(str(path))  # [(꼭짓점4, 텍스트, 신뢰도)]
    except Exception as e:
        print(f"OCR failed on {path.name}: {e}")
        return None

    def geom(quad):
        xs, ys = [p[0] for p in quad], [p[1] for p in quad]
        return sum(xs) / 4, sum(ys) / 4, min(xs), max(xs)

    # 날짜 헤더 후보: 날짜가 정확히 1개인 박스 ("8월 17일~21일" 같은 제목 제외)
    # 또는 "20일(목)"처럼 월 없이 일만 적힌 박스
    day_only = re.compile(r"(?<!\d)\d{1,2}\s*일(?!\s*주)")
    target_day = re.compile(rf"(?<!\d)0?{target.day}\s*일(?!\s*주)")
    headers = []  # (cx, cy, x0, x1, is_target)
    for quad, text, conf in boxes:
        mds = extract_month_days(text)
        if len(mds) == 1:
            is_target = mds[0] == (target.month, target.day)
        elif not mds and day_only.search(text):
            is_target = bool(target_day.search(text))
        else:
            continue
        cx, cy, x0, x1 = geom(quad)
        headers.append((cx, cy, x0, x1, is_target))

    ours = min([h for h in headers if h[4]], key=lambda h: h[1], default=None)
    if ours is None:
        print(f"menu text: no date header for {target} in {path.name}")
        return None
    cx, cy, x0, x1, _ = ours
    # 열 반폭 = 인접 헤더 간 최소 간격의 절반. 최소값을 쓰므로 헤더 하나가
    # OCR에 안 잡혀도 (간격이 2열로 벌어져도) 이웃 열을 침범하지 않음.
    all_cx = sorted(h[0] for h in headers)
    gaps = [b - a for a, b in zip(all_cx, all_cx[1:]) if b - a > 20]
    half = min(gaps) / 2 if gaps else (x1 - x0) or 50
    x_lo, x_hi = cx - half, cx + half

    lines = []
    for quad, text, conf in boxes:
        bx, by, bx0, bx1 = geom(quad)
        if conf < 0.3 or by <= cy or not (x_lo <= bx <= x_hi):
            continue
        # 폭의 30% 이상이 열 밖이면 제외 (하단 공지 등 가로로 긴 문구)
        overlap = min(bx1, x_hi) - max(bx0, x_lo)
        if (bx1 - bx0) and overlap < 0.7 * (bx1 - bx0):
            continue
        if text.strip():
            lines.append((by, bx, text.strip()))
    if not lines:
        print(f"menu text: header found but column empty in {path.name}")
        return None
    lines.sort()
    return "\n".join(t for _, _, t in lines)


def crop_day_menu_image(path: Path, target) -> Path | None:
    """주간 식단표에서 target 요일의 날짜 헤더와 일반 메뉴 열을 이미지로 자른다.

    한 이미지에 여러 주가 쌓여 있을 수 있으므로 먼저 target 주의 헤더 띠를 찾고
    (week_band), 그 띠의 5열 중 요일 번호에 해당하는 열만 자른다. 메뉴 텍스트를
    OCR 로 읽지는 않는다. 월~금 밖의 날짜이거나 주/열을 못 찾으면 None
    (호출부는 주간표 전체 업로드로 폴백).
    """
    if not 0 <= target.weekday() <= 4:
        return None
    try:
        from PIL import Image

        with Image.open(path) as image:
            image = image.convert("RGB")
            width, height = image.size
            band = week_band(image, target)
            if band is None:
                print(f"daily menu crop: no week of {target} in {path.name}")
                return None
            top, _bottom, cols = band
            if len(cols) != 5:
                print(f"daily menu crop: expected 5 headers, found {len(cols)}")
                return None
            # 일부 주메뉴 이름은 디자인상 자기 열보다 약간 넓게 배치된다.
            margin = max(8, round(width * 0.025))
            pad = max(4, round(height * 0.008))
            col = cols[target.weekday()]
            left = max(0, col[0] - margin)
            right = min(width, col[1] + margin)
            top = max(0, top - pad)
            bottom = min(height, _block_bottom(image, band, col) + pad)
            if right <= left or bottom <= top:
                return None
            cropped = image.crop((left, top, right, bottom))
            DOWNLOAD_DIR.mkdir(exist_ok=True)
            out = DOWNLOAD_DIR / f"menu_{target:%Y%m%d}.png"
            cropped.save(out, format="PNG", optimize=True)
        print(f"cropped daily menu -> {out}")
        return out
    except Exception as e:
        print(f"daily menu crop failed for {path.name}: {e}")
        return None


def crop_week_menu_image(path: Path, target) -> Path | None:
    """여러 주가 쌓인 이미지에서 target 이 속한 주만 잘라 낸다 (주 첫날 업로드용).

    한 주짜리 이미지면 자를 것이 없으므로 None - 호출부가 원본을 그대로 올린다.
    """
    try:
        from PIL import Image

        with Image.open(path) as image:
            image = image.convert("RGB")
            width, height = image.size
            if len(header_bands(image)) < 2:
                return None
            band = week_band(image, target)
            if band is None:
                print(f"week menu crop: no week of {target} in {path.name}")
                return None
            top, _bottom, cols = band
            margin = max(8, round(width * 0.025))
            pad = max(4, round(height * 0.008))
            left = max(0, cols[0][0] - margin)
            right = min(width, cols[-1][1] + margin)
            top = max(0, top - pad)
            bottom = min(height, max(_block_bottom(image, band, c) for c in cols)
                         + pad)
            if right <= left or bottom <= top:
                return None
            cropped = image.crop((left, top, right, bottom))
            DOWNLOAD_DIR.mkdir(exist_ok=True)
            monday = target - dt.timedelta(days=target.weekday())
            out = DOWNLOAD_DIR / f"menu_week_{monday:%Y%m%d}.png"
            cropped.save(out, format="PNG", optimize=True)
        print(f"cropped weekly menu -> {out}")
        return out
    except Exception as e:
        print(f"week menu crop failed for {path.name}: {e}")
        return None


def cleanup_menu_images(dry_run: bool = False) -> int:
    """menu_images/ 의 지난 이미지(후보/크롭/latest)를 모두 지운다 -> 지운 개수.
    매일 20:00 에 새로 받아 오므로 금요일 밤(prep)에 비워도 다음 주에 지장 없다."""
    if not DOWNLOAD_DIR.is_dir():
        return 0
    files = [f for f in DOWNLOAD_DIR.iterdir()
             if f.is_file() and f.suffix.lower() in IMAGE_EXTS]
    for f in files:
        if dry_run:
            print(f"[DRY-RUN] would delete {f.name}")
        else:
            f.unlink(missing_ok=True)
    return len(files)


def fetch_latest_menu_image(target_date=None) -> Path | None:
    """식단표 페이지에서 target_date(기본: 내일)에 해당하는 식단표 이미지 반환."""
    if target_date is None:
        target_date = dt.date.today() + dt.timedelta(days=1)
    try:
        resp = requests.get(MENU_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"menu page fetch failed: {e}")
        return None

    urls = find_menu_image_urls(resp.text)
    if not urls:
        print("no candidate images found — page structure may have changed")
        return None
    print(f"{len(urls)} candidate image(s):")
    for u in urls[:10]:
        print("  ", u)

    DOWNLOAD_DIR.mkdir(exist_ok=True)
    candidates: list[tuple[str, Path]] = []
    for i, url in enumerate(urls[:10]):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
        except requests.RequestException:
            continue
        ext = ".png" if "png" in r.headers.get("content-type", "") else ".jpg"
        p = DOWNLOAD_DIR / f"candidate_{i}{ext}"
        p.write_bytes(r.content)
        candidates.append((url, p))

    if not candidates:
        print("all downloads failed")
        return None

    chosen = pick_for_date(candidates, target_date)
    if chosen is None:
        return None
    final = DOWNLOAD_DIR / f"menu_latest{chosen.suffix}"
    final.write_bytes(chosen.read_bytes())
    print(f"saved -> {final} (for {target_date})")
    return final


def ocr_menu_image(path: Path) -> str:
    """한국어 OCR (선택). easyocr 최초 실행 시 모델 다운로드로 다소 느림."""
    import easyocr  # pip install easyocr

    reader = easyocr.Reader(["ko", "en"], gpu=False)
    results = reader.readtext(str(path), detail=0, paragraph=True)
    return "\n".join(results)


if __name__ == "__main__":
    p = fetch_latest_menu_image()
    if p and "--ocr" in sys.argv:
        print("--- OCR ---")
        print(ocr_menu_image(p))
