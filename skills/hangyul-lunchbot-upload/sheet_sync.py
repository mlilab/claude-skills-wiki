#!/usr/bin/env python3
"""
Google Sheet("점심 현황") 양방향 동기화 - 시트 구조 적응형.

날짜 컬럼이 실제로 있는 탭을 전체 탭에서 찾아, 그 탭의 실제 구조(이름/날짜 컬럼
위치)에 맞춰 읽고 쓴다. 사람이 만든 탭(예: "시트1")의 구조는 건드리지 않는다.

  - 날짜 헤더는 형식 무관 파싱: "8/24(월)", "2026/08/20 (목)", "8월 24일" 모두 인식
  - 이름 컬럼: 헤더가 이름/인원/성명/name (못 찾으면 A열)
  - Slack ID 컬럼(있다면): 헤더에 slack/id/아이디 - 없는 탭에서는 이름으로 행을
    찾으며, Total/가격 등 다른 컬럼은 건드리지 않음
  - 봇이 만드는 주차 탭: 제목 "YYYYMMDD-YYYYMMDD"(월~목), 맨 앞(index 0)에 생성 -
    인원 | 월~목 날짜 4컬럼 | Total(=COUNTA 수식) | 가격(=Total*8000 수식).
    Slack ID 컬럼은 없음. 인원 컬럼은 '명단' 탭 순서를 그대로 미러링.
    어느 탭도 날짜를 커버하지 않을 때만 만들어짐

흐름:
  금 밤  prep_week_tab()     다음 주(월~목) 탭 미리 생성 - 인원 = 명단 탭 미러
  탭 생성  sort_roster()       명단을 구역(정직원/인턴)별 이름 오름차순 정렬
  집계    add_to_roster()     명단에 없는 사람(반응자/시트 기입자)을 명단에 자동 추가
  20:00  ensure_day_setup()  날짜 컬럼 커버 확인 (없으면 주차 탭 생성)
  집계    read_day_orders()   날짜 컬럼에서 비어있지 않은 셀 -> 주문으로 간주
  집계    sync_reactions()    이모지 반응을 셀에 기록 - 수동 입력은 보존하고,
         반응을 취소하면 봇이 썼던 셀만 지움 (state.json "synced"로 소유권 추적)
  집계    sync_roster_names() Slack ID 기준으로 바뀐 닉네임을 명단 + 이번 주 이후
         주차 탭에 반영 (주차 탭엔 ID 컬럼이 없어 이름으로 행을 찾으므로 필수)
  명단    load_roster()/save_roster() - "명단" 탭(이름|Slack ID)과 ID 컬럼이 있는
         탭에서 {Slack ID: 이름}을 수집/저장. 채널 멤버 API가 스코프 문제로 막혀도
         이모지 반응자의 이름을 시트에 쓸 수 있게 하는 폴백 이름 소스

인증: service_account.json + 시트를 서비스 계정 이메일에 편집자로 공유
"""

import datetime as dt
import os
import re
from pathlib import Path

try:
    import lunchbot_config as _local_config
except ImportError:
    _local_config = None

# 단일 원본: lunch_bot.py의 SPREADSHEET_URL도 이 값으로 만들어짐.
# 환경변수 우선, 없으면 git에 올라가지 않는 lunchbot_config.py에서 읽는다.
SHEET_ID = os.environ.get("SHEET_ID") or getattr(_local_config, "SHEET_ID", "")
SETTLE_ACCOUNT = (os.environ.get("SETTLE_ACCOUNT")
                  or getattr(_local_config, "SETTLE_ACCOUNT", ""))  # 정산 계좌

SA_FILE = Path(__file__).parent / "service_account.json"

INCLUDE_FRIDAY = True              # 금요일 점심 포함 여부 (기본: 월~금)
WEEK_DAY_COUNT = 5 if INCLUDE_FRIDAY else 4   # 점심 있는 요일 수 -> set_include_friday
PRICE_PER_MEAL = 8000              # 가격 컬럼 수식 (=Total*8000, 시트1과 동일)
PREFIX_HEADER = ["인원"]
SUFFIX_HEADER = ["Total", "가격"]
LEGACY_HEADER = ["이름", "Slack ID", "합계"]  # 예전 봇 탭(2026-W34 등) 인식용
ROSTER_TITLE = "명단"
_WEEK_TAB_RE = re.compile(r"\d{8}-\d{8}")

# 주차 탭 맨 아래 안내문 블록. 새 탭을 만들 때 직전 탭에서 그대로 옮겨 오고,
# 옮겨 올 탭이 하나도 없을 때만 아래 기본값을 쓴다 (계좌는 SETTLE_ACCOUNT).
DEFAULT_INSTRUCTIONS = [
    ["<Instructions>"],
    ["1. Slack emoji 대신 스프레드시트에 직접 적으실 경우, 밥 or 샐러드로 해당 "
     "셀에 텍스트 입력 부탁드립니다 \n"
     "2. 새 인원을 추가 원하는 경우 slack 프로필 이름명으로 새 열만 하나 "
     "추가해두시면 됩니다! \n"
     "(한 번 추가해두면 자동으로 이후에는 체크 가능하므로, 매번 추가할 필요 없음) \n"
     "3. 매주 금요일 오후에 해당 주에 주문한 금액 입금 부탁드려요~ "
     f"(계좌 - {SETTLE_ACCOUNT})"],
]

_ID_LIKE_RE = re.compile(r"[UW][A-Z0-9]{6,}")

RICE_WORDS = ("🍚", "밥")
SALAD_WORDS = ("🥗", "샐러드")
VALID_MEAL_MARKS = {"밥", "샐러드", "error"}
CANCEL_TAG = "취소"                 # 최소 인원 미달로 취소된 날의 날짜 헤더 표시

NAME_HEADERS = {"이름", "인원", "성명", "name"}
_TOTAL_HEADERS = {"합계", "total", "계"}
_ID_HEADER_RE = re.compile(r"(?i)slack|아이디|(?<![a-z])id(?![a-z])")
_DATE_RE = re.compile(r"(?:(\d{4})\s*[./\-년]\s*)?(\d{1,2})\s*[./\-월]\s*(\d{1,2})")


def _is_id_like(s: str) -> bool:
    """Slack ID 문자열인가 - 이름 칸에 들어가면 안 되는 값.

    users:read 스코프가 없으면 Slack 이름 조회가 ID로 폴백되기 때문에
    ("U0123ABCDEF" 같은 값이 이름 행세를 함) 이름 쓰기 전에 항상 걸러낸다.
    """
    return bool(_ID_LIKE_RE.fullmatch((s or "").strip()))


def _norm_name(s: str) -> str:
    """이름 비교용 정규화 (공백 제거 + casefold)"""
    return "".join(s.split()).casefold()


def _name_keys(s: str) -> set[str]:
    """이름 매칭 키: 전체 + 괄호 밖 + 괄호 안 별칭.
    "지수 (Jisoo)" -> {"지수(jisoo)", "지수", "jisoo"} - Slack 표시 이름이
    "지수"이든 "Jisoo"이든 명단의 같은 행에 매칭되도록."""
    keys = set()
    for part in [s, re.sub(r"\([^)]*\)", " ", s), *re.findall(r"\(([^)]*)\)", s)]:
        k = _norm_name(part)
        if k:
            keys.add(k)
    return keys


def _is_summary_name(name: str) -> bool:
    """The weekly totals row is not a roster member."""
    return _norm_name(name) in _TOTAL_HEADERS


def _is_person_name(name: str) -> bool:
    name = (name or "").strip()
    return bool(name and "\n" not in name and len(name) <= 100
                and not name.startswith("<") and not _is_summary_name(name))


def set_include_friday(include: bool) -> None:
    """금요일 점심 포함 여부를 실행 중에 바꾼다 (lunch_bot의 --friday/--no-friday)."""
    global INCLUDE_FRIDAY, WEEK_DAY_COUNT
    INCLUDE_FRIDAY = bool(include)
    WEEK_DAY_COUNT = 5 if INCLUDE_FRIDAY else 4


def _week_days(any_day: dt.date) -> list[dt.date]:
    """해당 주의 점심 날짜 (월~목 4개, 금요일 포함이면 월~금 5개)"""
    mon = any_day - dt.timedelta(days=any_day.weekday())
    return [mon + dt.timedelta(days=i) for i in range(WEEK_DAY_COUNT)]


def _short_date(d: dt.date) -> str:
    """시트1과 같은 날짜 헤더 형식: 8/24(월)"""
    return f"{d.month}/{d.day}({'월화수목금토일'[d.weekday()]})"


def _col_letter(col: int) -> str:
    out = ""
    while col:
        col, r = divmod(col - 1, 26)
        out = chr(65 + r) + out
    return out


def _parse_header_date(text: str) -> tuple[int | None, int, int] | None:
    """헤더 셀에서 (연도|None, 월, 일) 추출. "8/24(월)", "2026/08/20 (목)" 등."""
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    y, mo, d = m.groups()
    mo, d = int(mo), int(d)
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return (int(y) if y else None, mo, d)


def _week_title_dates(title: str) -> tuple[dt.date, dt.date] | None:
    """봇이 만든 YYYYMMDD-YYYYMMDD 탭 제목을 날짜로 변환."""
    if not _WEEK_TAB_RE.fullmatch(title):
        return None
    try:
        start, end = title.split("-")
        return (dt.datetime.strptime(start, "%Y%m%d").date(),
                dt.datetime.strptime(end, "%Y%m%d").date())
    except ValueError:
        return None


def _canonical_mark(mark: str) -> str:
    """자유 형식 입력을 시트의 유효한 세 값 중 하나로 변환."""
    value = (mark or "").strip()
    if value in VALID_MEAL_MARKS:
        return value
    has_rice = any(w in value for w in RICE_WORDS)
    has_salad = any(w in value for w in SALAD_WORDS)
    if has_rice and not has_salad:
        return "밥"
    if has_salad and not has_rice:
        return "샐러드"
    return "error"


def _open_sheet():
    import gspread

    if not SHEET_ID:
        raise RuntimeError("SHEET_ID 미설정 - lunchbot_config.py 또는 환경변수에 지정")
    gc = gspread.service_account(filename=str(SA_FILE))
    return gc.open_by_key(SHEET_ID)


class _Layout:
    """워크시트 1행 헤더에서 실제 컬럼 구조를 파악."""

    def __init__(self, ws):
        self.ws = ws
        self.header = ws.row_values(1)
        self.name_col, self.id_col, self.total_col = 1, None, None
        self.date_cols: dict[tuple[int | None, int, int], int] = {}
        named = False
        for i, h in enumerate(self.header, 1):
            h = h.strip()
            if not h:
                continue
            key = _norm_name(h)
            if key in NAME_HEADERS:
                if not named:
                    self.name_col, named = i, True
            elif _ID_HEADER_RE.search(h):
                self.id_col = self.id_col or i
            elif key in _TOTAL_HEADERS:
                self.total_col = self.total_col or i
            else:
                parsed = _parse_header_date(h)
                if parsed:
                    self.date_cols.setdefault(parsed, i)

    def date_col(self, day: dt.date) -> int | None:
        """연도가 명시된 헤더는 연도까지, 없는 헤더("8/24(월)")는 월/일만 비교."""
        return (self.date_cols.get((day.year, day.month, day.day))
                or self.date_cols.get((None, day.month, day.day)))

    @property
    def is_bot_tab(self) -> bool:
        return (bool(_WEEK_TAB_RE.fullmatch(self.ws.title))
                or self.header[:len(LEGACY_HEADER)] == LEGACY_HEADER)


def _summary_row(names: list[str]) -> int | None:
    """이름 컬럼에서 'Total' 합계 행의 행 번호."""
    return next((i for i, v in enumerate(names, 1)
                 if i > 1 and _is_summary_name(v)), None)


def _person_block_end(names: list[str]) -> int:
    """새 인원을 끼워 넣을 행 번호 = 첫 구역(정직원)이 끝나는 자리.

    명단/주차 탭은 [정직원 … ] 빈 줄 "<Intern list>" [인턴 … ] 구조라서, 맨 뒤에
    붙이면 새 인원이 인턴 구역으로 들어간다. 첫 경계(빈 줄 또는 "<…>" 소제목)
    바로 앞에 삽입해 정직원 구역에 넣고, 경계 아래(인턴/빈 줄/Total/안내문)는
    통째로 한 줄씩 밀려 내려가므로 합계 행과의 간격도 그대로 유지된다.
    """
    row = 2
    for i, name in enumerate(names[1:], 2):     # 헤더 다음 행부터
        name = name.strip()
        if not name or _is_section_head(name) or _is_summary_name(name):
            return i
        row = i + 1
    return row


def _instruction_rows(values: list[list[str]], name_col: int = 1) -> list[list[str]]:
    """합계 행 아래의 안내문 블록. 주차 탭을 새로 만들 때 그대로 옮기려고 읽는다."""
    names = [row[name_col - 1] if name_col - 1 < len(row) else "" for row in values]
    row = _summary_row(names)
    if row is None:
        return []
    block = [list(r) for r in values[row:]]
    while block and not any(c.strip() for c in block[0]):
        block.pop(0)
    while block and not any(c.strip() for c in block[-1]):
        block.pop()
    for r in block:                              # 뒤쪽 빈 칸은 떼어 냄
        while r and not r[-1].strip():
            r.pop()
    return block


def _week_instructions(sh, exclude: str = "") -> list[list[str]]:
    """가장 최근 주차 탭의 안내문 블록 (새 탭에 옮겨 쓰려고)."""
    tabs = []
    for ws in sh.worksheets():
        span = _week_title_dates(ws.title)
        if span and ws.title != exclude:
            tabs.append((span[1], ws))
    for _end, ws in sorted(tabs, reverse=True, key=lambda item: item[0]):
        block = _instruction_rows(ws.get_all_values(), _Layout(ws).name_col)
        if block:
            print(f"안내문 블록을 {ws.title!r} 에서 가져옴")
            return block
    return []


def _align_body_rows(ws, old_values: list[list[str]], old_lay: "_Layout",
                     need: int):
    """값을 다시 쓰기 전에 인원 구역의 행 수를 need(인원 + 빈 줄 1)에 맞춘다.

    지난주 탭을 복사해 만든 탭은 Total/안내문 행의 서식(병합·줄바꿈 등)을
    그대로 물려받는데, 명단이 길어지거나 짧아지면 그 서식이 한 줄씩 어긋난다.
    값이 아니라 행을 넣고 빼서 아래 블록이 통째로 밀리도록 한다.
    """
    names = [row[old_lay.name_col - 1] if old_lay.name_col - 1 < len(row) else ""
             for row in old_values]
    summary = _summary_row(names)
    if summary is None:
        return
    delta = need - (summary - 2)
    at = _person_block_end(names)
    if delta > 0:
        ws.insert_rows([[""]] * delta, at, inherit_from_before=True)
    elif delta < 0:
        count = min(-delta, summary - at)
        if count > 0:
            ws.delete_rows(at, at + count - 1)
    if delta:
        print(f"인원 구역 {abs(delta)}행 {'추가' if delta > 0 else '삭제'} "
              f"(합계·안내문 블록은 그대로 밀림)")


def _insert_person_rows(lay: "_Layout", entries: list[tuple[str, str]]) -> int:
    """주차 탭에 없는 사람을 정직원 구역 끝에 삽입 (_person_block_end 참고)."""
    at = _person_block_end(lay.ws.col_values(lay.name_col))
    width = max(lay.name_col, lay.id_col or 0)
    rows = []
    for name, uid in entries:
        row = [""] * width
        row[lay.name_col - 1] = name
        if lay.id_col:
            row[lay.id_col - 1] = uid
        rows.append(row)
    lay.ws.insert_rows(rows, at, value_input_option="RAW", inherit_from_before=True)
    print(f"{lay.ws.title!r} {at}행에 인원 추가: {[n or u for n, u in entries]}")
    return at


def _create_week_tab(sh, any_day: dt.date, names=()):
    """주차 탭 준비: "YYYYMMDD-YYYYMMDD" / 인원 | 월~목 | Total | 가격.

    인원 컬럼은 '명단' 탭 순서를 그대로 미러링(구분용 빈 줄·소제목 포함).
    인원 아래는 [빈 줄] Total [빈 줄] 안내문 블록 - 안내문은 직전 주차 탭에서
    그대로 옮겨 오고(_week_instructions), 옮겨 올 탭이 없으면 DEFAULT_INSTRUCTIONS.
    names 는 현재 쓰이지 않는다 - 명단에 없는 사람은 add_to_roster 가 등록한다.
    같은 제목의 탭이 있으면 새 탭을 만들지 않고 구조를 다시 만들되, 사람별로
    이미 입력된 날짜 셀은 이름과 날짜를 기준으로 찾아 그대로 복원한다.
    """
    days = _week_days(any_day)
    header = PREFIX_HEADER + [_short_date(d) for d in days] + SUFFIX_HEADER
    title = f"{days[0]:%Y%m%d}-{days[-1]:%Y%m%d}"

    # 인원 컬럼은 명단 순서 그대로. names(채널 멤버 등) 중 명단에 없는 사람은
    # 여기서 덧붙이지 않고, 집계 때 add_to_roster 가 명단 정직원 구역에 등록해
    # 다음 탭부터 자연스럽게 미러링되게 한다.
    prefill: list[str] = []
    rws = _roster_ws(sh)
    if rws:
        prefill = [v.strip() for v in rws.col_values(1)[1:]]
        while prefill and not prefill[-1]:
            prefill.pop()

    worksheets = sh.worksheets()
    ws = next((candidate for candidate in worksheets
               if candidate.title == title), None)
    rebuild = ws is not None
    if ws is None:
        previous = []
        for candidate in worksheets:
            span = _week_title_dates(candidate.title)
            if span and span[1] < days[0]:
                previous.append((span[1], candidate))
        if previous:
            template = max(previous, key=lambda item: item[0])[1]
            ws = sh.duplicate_sheet(template.id, insert_sheet_index=0,
                                    new_sheet_name=title)
            print(f"주차 탭 템플릿 복사: {template.title!r} -> {title!r}")
        else:
            ws = sh.add_worksheet(title=title, rows=100, cols=len(header), index=0)

    # 값을 지우기 전에 직전 탭에서 안내문(+같은 제목이면 이미 입력된 주문)을 건진다.
    old_values = ws.get_all_values()
    old_lay = _Layout(ws)
    instructions = _instruction_rows(old_values, old_lay.name_col)
    saved_orders: list[tuple[str, tuple[int | None, int, int], str]] = []
    if rebuild:
        for row in old_values[1:]:
            name = (row[old_lay.name_col - 1].strip()
                    if old_lay.name_col <= len(row) else "")
            if not _is_person_name(name):     # 합계 행·소제목·안내문은 제외
                continue
            for date_key, col in old_lay.date_cols.items():
                value = row[col - 1].strip() if col <= len(row) else ""
                if value:
                    saved_orders.append((name, date_key, _canonical_mark(value)))
        print(f"기존 주차 탭 덮어쓰기: {title!r} "
              f"(입력된 주문 {len(saved_orders)}칸 보존)")
    if not instructions:
        instructions = _week_instructions(sh, exclude=title) or DEFAULT_INSTRUCTIONS

    # 인원 컬럼 아래로는 [빈 줄] Total [빈 줄] 안내문 블록. 합계 행과 인원 사이의
    # 빈 줄은 명단이 몇 명이든 항상 유지된다. 날짜 칸에는 아무것도 쓰지 않는다 -
    # API로 쓴 빈 문자열은 COUNTA가 세기 때문에 인원수가 틀어진다.
    body = [[n] for n in prefill] + [[""], ["Total"], [""]]
    _align_body_rows(ws, old_values, old_lay, len(prefill) + 1)
    ws.clear()  # 서식/색/열 크기는 보존하고 지난주 값만 제거
    rows, width = len(body) + len(instructions) + 1, len(header)
    if instructions:
        width = max(width, *(len(r) for r in instructions))
    if ws.row_count < rows or ws.col_count < width:
        ws.resize(rows=max(100, ws.row_count, rows),
                  cols=max(width, ws.col_count))
    ws.update(range_name="A1", values=[header])
    ws.update(range_name=f"A2:A{len(body) + 1}", values=body)
    if instructions:
        first = len(body) + 2
        w = max(len(r) for r in instructions)
        ws.update(range_name=f"A{first}:{_col_letter(w)}{first + len(instructions) - 1}",
                  values=[r + [""] * (w - len(r)) for r in instructions])
    summary_row = len(prefill) + 3
    lay = _Layout(ws)
    if saved_orders and prefill:
        import gspread

        row_by_name: dict[str, int] = {}
        for row_num, name in enumerate(prefill, 2):
            for key in _name_keys(name):
                row_by_name.setdefault(key, row_num)
        cells = []
        for name, date_key, value in saved_orders:
            row_num = next((row_by_name[k] for k in _name_keys(name)
                            if k in row_by_name), None)
            col = lay.date_cols.get(date_key)
            if row_num and col:
                cells.append(gspread.Cell(row_num, col, value))
        if cells:
            ws.update_cells(cells, value_input_option="RAW")
    _refresh_total_formulas(lay, summary_row)
    return ws


def _add_date_col(lay: "_Layout", lunch_day: dt.date, date_label: str) -> int:
    """탭에 없는 날짜 컬럼을 추가하고 그 컬럼 번호를 반환.

    봇 주차 탭에서는 Total/가격 **앞에** 끼워 넣어야 한다 - 맨 뒤에 붙이면
    Total 의 =COUNTA 범위가 Total/가격 칸까지 삼켜 인원수가 틀어진다.
    """
    if lay.is_bot_tab and lay.total_col:
        col = lay.total_col
        lay.ws.insert_cols([[_short_date(lunch_day)]], col)
        fresh = _Layout(lay.ws)
        _refresh_total_formulas(fresh, len(lay.ws.col_values(fresh.name_col)))
    else:
        col = len(lay.header) + 1
        lay.ws.update_cell(1, col, date_label)
    print(f"{lay.ws.title!r} 에 날짜 컬럼 추가: {_short_date(lunch_day)}")
    return col


def _locate(lunch_day: dt.date, date_label: str, create: bool, prefill=()):
    """점심 날짜 컬럼이 실제로 있는 탭을 전 탭에서 찾아 (Layout, 컬럼) 반환.

    없으면: create=True일 때 주차 탭(월~목 전체 컬럼)을 만들고,
    create=False면 (None, None).
    """
    sh = _open_sheet()
    for ws in sh.worksheets():
        if ws.title == ROSTER_TITLE:
            continue
        lay = _Layout(ws)
        col = lay.date_col(lunch_day)
        if col:
            return lay, col
    if not create:
        return None, None
    # 같은 주를 이미 커버하는 탭이 있으면 새 탭을 만들지 않고 그 탭에 컬럼만 추가한다.
    # (금요일에 --force 로 돌리는 등 월~목 밖의 날짜 - 예전엔 add_worksheet가
    #  제목 중복으로 실패하거나 같은 이름의 주차 탭이 복제되던 경로)
    for ws in sh.worksheets():
        if ws.title == ROSTER_TITLE:
            continue
        lay = _Layout(ws)
        if any(lay.date_col(d) for d in _week_days(lunch_day)):
            return lay, _add_date_col(lay, lunch_day, date_label)
    ws = _create_week_tab(sh, lunch_day, names=prefill)
    lay = _Layout(ws)
    col = lay.date_col(lunch_day)
    if col is None:  # 월~목 밖의 날짜 (설정 변경 시)
        col = _add_date_col(lay, lunch_day, date_label)
        lay = _Layout(lay.ws)
    return lay, col


def _rows(lay: _Layout) -> tuple[dict[str, int], dict[str, int], int]:
    """(Slack ID -> 행, 이름 매칭 키 -> 행, 마지막 사용 행)"""
    names = lay.ws.col_values(lay.name_col)
    ids = lay.ws.col_values(lay.id_col) if lay.id_col else []
    by_id, by_name, last = {}, {}, 1
    for i, v in enumerate(ids):
        if i > 0 and _is_person_name(v):
            by_id[v.strip()] = i + 1
            last = max(last, i + 1)
    for i, v in enumerate(names):
        if i > 0 and _is_person_name(v):
            for k in _name_keys(v):
                by_name.setdefault(k, i + 1)
            last = max(last, i + 1)
    return by_id, by_name, last


def _refresh_total_formulas(lay: _Layout, last_row: int):
    """봇이 만든 탭의 Total(=COUNTA)/가격(=Total*8000) 수식만 갱신 -
    사람이 만든 탭은 안 건드림. 이름이 빈 행(구분선 등)은 수식 없이 비워 둠."""
    if not (lay.is_bot_tab and lay.total_col and lay.date_cols and last_row >= 2):
        return
    names = lay.ws.col_values(lay.name_col)
    cols = sorted(lay.date_cols.values())
    a, b = _col_letter(cols[0]), _col_letter(cols[-1])
    t = _col_letter(lay.total_col)
    rows = range(2, last_row + 1)

    def named(r: int) -> bool:
        return r - 1 < len(names) and _is_person_name(names[r - 1])

    summary_row = next((r for r in range(2, len(names) + 1)
                        if _is_summary_name(names[r - 1])), None)

    lay.ws.update(f"{t}2:{t}{last_row}",
                  [[f"=COUNTA({a}{r}:{b}{r})" if named(r) else ""] for r in rows],
                  value_input_option="USER_ENTERED")
    if summary_row:
        for c in cols:
            letter = _col_letter(c)
            lay.ws.update_cell(summary_row, c,
                               f"=COUNTA({letter}2:{letter}{summary_row - 1})")
        lay.ws.update_cell(summary_row, lay.total_col,
                           f"=SUM({a}{summary_row}:{b}{summary_row})")
    price_col = lay.total_col + 1  # 주차 탭 구조에서 Total 바로 오른쪽이 가격
    if price_col <= len(lay.header) and _norm_name(lay.header[price_col - 1]) == "가격":
        p = _col_letter(price_col)
        lay.ws.update(f"{p}2:{p}{last_row}",
                      [[f"={t}{r}*{PRICE_PER_MEAL}" if named(r) else ""] for r in rows],
                      value_input_option="USER_ENTERED")
        if summary_row:
            lay.ws.update_cell(summary_row, price_col,
                               f"={t}{summary_row}*{PRICE_PER_MEAL}")


def _ensure_roster_id_col(ws):
    """명단 탭에 Slack ID 컬럼이 없으면 헤더를 만들어 준다.

    ID 컬럼이 없으면 load_roster가 이 탭을 이름 소스로 인식하지 못하고
    (=멤버 API가 막힌 환경에선 멘션이 전부 이름으로 나옴), save_roster/
    add_to_roster가 쓴 ID도 헤더 없는 열에 묻힌다.
    """
    header = ws.row_values(1)
    if any(_ID_HEADER_RE.search(h or "") for h in header):
        return
    col = max(2, len(header) + 1)
    if ws.col_count < col:          # 1열짜리 탭이면 그리드부터 넓혀야 함
        ws.add_cols(col - ws.col_count)
    ws.update_cell(1, col, "Slack ID")
    print(f"명단 탭에 'Slack ID' 헤더 추가 ({_col_letter(col)}1)")


def _roster_ws(sh, create: bool = False):
    """'명단' 탭 핸들 (create=True면 없을 때 생성 + ID 컬럼 보강)."""
    import gspread

    try:
        ws = sh.worksheet(ROSTER_TITLE)
    except gspread.WorksheetNotFound:
        if not create:
            return None
        ws = sh.add_worksheet(title=ROSTER_TITLE, rows=100, cols=2)
        ws.update("A1", [["이름", "Slack ID"]])
        return ws
    if create:
        _ensure_roster_id_col(ws)
    return ws


def ensure_day_setup(lunch_day: dt.date, date_label: str,
                     members: dict[str, str], dry_run: bool = False):
    """날짜 컬럼 커버 확인 - 어느 탭에도 없으면 주차 탭(월~목 전체)을 만들고
    members 이름을 프리필. 이미 커버돼 있으면 아무것도 바꾸지 않는다."""
    if dry_run:
        print(f"[DRY-RUN] would ensure sheet tab for {date_label!r} "
              f"({len(members)} members)")
        return
    lay, _col = _locate(lunch_day, date_label, create=True,
                        prefill=members.values())
    print(f"sheet ready: {lay.ws.title} / {date_label}")


def week_names(any_day: dt.date, dry_run: bool = False) -> list[str]:
    """해당 주 날짜를 커버하는 탭의 인원 이름 목록 (다음 주 탭 프리필용)."""
    if dry_run:
        return []
    sh = _open_sheet()
    days = _week_days(any_day)
    for ws in sh.worksheets():
        if ws.title == ROSTER_TITLE:
            continue
        lay = _Layout(ws)
        if any(lay.date_col(d) for d in days):
            return [n.strip() for n in ws.col_values(lay.name_col)[1:] if n.strip()]
    return []


def week_orders(any_day: dt.date, members: dict[str, str] | None = None,
                dry_run: bool = False) -> list[str]:
    """그 주(월~목) 날짜 컬럼에 한 번이라도 체크한 사람 전원 (금요일 정산용).

    그 주를 커버하는 '모든' 탭을 훑어 합집합 - 요일마다 다른 탭에 기록됐어도
    (사람 탭 + 봇 탭 혼재 등) 누락되지 않는다. 같은 사람이 여러 탭에 있으면
    한 번만 (ID 우선, 이름은 별칭 키로 비교). 반환 원소는 Slack ID(멘션용)
    또는 매칭 안 된 이름 그대로 - read_day_orders와 같은 방식.
    """
    if dry_run:
        fake = ["U01AAAAAA", "U03CCCCCC", "김게스트"]
        print(f"[DRY-RUN] week orders -> {fake}")
        return fake
    sh = _open_sheet()
    days = _week_days(any_day)
    id_by_name = {}
    for uid, n in (members or {}).items():
        for k in _name_keys(n):
            id_by_name.setdefault(k, uid)
    hits: list[tuple[str, str]] = []  # (uid 또는 "", 행의 이름)
    for ws in sh.worksheets():
        if ws.title == ROSTER_TITLE:
            continue
        lay = _Layout(ws)
        cols = [c for c in (lay.date_col(d) for d in days) if c]
        if not cols:
            continue
        for i, row in enumerate(lay.ws.get_all_values()):
            if i == 0:
                continue

            def cell(c: int) -> str:
                return row[c - 1].strip() if c - 1 < len(row) else ""

            name = cell(lay.name_col)
            uid = cell(lay.id_col) if lay.id_col else ""
            if not uid and name:
                uid = next((id_by_name[k] for k in _name_keys(name)
                            if k in id_by_name), "")
            if (uid or _is_person_name(name)) and any(cell(c) for c in cols):
                hits.append((uid, name))

    # ID가 있는 사람 먼저 확정한 뒤 이름만 있는 행을 별칭 키로 비교 - 같은 사람이
    # 한 탭에선 ID 매칭되고 다른 탭에선 안 됐어도 멘션 쪽 한 번만 남는다
    out: list[str] = []
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    for uid, name in hits:
        if uid and uid not in seen_ids:
            seen_ids.add(uid)
            seen_keys |= _name_keys(name) | _name_keys((members or {}).get(uid, ""))
            out.append(uid)
    for uid, name in hits:
        if not uid and not (_name_keys(name) & seen_keys):
            seen_keys |= _name_keys(name)
            out.append(name)
    return out


def prep_week_tab(any_day: dt.date, names=(), dry_run: bool = False) -> str | None:
    """해당 주(월~목) 탭이 없으면 맨 앞에 생성 - 금요일 밤 job_prep에서 호출.
    인원 = 명단 탭 미러 + names 중 명단에 없는 이름(명단에도 등록됨).
    반환: 만든 탭 제목, 이미 어떤 탭이 그 주를 커버하고 있으면 None."""
    days = _week_days(any_day)
    title = f"{days[0]:%Y%m%d}-{days[-1]:%Y%m%d}"
    if dry_run:
        print(f"[DRY-RUN] would create week tab {title!r} at first position "
              f"(명단 미러 + 추가 후보 {len(list(names))}명)")
        return title
    sh = _open_sheet()
    for ws in sh.worksheets():
        if ws.title == ROSTER_TITLE:
            continue
        lay = _Layout(ws)
        covered = [d for d in days if lay.date_col(d)]
        if covered:
            print(f"week tab skipped: {ws.title!r} already covers "
                  f"{_short_date(covered[0])}")
            return None
    ws = _create_week_tab(sh, any_day, names=names)
    print(f"week tab created: {ws.title}")
    return ws.title


def read_day_orders(lunch_day: dt.date, date_label: str,
                    members: dict[str, str] | None = None,
                    dry_run: bool = False) -> dict[str, str]:
    """날짜 컬럼에서 비어있지 않은 셀 -> {Slack ID(또는 미매칭 이름): 셀 내용}.

    이름만 있는 행은 members({Slack ID: 이름})로 ID를 찾아 키로 쓰고(ID 컬럼이
    있는 탭이면 시트에도 보충), 끝내 매칭 안 되면 이름 그대로가 키가 됨.
    """
    if dry_run:
        fake = {"U04DDDDDD": "밥", "U05EEEEEEE": "샐러드", "김게스트": "밥"}
        print(f"[DRY-RUN] sheet orders for {date_label!r} -> {fake}\n"
              "          (U05...: 이름 매칭으로 ID 보충 / 김게스트: 미매칭 이름)")
        return fake
    import gspread

    lay, col = _locate(lunch_day, date_label, create=False)
    if lay is None:
        return {}
    names = lay.ws.col_values(lay.name_col)
    ids = lay.ws.col_values(lay.id_col) if lay.id_col else []
    marks = lay.ws.col_values(col)
    id_by_name = {}
    for uid, n in (members or {}).items():
        for k in _name_keys(n):
            id_by_name.setdefault(k, uid)
    out, backfill = {}, []
    for i in range(1, max(len(ids), len(names))):
        uid = ids[i].strip() if i < len(ids) else ""
        name = names[i].strip() if i < len(names) else ""
        mark = marks[i].strip() if i < len(marks) else ""
        if not uid and name:
            uid = next((id_by_name[k] for k in _name_keys(name)
                        if k in id_by_name), "")
            if uid and lay.id_col:
                backfill.append(gspread.Cell(i + 1, lay.id_col, uid))
        if mark and (uid or _is_person_name(name)):
            canonical = _canonical_mark(mark)
            out[uid or name] = canonical
            if mark != canonical:
                backfill.append(gspread.Cell(i + 1, col, canonical))
    if backfill:
        lay.ws.update_cells(backfill)
    return out


def day_sheet_names(lunch_day: dt.date, date_label: str,
                    dry_run: bool = False) -> list[str]:
    """Person names present on the current/newest weekly sheet.

    This deliberately ignores totals, section headings, and instructions.  It is
    used only as a candidate source for participant-driven roster additions.
    """
    if dry_run:
        return []
    lay, _col = _locate(lunch_day, date_label, create=False)
    if lay is None:
        return []
    return [name.strip() for name in lay.ws.col_values(lay.name_col)[1:]
            if _is_person_name(name)]


def classify_mark(mark: str) -> str | None:
    """셀 내용 -> 'rice' / 'salad' / None(error)."""
    canonical = _canonical_mark(mark)
    if canonical == "밥":
        return "rice"
    if canonical == "샐러드":
        return "salad"
    return None


def sync_reactions(lunch_day: dt.date, date_label: str,
                   rice: set[str], salad: set[str],
                   names: dict[str, str], prev_synced: dict[str, str],
                   dry_run: bool = False) -> dict[str, str]:
    """이모지 반응을 시트 셀에 반영. 봇이 쓴 {Slack ID: 마크}를 반환 (state.json 저장).

    - 빈 셀에만 쓰고, 사람이 직접 입력한 값(prev_synced와 다른 값)은 절대 덮지 않음
    - 반응을 취소한 사람은 봇이 썼던 셀만 지움 (셀 값이 prev_synced와 같을 때만)
    - 행 찾기: Slack ID 컬럼 -> 이름(names 매핑) 순서. 둘 다 없으면 정직원 구역
      끝에 행을 끼워 넣어 이름(모르면 ID)을 적는다 - 탭 구조에 맞춰 이름/ID 컬럼
      위치를 따라가고, 맨 아래 합계 행과의 빈 줄은 그대로 밀려 내려간다
    """
    desired = {**{u: "밥" for u in rice}, **{u: "샐러드" for u in salad}}
    for u in rice & salad:
        desired[u] = "error"
    if dry_run:
        print(f"[DRY-RUN] would sync reactions to sheet col {date_label!r}:")
        for u, m in sorted(desired.items()):
            print(f"    {names.get(u, u):10} ({u}) -> {m}")
        for u in sorted(set(prev_synced) - set(desired)):
            print(f"    {names.get(u, u):10} ({u}) -> (반응 취소, 봇 기록 삭제)")
        return desired
    import gspread

    lay, col = _locate(lunch_day, date_label, create=True, prefill=names.values())
    by_id, by_name, last = _rows(lay)

    def row_for(uid: str) -> int | None:
        r = by_id.get(uid)
        if r:
            return r
        return next((by_name[k] for k in _name_keys(names.get(uid, uid))
                     if k in by_name), None)

    # 시트에 아직 없는 사람은 먼저 정직원 구역에 행으로 끼워 넣는다. 행 번호가
    # 밀리므로 값 쓰기 전에 끝내고 구조를 다시 읽는다.
    missing = [uid for uid in sorted(desired) if row_for(uid) is None]
    if missing:
        _insert_person_rows(lay, [(names.get(uid, uid), uid) for uid in missing])
        lay = _Layout(lay.ws)
        col = lay.date_col(lunch_day) or col
        by_id, by_name, last = _rows(lay)

    col_vals = lay.ws.col_values(col)

    def cur_val(r: int | None) -> str:
        return col_vals[r - 1].strip() if r and r - 1 < len(col_vals) else ""

    next_row = last + 1
    cells, synced = [], {}
    for uid, mark in sorted(desired.items()):
        r = row_for(uid)
        cur = cur_val(r)
        if cur and cur != prev_synced.get(uid):
            continue  # 사람이 직접 쓴 값은 덮어쓰지 않음
        if r is None:
            r = next_row
            next_row += 1
            cells.append(gspread.Cell(r, lay.name_col, names.get(uid, uid)))
            if lay.id_col:
                cells.append(gspread.Cell(r, lay.id_col, uid))
        if cur != mark:
            cells.append(gspread.Cell(r, col, mark))
        synced[uid] = mark
    clears = []
    for uid, mark in prev_synced.items():  # 반응 취소 -> 봇이 썼던 셀만 삭제
        r = row_for(uid)
        if uid not in desired and r and cur_val(r) == mark:
            # 빈 문자열을 쓰면 COUNTA가 계속 세므로 batch_clear로 진짜 비움
            clears.append(f"{_col_letter(col)}{r}")
    if cells:
        lay.ws.update_cells(cells)
    if clears:
        lay.ws.batch_clear(clears)
    _refresh_total_formulas(lay, next_row - 1)
    print(f"sheet synced: {lay.ws.title} / {date_label} ({len(synced)}명)")
    return synced


def cancel_day(lunch_day: dt.date, date_label: str,
               dry_run: bool = False) -> int:
    """최소 인원 미달로 주문이 취소된 날을 시트에 반영. 지운 주문 칸 수를 반환.

    - 그 날짜 컬럼의 주문 칸을 전부 비운다 (사람이 직접 쓴 값 포함 - 주문 자체가
      없어졌으므로). 남겨 두면 행별 Total(=COUNTA)/가격에 잡혀 정산 때 청구된다.
      빈 문자열 대신 batch_clear로 지워야 COUNTA가 세지 않는다.
    - 헤더에 CANCEL_TAG를 붙여 취소된 날임을 표시 ("10/20(화) 취소"). 날짜 파싱은
      그대로 되므로 _locate/_Layout은 계속 이 컬럼을 같은 날짜로 인식한다.
    합계 행 아래(안내문 등)는 건드리지 않는다. 다시 실행해도 결과는 같다.
    """
    if dry_run:
        print(f"[DRY-RUN] would clear orders in sheet col {date_label!r} "
              f"and mark the header {CANCEL_TAG!r}")
        return 0
    lay, col = _locate(lunch_day, date_label, create=False)
    if lay is None:
        return 0
    names = lay.ws.col_values(lay.name_col)
    ids = lay.ws.col_values(lay.id_col) if lay.id_col else []
    marks = lay.ws.col_values(col)
    end = (_summary_row(names) or len(marks) + 1) - 1
    letter = _col_letter(col)
    clears = []
    for r in range(2, min(end, len(marks)) + 1):
        name = names[r - 1] if r - 1 < len(names) else ""
        uid = ids[r - 1].strip() if r - 1 < len(ids) else ""
        if marks[r - 1].strip() and (uid or _is_person_name(name)):
            clears.append(f"{letter}{r}")
    if clears:
        lay.ws.batch_clear(clears)
    header = lay.header[col - 1] if col - 1 < len(lay.header) else ""
    if CANCEL_TAG not in header:
        lay.ws.update_cell(1, col, f"{header.strip()} {CANCEL_TAG}".strip())
    print(f"sheet cancelled: {lay.ws.title} / {date_label} "
          f"(주문 {len(clears)}칸 삭제)")
    return len(clears)


# ---------------------------------------------------------------- roster

def load_roster(dry_run: bool = False) -> dict[str, str]:
    """'명단' 탭 등 Slack ID 컬럼이 있는 모든 탭에서 {Slack ID: 이름} 수집.
    채널 멤버 API가 스코프 문제로 막혔을 때의 이름 소스."""
    if dry_run:
        print("[DRY-RUN] would load roster names from sheet")
        return {}
    out: dict[str, str] = {}
    for ws in _open_sheet().worksheets():
        lay = _Layout(ws)
        if not lay.id_col:
            continue
        names = ws.col_values(lay.name_col)
        ids = ws.col_values(lay.id_col)
        for i in range(1, len(ids)):
            uid = ids[i].strip()
            name = names[i].strip() if i < len(names) else ""
            if uid and name and name != uid:
                out.setdefault(uid, name)
    return out


def _covers_from(lay: "_Layout", since: dt.date) -> bool:
    """탭의 날짜 컬럼 중 since 이후가 하나라도 있는가 (지난 주 기록은 안 건드리려고)."""
    for y, mo, d in lay.date_cols:
        try:
            day = dt.date(y or since.year, mo, d)
        except ValueError:
            continue
        if y is None and (since - day).days > 180:   # 연말/연초 걸침 보정
            day = day.replace(year=since.year + 1)
        if day >= since:
            return True
    return False


def _propagate_names(sh, renames: dict[str, tuple[str, str]], since: dt.date):
    """이번 주 이후 주차 탭의 이름 셀도 새 이름으로 바꾼다.

    봇 주차 탭엔 Slack ID 컬럼이 없어 행을 이름으로 찾으므로, 명단만 바꾸면
    같은 사람이 새 행으로 중복 추가된다. 지난 주 탭은 기록 보존을 위해 그대로 둔다.
    """
    import gspread

    by_id = {uid: new for uid, (_old, new) in renames.items()}
    by_key = {k: new for _uid, (old, new) in renames.items()
              for k in _name_keys(old) if old}
    for ws in sh.worksheets():
        if ws.title == ROSTER_TITLE:
            continue
        lay = _Layout(ws)
        if not _covers_from(lay, since):
            continue
        names = ws.col_values(lay.name_col)
        ids = ws.col_values(lay.id_col) if lay.id_col else []
        cells = []
        for i in range(1, len(names)):
            nm = names[i].strip()
            uid = ids[i].strip() if i < len(ids) else ""
            new = (by_id.get(uid)
                   or next((by_key[k] for k in _name_keys(nm) if k in by_key), None))
            if new and new != nm:
                cells.append(gspread.Cell(i + 1, lay.name_col, new))
        if cells:
            ws.update_cells(cells)
            print(f"  {ws.title}: 이름 {len(cells)}건 갱신")


def sync_roster_names(current: dict[str, str], today: dt.date | None = None,
                      dry_run: bool = False) -> dict[str, tuple[str, str]]:
    """Slack 닉네임이 바뀌면 Slack ID를 기준으로 시트 이름을 따라가게 한다.

    current: {Slack ID: 현재 Slack 표시 이름}. 반환: {ID: (예전 이름, 새 이름)}

    - 별칭 키가 하나라도 겹치면("지수" vs "지수 (Jisoo)") 이미 같은 사람으로
      매칭되므로 그대로 둔다 - 사람이 정리해 둔 표기를 괜히 덮지 않음
    - 안 겹치면 진짜 개명으로 보고 명단 이름을 바꾸고, 이번 주 이후 주차 탭의
      같은 사람 행도 함께 바꾼다 (_propagate_names)
    - 새 이름이 명단의 다른 사람과 겹치면 중복 행이 생기므로 건너뛰고 경고만
    """
    if dry_run:
        print(f"[DRY-RUN] would reconcile {len(current)}명 roster names by Slack ID")
        return {}
    if not current:
        return {}
    import gspread

    sh = _open_sheet()
    ws = _roster_ws(sh, create=True)
    lay = _Layout(ws)
    if not lay.id_col:
        return {}
    names = ws.col_values(lay.name_col)
    ids = ws.col_values(lay.id_col)
    row_of: dict[str, int] = {}
    owner: dict[str, str] = {}          # 이름 키 -> 그 이름을 쓰는 사람(ID 또는 이름)
    for i in range(1, max(len(ids), len(names))):
        uid = ids[i].strip() if i < len(ids) else ""
        nm = names[i].strip() if i < len(names) else ""
        if uid:
            row_of[uid] = i + 1
        for k in _name_keys(nm):
            owner.setdefault(k, uid or nm)

    renames: dict[str, tuple[str, str]] = {}
    cells = []
    for uid, new in current.items():
        new = (new or "").strip()
        r = row_of.get(uid)
        if not (r and new) or _is_id_like(new):
            continue          # 이름 조회가 ID로 폴백된 경우 (users:read 없음)
        old = names[r - 1].strip() if r - 1 < len(names) else ""
        if _name_keys(old) & _name_keys(new):
            continue                     # 이미 같은 사람으로 매칭됨
        clash = next((owner[k] for k in _name_keys(new)
                      if owner.get(k, uid) != uid), None)
        if clash:
            print(f"이름 갱신 보류: {old!r} -> {new!r} "
                  f"(명단의 다른 행 {clash!r} 과 이름 충돌)")
            continue
        cells.append(gspread.Cell(r, lay.name_col, new))
        renames[uid] = (old, new)
    if not renames:
        return {}
    ws.update_cells(cells)
    print("명단 이름 갱신(Slack ID 기준): "
          + ", ".join(f"{o or '(빈칸)'} -> {n}" for o, n in renames.values()))
    _propagate_names(sh, renames, today or dt.date.today())
    return renames


def _is_section_head(name: str) -> bool:
    """"<Intern list>" 같은 구역 소제목 - 정렬 대상이 아니라 구역 경계."""
    return name.strip().startswith("<")


def _sorted_roster_rows(body: list[list[str]], name_idx: int) -> list[list[str]]:
    """명단 본문을 구역별 이름 오름차순으로 정렬한 새 리스트.

    빈 줄과 "<...>" 소제목은 있던 자리를 그대로 지키는 경계이고, 경계 사이
    블록 안에서만 정렬한다 - 정직원 구역과 인턴 구역이 섞이지 않게.
    이름 없이 Slack ID만 있는 행(이름 조회가 막힌 반응자)은 블록 맨 뒤로.
    """
    out: list[list[str]] = []
    block: list[list[str]] = []

    def key(row):
        name = _norm_name(row[name_idx] if name_idx < len(row) else "")
        return (0, name) if name else (1, "".join(row))

    def flush():
        out.extend(sorted(block, key=key))
        block.clear()

    for row in body:
        name = (row[name_idx] if name_idx < len(row) else "").strip()
        if _is_section_head(name) or not any(c.strip() for c in row):
            flush()
            out.append(row)
        else:
            block.append(row)
    flush()
    return out


def _sort_roster_ws(ws) -> bool:
    """'명단' 탭을 구역별 오름차순으로 다시 쓴다 (이미 정렬돼 있으면 안 씀).

    사람이 수식을 넣어 둔 칸이 값으로 납작해지지 않도록 FORMULA로 읽어
    USER_ENTERED로 되쓴다. 행 전체를 옮기므로 이름-ID 짝은 그대로 유지된다.
    """
    rows = [[str(c) for c in r]
            for r in ws.get_all_values(value_render_option="FORMULA")]
    if len(rows) < 3:                   # 헤더 + 1행 이하면 정렬할 게 없음
        return False
    name_idx = next((i for i, h in enumerate(rows[0])
                     if _norm_name(h) in NAME_HEADERS), 0)
    width = max(len(r) for r in rows)
    body = [r + [""] * (width - len(r)) for r in rows[1:]]
    new = _sorted_roster_rows(body, name_idx)
    if new == body:
        return False
    ws.update(values=new, range_name=f"A2:{_col_letter(width)}{len(new) + 1}",
              value_input_option="USER_ENTERED")
    print(f"명단 정렬(구역별 이름 오름차순): {len(new)}행")
    return True


def sort_roster(dry_run: bool = False) -> bool:
    """'명단' 탭 이름을 구역(정직원/인턴)별로 오름차순 정렬. 바뀌었으면 True.

    주차 탭을 만들 때마다 자동 호출되므로 새 탭의 인원 컬럼도 정렬된 순서를
    미러링한다. 수동 실행: python -c "import sheet_sync as S; S.sort_roster()"
    """
    if dry_run:
        print("[DRY-RUN] would sort 명단 names ascending within each section")
        return False
    ws = _roster_ws(_open_sheet())
    return _sort_roster_ws(ws) if ws is not None else False


def roster_missing_ids(dry_run: bool = False) -> list[str]:
    """'명단' 탭에서 Slack ID가 비어 있는 이름 목록 (ID 자동 보충 대상).

    빈 줄과 "<Intern list>" 같은 소제목 행은 제외. ID 컬럼이 없는 명단이면
    _roster_ws가 먼저 만들어 준다.
    """
    if dry_run:
        print("[DRY-RUN] would list 명단 rows missing a Slack ID")
        return []
    import gspread

    ws = _roster_ws(_open_sheet(), create=True)
    lay = _Layout(ws)
    names = ws.col_values(lay.name_col)
    ids = ws.col_values(lay.id_col) if lay.id_col else []
    out = []
    for i in range(1, len(names)):
        name = names[i].strip()
        uid = ids[i].strip() if i < len(ids) else ""
        if name and not uid and not name.startswith("<"):
            out.append(name)
    return out


def save_roster(members: dict[str, str], dry_run: bool = False):
    """채널 멤버 조회가 성공했을 때 '명단' 탭(이름|Slack ID)에 ID를 채움.

    - ID가 이미 있는 행: 이름 셀이 비어 있을 때만 이름을 채움
      (사람이 정리한 이름 - "지수 (Jisoo)" 등 - 은 덮어쓰지 않음)
    - ID가 없지만 이름(괄호 별칭 포함)이 매칭되는 행: ID만 보충
    - 어느 행에도 없으면 새 행 추가
    """
    if not members:
        return
    if dry_run:
        print(f"[DRY-RUN] would save {len(members)} members to {ROSTER_TITLE!r} tab")
        return
    import gspread

    ws = _roster_ws(_open_sheet(), create=True)
    names_col = ws.col_values(1)
    ids = ws.col_values(2)
    row_of_id = {v.strip(): i + 1 for i, v in enumerate(ids) if i > 0 and v.strip()}
    key_rows: dict[str, int] = {}
    for i, n in enumerate(names_col):
        if i > 0 and n.strip():
            for k in _name_keys(n):
                key_rows.setdefault(k, i + 1)
    next_row = max([1, len(ids), len(names_col)]) + 1
    cells = []
    for uid, name in sorted(members.items(), key=lambda kv: kv[1]):
        r = row_of_id.get(uid)
        if r:
            if ((r - 1 >= len(names_col) or not names_col[r - 1].strip())
                    and not _is_id_like(name)):
                cells.append(gspread.Cell(r, 1, name))
            continue
        r = next((key_rows[k] for k in _name_keys(name) if k in key_rows), None)
        if r and (r - 1 >= len(ids) or not ids[r - 1].strip()):
            cells.append(gspread.Cell(r, 2, uid))  # 이름 행에 ID 보충
            row_of_id[uid] = r
            continue
        cells += [gspread.Cell(next_row, 1, name),
                  gspread.Cell(next_row, 2, uid)]
        next_row += 1
    if cells:
        ws.update_cells(cells)


def add_to_roster(entries, dry_run: bool = False):
    """명단 탭에 없는 사람 추가. entries: (이름, Slack ID) 목록 - 한쪽이 빈 값이어도 됨.

    ID 또는 이름(괄호 별칭 포함)이 이미 명단에 있으면 건너뜀. 이름을 알 수 없는
    이모지 반응자는 ID만 적힌 행으로 추가됨 - 이름 셀을 사람이 채워 주면 이후
    매칭에 쓰임 (스코프가 생기면 save_roster가 자동으로 채움).
    새 행은 정직원 구역(첫 구역) 끝에 삽입된다 - _person_block_end 참고.
    """
    entries = [(n.strip(), u.strip()) for n, u in entries]
    # 이름 칸에 Slack ID가 들어온 경우(스코프 없어 이름 조회 실패) 이름 대신 ID로 취급
    entries = [("", u or n) if _is_id_like(n) else (n, u) for n, u in entries]
    entries = [(n, u) for n, u in entries if n or u]
    if not entries:
        return
    if dry_run:
        print(f"[DRY-RUN] would add missing people to {ROSTER_TITLE!r}: {entries}")
        return
    import gspread

    ws = _roster_ws(_open_sheet(), create=True)
    names_col = ws.col_values(1)
    ids = ws.col_values(2)
    known_ids = {v.strip() for v in ids[1:] if v.strip()}
    key_rows: dict[str, int] = {}
    for i, n in enumerate(names_col[1:], 2):
        for key in _name_keys(n):
            key_rows.setdefault(key, i)
    known_keys = set(key_rows)
    rows = []
    cells = []
    for n, u in entries:
        if u and u in known_ids:
            continue
        matched_row = next((key_rows[k] for k in _name_keys(n)
                            if k in key_rows), None)
        if matched_row:
            if u and (matched_row - 1 >= len(ids)
                      or not ids[matched_row - 1].strip()):
                cells.append(gspread.Cell(matched_row, 2, u))
                known_ids.add(u)
            continue
        rows.append([n, u])
        known_ids.add(u)
        known_keys |= _name_keys(n)
    if cells:
        ws.update_cells(cells)
    if rows:
        # 맨 아래에 붙이면 "<Intern list>" 아래 = 인턴 구역으로 들어가므로
        # 정직원 구역(첫 구역) 끝에 끼워 넣는다.
        at = _person_block_end(names_col)
        ws.insert_rows(rows, at, value_input_option="RAW", inherit_from_before=True)
        print(f"명단 {at}행에 추가: {[n or u for n, u in rows]}")
