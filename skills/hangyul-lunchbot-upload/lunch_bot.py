#!/usr/bin/env python3
"""
도시락 주문 Slack 리마인더 봇 (test version)

- 20:00 KST: 주문 안내 메시지 게시
- 22:00 KST: 8PM 메시지에 이모지 반응한 사람 + 스프레드시트 체크한 사람을 집계해 최종 리마인더 게시
- 23:00 KST: 최종 주문 확정/취소 메시지 게시
- 20:00~23:00 KST: 5분마다 이모지 반응과 스프레드시트 상태 동기화
  (집계할 때마다 이모지 반응을 시트에도 기록 - 시트/이모지 양쪽 어느 쪽으로 주문해도 집계·기록됨)
- 한국 공휴일(대체공휴일 포함) 및 주말 스킵

Modes:
  --dry-run          Slack 호출 없이 콘솔에 출력 (토큰 불필요, 로컬 테스트용)
  --test             지금 8PM 메시지 게시 -> N초 후 최종 리마인더 (기본 60초)
  --once first       8PM 메시지 1회 게시 (cron 용)
  --once final       최종 리마인더 1회 게시 (cron 용)
  --once sync        Slack 메시지 없이 주문 상태를 시트에 1회 동기화 (cron 용)
  --once prep        다음 주 시트 탭 생성, Slack 메시지 없음 (금요일 밤 cron 용)
  --once settle      이번 주 주문자들에게 정산 리마인더 (금요일 15:00 cron 용)
  --run              내장 스케줄러로 상시 실행
  --friday / --no-friday
                     금요일 점심 포함 여부 (기본: 포함 - INCLUDE_FRIDAY 설정)
                     (20:00 / 금 15:00 settle / 금 21:00 prep / 22:00 / 23:00 KST,
                      주문 가능일 20:00~22:55에는 5분마다 시트 동기화)

Env vars:
  SLACK_BOT_TOKEN    xoxb-... (필수 scopes: chat:write, reactions:read, reactions:write
                     / 권장: users:read, channels:read 또는 groups:read - 없으면
                     이름을 시트 '명단' 탭에서 가져오는 폴백으로 동작)
  SLACK_CHANNEL_ID   C0XXXXXXX
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import holidays

import sheet_sync as _sheet_sync_mod

from sheet_sync import SHEET_ID, SETTLE_ACCOUNT, WEEK_DAY_COUNT, _name_keys  # 시트 ID/계좌/주 길이/이름
                                                # 매칭 단일 원본 (sheet_sync 상단은
                                                # 표준 라이브러리만 import)

try:
    import lunchbot_config as _local_config
except ImportError:
    _local_config = None


def _setting(name: str, default: str | None = None) -> str | None:
    """환경변수 우선, 없으면 로컬 Python 설정 파일에서 값을 읽는다."""
    return (os.environ.get(name)
            or getattr(_local_config, name, None)
            or default)

KST = ZoneInfo("Asia/Seoul")
STATE_FILE = Path(__file__).parent / "state.json"


def kdate(d: dt.date) -> str:
    """2026/08/20 (목) 형식"""
    return f"{d.year}/{d.month:02d}/{d.day:02d} ({'월화수목금토일'[d.weekday()]})"


def _week_span(any_day: dt.date) -> str:
    """그 주 점심 기간(월~목, 금요일 포함 시 월~금): 2026/08/17-2026/08/21 형식"""
    mon = any_day - dt.timedelta(days=any_day.weekday())
    last = mon + dt.timedelta(days=WEEK_DAY_COUNT - 1)
    return f"{mon:%Y/%m/%d}-{last:%Y/%m/%d}"

SPREADSHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit?usp=sharing"

RICE_EMOJI, SALAD_EMOJI = "rice", "green_salad"  # 🍚, 🥗 (Slack 이모지 이름)

_SLACK_ID_RE = re.compile(r"[UW][A-Z0-9]{6,}")


def _mention(u: str, at_names: bool = False) -> str:
    """Slack ID면 실제 멘션(<@ID>). ID를 못 찾은 사람은 이름 그대로,
    at_names=True면 @이름 형태로 표시 (실제 알림은 안 가지만 태그처럼 보임)."""
    if _SLACK_ID_RE.fullmatch(u):
        return f"<@{u}>"
    return f"@{u}" if at_names else u

FIRST_MSG = (
    "*내일 {date}* 점심 도시락 주문받습니다 - 이모지나 아래 spreadsheet에 체크 부탁드려요 😄\n"
    "밥을 원하시면 밥 이모지를 🍚, 샐러드를 원하시면 샐러드 이모지를 🥗 클릭해주세요\n"
    "- 샐러드가 포함된 식단표는 업체 카카오톡 프로필 사진에서 확인부탁드립니다 - ID: foodbox88\n"
    "- 수령은 건물 1층 왼쪽 입구 책상에서, 반납은 건물 뒷쪽 재활용 쓰레기 버리는 곳 옆에 반납부탁드립니다\n"
    f"{SPREADSHEET_URL}"
)

FINAL_MSG_TEMPLATE = (
    "*[Reminder] 내일 {date}* 점심 도시락 주문 받는 중입니다! 체크 안하신 분 이모지 or 스프레드시트에 체크 부탁드려요\n현재 인원 - {count}명 ({mentions})\n"
    "🍚 {rice}명 ({rice_mentions})\n"
    "🥗 {salad}명 ({salad_mentions})"
)

MIN_ORDER = 3  # 이 인원 미만이면 23시에 주문 취소 안내
MIDNIGHT_CANCEL_TEMPLATE = "최종 인원 {count}명 - *내일 {date}* 은 주문이 없습니다"
MIDNIGHT_CONFIRM_TEMPLATE = (
    "주문 확정 🎉 *내일 {date}* 총 {count}명 ({mentions})\n"
    "🍚 {rice}명 ({rice_mentions})\n"
    "🥗 {salad}명 ({salad_mentions})"
)

SETTLE_MSG_TEMPLATE = (          # 금요일 15:00 정산 리마인더 (금액은 언급하지 않음)
    "이번 주 ({week}) 점심 도시락값 정산 부탁드릴게요! 💸💸 계좌- {account}  "
    "\n정산 금액은 다음의 sheet 참조 - {link}\n해당 인원 - {mentions}"
)
SETTLE_NO_ORDER_MSG_TEMPLATE = "이번 주는 ({week}) 주문자가 없습니다! 정산은 생략 💸💸"

SKIP_IF_TODAY_IS_HOLIDAY = False     # 오늘이 휴일이어도, 내일이 근무일이면 발송
SKIP_IF_TOMORROW_IS_HOLIDAY = True   # 내일이 공휴일이면 (도시락 불필요) 안 보냄
SKIP_WEEKENDS = True                 # 내일이 주말이면 안 보냄
NO_LUNCH_WEEKDAYS: set[int] = set()  # 도시락 없는 요일 (0=월 ... 4=금) -> set_include_friday
                                     # 금요일 제외 시 {4}: 목요일 저녁 리마인더가 스킵됨
SETTLE_WEEKDAY = 4                   # 정산 기준 요일 (금). 휴일이면 그 주 마지막
                                     # 근무일로 앞당겨짐 -> _settle_day




def set_include_friday(include: bool) -> None:
    """금요일 점심 포함 여부를 봇 전체(스킵 로직 + 시트 주차 컬럼 수)에 반영."""
    global NO_LUNCH_WEEKDAYS, WEEK_DAY_COUNT
    _sheet_sync_mod.set_include_friday(include)
    WEEK_DAY_COUNT = _sheet_sync_mod.WEEK_DAY_COUNT
    NO_LUNCH_WEEKDAYS = set() if include else {4}


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("0", "false", "no", "off", "")


# 기본값은 금요일 포함. 환경변수/lunchbot_config.py의 INCLUDE_FRIDAY로 끌 수 있고,
# CLI의 --friday/--no-friday가 그보다 우선한다.
set_include_friday(_parse_bool(
    os.environ.get("INCLUDE_FRIDAY", getattr(_local_config, "INCLUDE_FRIDAY", True))))


# ---------------------------------------------------------------- holidays

def _is_off(day: dt.date) -> bool:
    kr = holidays.KR(years=day.year)
    if day in kr:
        return True
    if SKIP_WEEKENDS and day.weekday() >= 5:  # Sat=5, Sun=6
        return True
    return False


def _settle_day(any_day: dt.date) -> dt.date | None:
    """그 주 정산 메시지를 보낼 날 = 마지막 근무일(기본 금요일).

    금요일이 공휴일이면 목요일, 목·금이 다 휴일이면 수요일... 로 앞당긴다.
    월~금이 전부 휴일이면 None (그 주는 정산 메시지를 보내지 않음).
    """
    mon = any_day - dt.timedelta(days=any_day.weekday())
    for offset in range(SETTLE_WEEKDAY, -1, -1):
        day = mon + dt.timedelta(days=offset)
        if not _is_off(day):
            return day
    return None


def _is_first_lunch_day_of_week(lunch_day: dt.date) -> bool:
    """그 주의 첫 도시락 날인가 - 월요일이거나, 그 앞 요일이 전부 휴일/도시락 없는 날.
    (이날의 주문 메시지는 보통 직전 주말 저녁에 게시됨 -> 주간 식단표 이미지 동반)"""
    day = lunch_day - dt.timedelta(days=lunch_day.weekday())  # 그 주 월요일
    while day < lunch_day:
        if not _is_off(day) and day.weekday() not in NO_LUNCH_WEEKDAYS:
            return False
        day += dt.timedelta(days=1)
    return True


def should_send(now: dt.datetime) -> tuple[bool, str]:
    today, tomorrow = now.date(), now.date() + dt.timedelta(days=1)
    if SKIP_IF_TODAY_IS_HOLIDAY and _is_off(today):
        return False, f"skip: today {today} is a holiday/weekend"
    if SKIP_IF_TOMORROW_IS_HOLIDAY and _is_off(tomorrow):
        return False, f"skip: tomorrow {tomorrow} is a holiday/weekend"
    if tomorrow.weekday() in NO_LUNCH_WEEKDAYS:
        return False, f"skip: no lunch on {'월화수목금토일'[tomorrow.weekday()]}요일 ({tomorrow})"
    return True, "ok"


# ---------------------------------------------------------------- slack client

class SlackClient:
    """Thin wrapper; dry_run=True prints instead of calling the API."""

    def __init__(self, dry_run: bool):
        self.dry_run = dry_run
        if dry_run:
            self.client = None
            self.bot_user_id = "UBOT00000"
        else:
            from slack_sdk import WebClient
            token = _setting("SLACK_BOT_TOKEN")
            if not token:
                sys.exit("SLACK_BOT_TOKEN not set")
            self.client = WebClient(token=token)
            self.bot_user_id = self.client.auth_test()["user_id"]

    def post(self, channel: str, text: str) -> str:
        if self.dry_run:
            print(f"\n[DRY-RUN] would post to {channel}:\n---\n{text}\n---")
            return "1234567890.000001"  # fake ts
        resp = self.client.chat_postMessage(channel=channel, text=text)
        return resp["ts"]

    def upload_image(self, channel: str, path, comment: str = ""):
        if self.dry_run:
            print(f"[DRY-RUN] would upload image {path} to {channel} ({comment})")
            return
        self.client.files_upload_v2(
            channel=channel, file=str(path), initial_comment=comment
        )

    def get_channel_members(self, channel: str) -> dict[str, str]:
        """채널 전체 멤버 {ID: 이름}, 봇 제외 (scopes: channels:read 또는 groups:read)"""
        if self.dry_run:
            return {f"U0{i}{'ABCDE'[i-1]*7}": f"이름{'ABCDE'[i-1]*2}" for i in range(1, 6)}
        member_ids = []
        cursor = None
        while True:
            resp = self.client.conversations_members(channel=channel, cursor=cursor, limit=200)
            member_ids += resp["members"]
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        out = {}
        for uid in member_ids:
            try:
                u = self.client.users_info(user=uid)["user"]
                if u.get("is_bot") or uid == self.bot_user_id:
                    continue
                out[uid] = (u.get("profile", {}).get("display_name")
                            or u.get("real_name") or uid)
            except Exception:
                out[uid] = uid
        return out

    def get_user_names(self, uids) -> dict[str, str]:
        """개별 유저 이름 조회 폴백 - 반응한 사람만 조회 (scope: users:read)"""
        if self.dry_run:
            return {}
        out = {}
        for uid in uids:
            u = self.client.users_info(user=uid)["user"]
            out[uid] = (u.get("profile", {}).get("display_name")
                        or u.get("real_name") or uid)
        return out

    @staticmethod
    def _display_name(u: dict) -> str:
        prof = u.get("profile", {})
        return (prof.get("display_name") or prof.get("real_name")
                or u.get("real_name") or u.get("name") or u["id"])

    def _iter_users(self):
        """users.list 페이지네이션 (scope: users:read). 봇/비활성 계정 제외."""
        cursor = None
        while True:
            resp = self.client.users_list(cursor=cursor, limit=200)
            for u in resp["members"]:
                if not (u.get("is_bot") or u.get("deleted")):
                    yield u
            cursor = resp.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

    def get_all_users(self) -> dict[str, str]:
        """workspace 전체 {Slack ID: 현재 표시 이름} (scope: users:read).
        닉네임 변경 감지용 - 명단에 있는 ID의 최신 이름을 확인한다."""
        if self.dry_run:
            print("[DRY-RUN] would fetch workspace user list (닉네임 변경 확인)")
            return {}
        return {u["id"]: self._display_name(u) for u in self._iter_users()}

    def find_users_by_name(self, names) -> dict[str, str]:
        """이름 -> Slack ID (workspace 전체 users.list 검색, scope: users:read).
        표시 이름/실명 모두 별칭 키(_name_keys)로 비교 - 멘션용 ID 보충."""
        wanted: dict[str, str] = {}
        for n in names:
            for k in _name_keys(n):
                wanted.setdefault(k, n)
        if not wanted:
            return {}
        if self.dry_run:
            fake = {n: f"U9{i}FAKE00" for i, n in enumerate(sorted(set(names)), 1)}
            print(f"[DRY-RUN] would look up names via users.list -> {fake}")
            return fake
        out: dict[str, str] = {}
        for u in self._iter_users():
            prof = u.get("profile", {})
            for cand in (prof.get("display_name"), prof.get("real_name"),
                         u.get("real_name"), u.get("name")):
                for k in _name_keys(cand or ""):
                    if k in wanted:
                        out.setdefault(wanted[k], u["id"])
        return out

    def add_reaction(self, channel: str, ts: str, name: str):
        """봇이 메시지에 이모지를 미리 달아둠 -> 사람들은 클릭만 하면 됨 (scope: reactions:write)"""
        if self.dry_run:
            print(f"[DRY-RUN] would seed :{name}: reaction on {ts}")
            return
        try:
            self.client.reactions_add(channel=channel, timestamp=ts, name=name)
        except Exception as e:
            print(f"seed reaction :{name}: failed (reactions:write scope?): {e}")

    def get_reactions_by_emoji(self, channel: str, ts: str) -> dict[str, set[str]]:
        """이모지 이름 -> 반응한 유저 집합 (봇 자신 제외)"""
        if self.dry_run:
            # 봇 자신(UBOT00000)도 반응 목록에 포함시켜 제외 로직을 검증
            raw = {
                "rice": {self.bot_user_id, "U01AAAAAA", "U02BBBBBB"},
                "green_salad": {self.bot_user_id, "U03CCCCCC"},
            }
            fake = {k: v - {self.bot_user_id} for k, v in raw.items()}
            print(f"[DRY-RUN] raw reactions (bot included) -> {raw}")
            print(f"[DRY-RUN] after excluding bot -> {fake}")
            return fake
        resp = self.client.reactions_get(channel=channel, timestamp=ts)
        by_emoji: dict[str, set[str]] = {}
        for reaction in resp["message"].get("reactions", []):
            users = set(reaction["users"]) - {self.bot_user_id}
            if users:
                by_emoji[reaction["name"]] = users
        return by_emoji


# ---------------------------------------------------------------- jobs

def _channel_members(slack: SlackClient, channel: str,
                     reactors=()) -> dict[str, str]:
    """멤버 {Slack ID: 이름}. 성공하면 시트 '명단' 탭도 갱신해 둔다.

    조회 실패(channels:read/groups:read 스코프 누락 등) 시 폴백 순서:
      1) 시트 '명단' 탭 등에 기록된 이름 (load_roster)
      2) 반응한 유저(reactors)만 users_info로 개별 조회 (users:read)
    둘 다 안 되면 {} - 시트 동기화는 계속되고 이름 대신 ID가 기록됨.
    """
    members: dict[str, str] | None = None
    try:
        members = slack.get_channel_members(channel)
    except Exception as e:
        print(f"channel members unavailable (channels:read/groups:read scope?): {e}")
    if members is not None:
        # users:read 가 없으면 users_info 가 실패해 이름 자리에 ID가 들어오고,
        # 봇/사람 구분도 안 된다 -> 이런 항목은 프리필/명단 갱신에 쓰지 않는다
        named = {u: n for u, n in members.items() if not _SLACK_ID_RE.fullmatch(n)}
        if members and not named:
            print("멤버 이름을 못 받음 (users:read scope?) - 시트 명단으로 폴백")
            members = None
        else:
            members = named
    if members is not None:
        try:
            from sheet_sync import save_roster
            if False:  # participant-only roster policy; keep discovery read-only
                save_roster(members, dry_run=slack.dry_run)
        except Exception as e:
            print(f"roster save skipped: {e}")
    else:
        members = {}
        try:
            from sheet_sync import load_roster
            members = load_roster(dry_run=slack.dry_run)
        except Exception as e:
            print(f"roster load skipped: {e}")
        missing = [u for u in reactors if u not in members]
        if missing:
            try:
                members.update(slack.get_user_names(missing))
            except Exception as e:
                print(f"users_info fallback unavailable (users:read scope?): {e}")
        if members:
            print(f"fallback name map: {len(members)}명 (시트 명단/개별 조회)")
    # 채널 밖 workspace 신규 멤버도 명단에만 등록한다. 반환하는
    # members는 계속 채널 멤버만이므로 알림 채널 초대/대상에는 영향이 없다.
    # Roster writes are participant-driven in _tally; member discovery is read-only.
    # 멤버 맵을 만들 때마다 명단의 빈 Slack ID를 채우고(신규 인원),
    # Slack ID 기준으로 바뀐 닉네임을 시트에 반영한다 (주간 prep/매일 집계 공통)
    return members


def _sync_workspace_roster(slack: SlackClient) -> dict[str, str]:
    """workspace 전체 사람을 `명단`에 저장하되 채널에는 초대하지 않는다.

    users.list(users:read)만 사용하며 conversations.invite를 포함한 쓰기
    API는 호출하지 않는다. 스코프가 없어도 기존 알림은 계속 동작한다.
    """
    try:
        workspace_members = slack.get_all_users()
    except Exception as e:
        print(f"workspace roster sync unavailable (users:read scope?): {e}")
        return {}
    if not workspace_members:
        return {}
    try:
        from sheet_sync import save_roster
        save_roster(workspace_members, dry_run=slack.dry_run)
    except Exception as e:
        print(f"workspace roster save skipped: {e}")
        return {}
    print(f"workspace 명단 동기화: {len(workspace_members)}명 (채널 초대 없음)")
    return workspace_members


def _sync_roster_names(slack: SlackClient, known: dict[str, str]) -> dict:
    """닉네임 변경 반영: 명단에 적힌 Slack ID의 현재 표시 이름을 확인해 시트를 갱신.

    이름은 사람이 바꿀 수 있지만 Slack ID는 안 바뀌므로 ID를 기준으로 맞춘다.
    최신 이름 출처: 1) 방금 만든 멤버 맵 2) users.list (명단에 있는 ID만 사용).
    반환: {ID: (예전 이름, 새 이름)} - 호출부가 멤버 맵도 새 이름으로 맞추도록.
    """
    if slack.dry_run:
        print("[DRY-RUN] would reconcile 명단 names by Slack ID (닉네임 변경 추적)")
        return {}
    try:
        from sheet_sync import load_roster, sync_roster_names
        roster = load_roster(dry_run=slack.dry_run)
    except Exception as e:
        print(f"roster name sync skipped: {e}")
        return {}
    if not roster:
        return {}
    current = {uid: known[uid] for uid in roster if uid in (known or {})}
    if len(current) < len(roster):          # 멤버 API로 못 본 사람은 users.list로 확인
        try:
            everyone = slack.get_all_users()
        except Exception as e:
            print(f"name refresh unavailable (users:read scope?): {e}")
            everyone = {}
        current.update({u: n for u, n in everyone.items() if u in roster})
    try:
        return sync_roster_names(current, dry_run=slack.dry_run)
    except Exception as e:
        print(f"roster name sync skipped: {e}")
        return {}


def _refresh_roster_ids(slack: SlackClient, known: dict[str, str]) -> dict[str, str]:
    """'명단' 탭에서 Slack ID가 빈 사람을 자동으로 채운다 -> {ID: 이름}.

    1) 방금 만든 멤버 맵(known)으로 이름 매칭  2) 남으면 users.list 검색.
    한 번 채워두면 스코프가 막힌 환경에서도 시트만으로 멘션이 된다.
    이미 다 채워져 있으면 API 호출 없이 즉시 반환.
    """
    try:
        from sheet_sync import roster_missing_ids, save_roster
        missing = roster_missing_ids(dry_run=slack.dry_run)
    except Exception as e:
        print(f"roster id refresh skipped: {e}")
        return {}
    if not missing:
        return {}
    id_by_key = {k: uid for uid, n in (known or {}).items() for k in _name_keys(n)}
    found = {n: id_by_key[k] for n in missing
             for k in _name_keys(n) if k in id_by_key}
    rest = [n for n in missing if n not in found]
    if rest:
        try:
            found.update(slack.find_users_by_name(rest))
        except Exception as e:
            print(f"name lookup unavailable (users:read scope?): {e}")
    if not found:
        return {}
    by_id = {uid: n for n, uid in found.items()}
    try:
        save_roster(by_id, dry_run=slack.dry_run)
    except Exception as e:
        print(f"roster id save skipped: {e}")
        return {}
    print(f"명단 Slack ID 보충: {len(by_id)}명 ({', '.join(sorted(found))})")
    return by_id


def _resolve_mentions(slack: SlackClient, users, members) -> list[str]:
    """집계 결과(Slack ID 또는 이름)를 최대한 Slack ID로 바꿔 실제 멘션이 되게 한다.

    이름만 남은 사람은 1) 이미 아는 멤버 맵 2) users.list 검색 순으로 찾고,
    찾은 ID는 시트 '명단' 탭에도 적어 둬 다음부터는 API 없이도 멘션된다.
    끝내 못 찾으면 이름 그대로 남는다 (호출부에서 @이름으로 표시).
    """
    id_by_key: dict[str, str] = {}
    for uid, n in (members or {}).items():
        for k in _name_keys(n):
            id_by_key.setdefault(k, uid)

    out, unresolved = [], []
    for u in users:
        if _SLACK_ID_RE.fullmatch(u):
            out.append(u)
            continue
        uid = next((id_by_key[k] for k in _name_keys(u) if k in id_by_key), None)
        out.append(uid or u)
        if not uid:
            unresolved.append(u)

    if unresolved:
        found = {}
        try:
            found = slack.find_users_by_name(unresolved)
        except Exception as e:
            print(f"name lookup unavailable (users:read scope?): {e}")
        if found:
            out = [found.get(u, u) for u in out]
            try:  # 다음 실행부터는 시트 명단만으로 멘션 가능
                from sheet_sync import save_roster
                save_roster({uid: n for n, uid in found.items()},
                            dry_run=slack.dry_run)
            except Exception as e:
                print(f"roster save skipped: {e}")
        still = sorted({u for u in unresolved if u not in found})
        if still:
            print(f"멘션할 Slack ID를 못 찾음 -> @이름 텍스트로만 표시됨: {still}\n"
                  f"    해결: 시트 '명단' 탭의 'Slack ID' 열에 해당 사람의 ID를 적거나,\n"
                  f"    앱에 users:read / channels:read 스코프를 주고 재설치")

    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


def job_first(slack: SlackClient, channel: str, force: bool = False):
    now = dt.datetime.now(KST)
    ok, reason = should_send(now)
    if not ok and not force:
        print(f"[{now:%F %T}] {reason}")
        return
    lunch_day = now.date() + dt.timedelta(days=1)

    # 그 주의 첫 도시락 날에는 주간 식단표 전체를, 나머지 날에는 내일 날짜의
    # 열만 잘라서 올린다. 메뉴 텍스트 OCR은 정확도가 낮아 메시지에 사용하지 않는다.
    menu_img, upload_menu_img, week_menu = None, None, False
    try:
        from menu_fetch import (crop_day_menu_image, crop_week_menu_image,
                                fetch_latest_menu_image)
        menu_img = fetch_latest_menu_image(target_date=lunch_day)
        week_menu = _is_first_lunch_day_of_week(lunch_day)
        if menu_img and week_menu:
            # 한 이미지에 두 주가 쌓여 있는 주간표가 있어 이번 주만 잘라 올린다
            upload_menu_img = crop_week_menu_image(menu_img, lunch_day) or menu_img
        elif menu_img:
            upload_menu_img = crop_day_menu_image(menu_img, lunch_day)
    except Exception as e:
        print(f"menu fetch skipped: {e}")

    text = FIRST_MSG.format(date=kdate(lunch_day))
    ts = slack.post(channel, text)
    STATE_FILE.write_text(json.dumps({"ts": ts, "date": str(now.date())}))
    print(f"[{now:%F %T}] first message posted, ts={ts}")
    slack.add_reaction(channel, ts, RICE_EMOJI)
    slack.add_reaction(channel, ts, SALAD_EMOJI)

    # 시트 준비: 채널 멤버 프리필 + 오늘 날짜 컬럼 (실패해도 리마인더는 정상 동작)
    try:
        from sheet_sync import ensure_day_setup
        ensure_day_setup(lunch_day, kdate(lunch_day),
                         members=_channel_members(slack, channel),
                         dry_run=slack.dry_run)
    except Exception as e:
        print(f"sheet setup skipped: {e}")

    if menu_img:
        try:
            slack.upload_image(channel, upload_menu_img or menu_img,
                               comment=("이번 주 식단표 📋" if week_menu
                                        else f"내일 {kdate(lunch_day)} 식단 📋"))
        except Exception as e:
            print(f"menu image upload skipped: {e}")


def job_prep(slack: SlackClient, channel: str, force: bool = False):
    """금요일 밤: 다음 주 시트 탭을 맨 앞에 미리 생성하고 menu_images/ 를 비운다.
    Slack 메시지는 없음.
    인원 컬럼은 '명단' 탭 순서 그대로 - 채널 멤버/이번 주 탭에만 있는 이름은
    명단에도 추가된 뒤 뒤에 덧붙음."""
    now = dt.datetime.now(KST)
    next_mon = now.date() + dt.timedelta(days=7 - now.date().weekday())
    try:
        from sheet_sync import prep_week_tab, week_names
        members = _channel_members(slack, channel)
        extras = list(members.values()) + week_names(now.date(),
                                                     dry_run=slack.dry_run)
        prep_week_tab(next_mon, names=extras, dry_run=slack.dry_run)
    except Exception as e:
        print(f"week tab prep skipped: {e}")
    try:
        from menu_fetch import cleanup_menu_images
        print(f"menu images cleaned: {cleanup_menu_images(dry_run=slack.dry_run)} file(s)")
    except Exception as e:
        print(f"menu image cleanup skipped: {e}")
    print(f"[{now:%F %T}] week prep done (다음 주 월요일: {next_mon})")


def job_settle(slack: SlackClient, channel: str, force: bool = False):
    """그 주 마지막 근무일 15:00: 이번 주에 한 번이라도 주문한 사람들에게
    정산 리마인더. 금액은 언급하지 않고 시트 링크 + 멘션만. 주문자가 없으면 생략
    안내만 발송. 금요일이 공휴일이면 그 앞 근무일로 앞당겨 보낸다(_settle_day) -
    매일 15:00 에 --once settle 을 걸어 두면 알아서 그 날에만 나간다."""
    now = dt.datetime.now(KST)
    settle_day = _settle_day(now.date())
    if not force and now.date() != settle_day:
        print(f"[{now:%F %T}] settle skipped: 이번 주 정산일은 "
              f"{settle_day or '없음(전부 휴일)'}")
        return
    week = _week_span(now.date())
    try:
        from sheet_sync import week_orders
        members = _channel_members(slack, channel)
        eaters = week_orders(now.date(), members=members, dry_run=slack.dry_run)
    except Exception as e:
        print(f"[{now:%F %T}] settle reminder skipped (sheet error): {e}")
        return
    if not eaters:
        slack.post(channel, SETTLE_NO_ORDER_MSG_TEMPLATE.format(week=week))
        print(f"[{now:%F %T}] settle reminder posted: 이번 주 주문자 없음")
        return
    eaters = _resolve_mentions(slack, eaters, members)
    mentions = ", ".join(_mention(u, at_names=True) for u in sorted(eaters))
    slack.post(channel, SETTLE_MSG_TEMPLATE.format(week=week,
                                                   account=SETTLE_ACCOUNT,
                                                   link=SPREADSHEET_URL,
                                                   mentions=mentions))
    print(f"[{now:%F %T}] settle reminder posted ({len(eaters)}명)")


def _participant_roster_entries(slack: SlackClient, members: dict[str, str],
                                participants, sheet_names) -> list[tuple[str, str]]:
    """Build roster additions only from reactors and names on the active sheet.

    A sheet participant may be outside the channel, so unresolved candidate names
    are looked up in the workspace.  The lookup is restricted to those names; it
    never turns the full workspace member list into roster entries.
    """
    id_by_key = {key: uid for uid, name in (members or {}).items()
                 for key in _name_keys(name)}
    unresolved = [name for name in sheet_names
                  if not any(key in id_by_key for key in _name_keys(name))]
    found = {}
    if unresolved:
        try:
            found = slack.find_users_by_name(unresolved)
        except Exception as e:
            print(f"participant ID lookup unavailable (users:read scope?): {e}")

    entries = [(members.get(user, ""), user)
               if _SLACK_ID_RE.fullmatch(user) else (user, "")
               for user in participants]
    for name in sheet_names:
        uid = next((id_by_key[key] for key in _name_keys(name)
                    if key in id_by_key), found.get(name, ""))
        entries.append((name, uid))
    return entries


def _tally(slack: SlackClient, channel: str, state: dict):
    """이모지 반응 + 시트 직접 입력 집계, 이모지 -> 시트 동기화.
    returns (all_users, rice_users, salad_users)"""
    by_emoji = slack.get_reactions_by_emoji(channel, state["ts"])
    emoji_rice = set(by_emoji.get(RICE_EMOJI, set()))
    emoji_salad = set(by_emoji.get(SALAD_EMOJI, set()))
    rice, salad = set(emoji_rice), set(emoji_salad)
    everyone: set[str] = set().union(*by_emoji.values()) if by_emoji else set()

    # 시트 병합 + 동기화 (실패해도 이모지 집계는 정상 동작)
    try:
        from sheet_sync import read_day_orders, sync_reactions, classify_mark
        lunch_day = dt.date.fromisoformat(state["date"]) + dt.timedelta(days=1)
        members = _channel_members(slack, channel, reactors=sorted(everyone))
        prev_synced = state.get("synced", {})

        # 시트에 직접 체크한 사람 병합 (이모지 없이 시트만 체크해도 집계됨).
        # 봇이 지난 동기화에서 쓴 셀(prev_synced와 동일)은 이모지 반응이 원본이므로 제외
        # -> 반응을 취소한 사람이 시트 경유로 다시 집계되는 것을 방지.
        for uid, mark in read_day_orders(lunch_day, kdate(lunch_day),
                                         members=members,
                                         dry_run=slack.dry_run).items():
            if prev_synced.get(uid) == mark:
                continue
            everyone.add(uid)
            kind = classify_mark(mark)
            if kind == "rice":
                rice.add(uid)
            elif kind == "salad":
                salad.add(uid)

        # 이모지 반응 -> 시트 기록 (수동 입력 보존, 취소된 반응의 봇 기록은 삭제)
        state["synced"] = sync_reactions(
            lunch_day, kdate(lunch_day), emoji_rice, emoji_salad,
            names=members, prev_synced=prev_synced, dry_run=slack.dry_run)
        STATE_FILE.write_text(json.dumps(state))

        # 명단 탭에 없는 사람(이모지 반응자 / 시트에 이름만 쓴 사람) 자동 등록
        try:
            from sheet_sync import add_to_roster, day_sheet_names
            sheet_names = day_sheet_names(lunch_day, kdate(lunch_day),
                                          dry_run=slack.dry_run)
            entries = _participant_roster_entries(
                slack, members, everyone, sheet_names)
            add_to_roster(entries,
                          dry_run=slack.dry_run)
        except Exception as e:
            print(f"roster add skipped: {e}")
    except Exception as e:
        print(f"sheet sync skipped: {e}")
    return everyone, rice, salad


def _load_state(max_age_days: int = 0) -> dict | None:
    """오늘 20시 주문 메시지가 만든 state만 유효."""
    if not STATE_FILE.exists():
        print("no state file — was the 8PM message posted?")
        return None
    state = json.loads(STATE_FILE.read_text())
    posted = dt.date.fromisoformat(state["date"])
    age = (dt.datetime.now(KST).date() - posted).days
    if age > max_age_days:
        print(f"state is stale ({state['date']}) — 8PM message not posted today; skip")
        return None
    return state


def job_final(slack: SlackClient, channel: str, force: bool = False):
    now = dt.datetime.now(KST)
    ok, reason = should_send(now)
    if not ok and not force:
        print(f"[{now:%F %T}] {reason}")
        return
    state = _load_state()
    if not state:
        return
    users, rice, salad = _tally(slack, channel, state)
    lunch_day = dt.date.fromisoformat(state["date"]) + dt.timedelta(days=1)
    mentions = ", ".join(_mention(u) for u in sorted(users)) or "아직 없음"
    rice_mentions = ", ".join(_mention(u, at_names=True)
                               for u in sorted(rice)) or "없음"
    salad_mentions = ", ".join(_mention(u, at_names=True)
                                for u in sorted(salad)) or "없음"
    text = FINAL_MSG_TEMPLATE.format(
        date=kdate(lunch_day),
        count=len(users), mentions=mentions,
        rice=len(rice), rice_mentions=rice_mentions,
        salad=len(salad), salad_mentions=salad_mentions,
    )
    slack.post(channel, text)
    print(f"[{now:%F %T}] final message posted ({len(users)}명)")


def job_sync(slack: SlackClient, channel: str, force: bool = False):
    """주문 가능 시간의 5분 주기 동기화. Slack 메시지는 게시하지 않는다."""
    now = dt.datetime.now(KST)
    ok, reason = should_send(now)
    if not ok and not force:
        print(f"[{now:%F %T}] {reason}")
        return
    state = _load_state()
    if not state:
        return
    users, _rice, _salad = _tally(slack, channel, state)
    print(f"[{now:%F %T}] sheet status synced ({len(users)}명)")


def job_midnight(slack: SlackClient, channel: str, force: bool = False):
    """23:00 확정 메시지. 당일 20:00 메시지 state가 있을 때만 실행."""
    now = dt.datetime.now(KST)
    state = _load_state()
    if not state:
        return
    users, rice, salad = _tally(slack, channel, state)
    lunch_day = dt.date.fromisoformat(state["date"]) + dt.timedelta(days=1)
    if len(users) < MIN_ORDER:
        text = MIDNIGHT_CANCEL_TEMPLATE.format(count=len(users), date=kdate(lunch_day))
        # 취소된 날의 주문을 시트에서 지워야 Total/가격과 금요일 정산에 안 잡힌다
        try:
            from sheet_sync import cancel_day
            cancel_day(lunch_day, kdate(lunch_day), dry_run=slack.dry_run)
        except Exception as e:
            print(f"sheet cancel skipped: {e}")
    else:
        # 시트 기록은 _tally 안의 sync_reactions가 이미 처리
        mentions = ", ".join(_mention(u) for u in sorted(users))
        rice_mentions = ", ".join(_mention(u, at_names=True)
                                   for u in sorted(rice)) or "없음"
        salad_mentions = ", ".join(_mention(u, at_names=True)
                                    for u in sorted(salad)) or "없음"
        text = MIDNIGHT_CONFIRM_TEMPLATE.format(
            date=kdate(lunch_day),
            count=len(users), mentions=mentions,
            rice=len(rice), rice_mentions=rice_mentions,
            salad=len(salad), salad_mentions=salad_mentions,
        )
    slack.post(channel, text)
    print(f"[{now:%F %T}] 23:00 confirmation message posted "
          f"({len(users)}명, min={MIN_ORDER})")


# ---------------------------------------------------------------- entrypoints

# 예정 시각을 이만큼 지나면 그 슬롯은 포기한다 (한 시간 내내 열어 두지 않는다).
SCHEDULE_GRACE = dt.timedelta(minutes=10)
SYNC_GRACE = dt.timedelta(minutes=5)       # 5분 간격이라 다음 슬롯에 바로 넘긴다


def _slots(day: dt.date) -> list[tuple[str, dt.datetime, str]]:
    """그 날 예정된 (키, 실행 시각, job 이름) 전체 목록 - 실행 시각 순."""
    def at(hour: int, minute: int = 0) -> dt.datetime:
        return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=KST)

    out = [(f"{day}-first", at(20), "first"),
           (f"{day}-final", at(22), "final"),
           (f"{day}-midnight", at(23), "midnight")]
    if _settle_day(day) == day:                  # 그 주 마지막 근무일 (보통 금)
        out.append((f"{day}-settle", at(15), "settle"))
    if day.weekday() == 4:                       # 금요일 밤: 다음 주 탭 준비
        out.append((f"{day}-prep", at(21), "prep"))
    for hour in range(20, 23):                   # 20:00~22:55 5분 간격 시트 동기화
        for minute in range(0, 60, 5):
            if (hour, minute) <= (22, 55):
                out.append((f"{day}-sync-{hour:02d}{minute:02d}",
                            at(hour, minute), "sync"))
    return sorted(out, key=lambda slot: slot[1])


def _due_slots(now: dt.datetime, started: dt.datetime,
               fired: set[str]) -> list[tuple[str, dt.datetime, str]]:
    """지금 실행할 슬롯.

    스케줄러가 켜지기 전에 지나간 슬롯은 영구히 건너뛴다 - 21시에 다시 띄웠다고
    20시 주문 메시지가 그제서야 나가면 안 된다. 예정 시각을 SCHEDULE_GRACE 이상
    지난 슬롯도 마찬가지로 포기한다 (프로세스가 멈췄다 늦게 깨어난 경우).
    """
    start_slot = started.replace(second=0, microsecond=0)
    return [(key, at, name) for key, at, name in _slots(now.date())
            if key not in fired and at >= start_slot
            and at <= now < at + (SYNC_GRACE if name == "sync"
                                  else SCHEDULE_GRACE)]


def run_scheduler(slack: SlackClient, channel: str):
    """단순 루프 스케줄러.

    20:00 first / 22:00 final / 23:00 confirm, 주문 가능일 20:00~22:55에는
    매 5분 sheet sync. cron을 쓸 수 있으면 --once 권장.
    켜기 전에 지난 슬롯은 실행하지 않는다 (_due_slots). 지난 작업을 일부러
    돌리려면 --once <job> 으로 직접 실행하면 된다.
    """
    jobs = {"first": job_first, "final": job_final, "midnight": job_midnight,
            "sync": job_sync, "prep": job_prep, "settle": job_settle}
    started = dt.datetime.now(KST)
    fired: set[str] = set()
    todo = [slot for slot in _slots(started.date())
            if slot[1] >= started.replace(second=0, microsecond=0)]
    print("scheduler running (20:00 first / Fri 15:00 settle / Fri 21:00 prep / "
          "22:00 final / 23:00 confirm / every 5 min sheet sync, KST). "
          "Ctrl+C to stop.")
    print(f"[{started:%F %T}] 오늘 남은 슬롯 {len(todo)}개"
          + (f", 다음: {todo[0][2]} @ {todo[0][1]:%H:%M}" if todo else "")
          + " (이미 지난 슬롯은 실행하지 않음)")
    while True:
        now = dt.datetime.now(KST)
        for key, _at, name in _due_slots(now, started, fired):
            fired.add(key)
            jobs[name](slack, channel)
        fired = {key for key in fired if key.startswith(str(now.date()))}
        time.sleep(30)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--test", action="store_true", help="first now, final after --delay sec")
    p.add_argument("--delay", type=int, default=60)
    p.add_argument("--once", choices=["first", "final", "midnight", "sync",
                                      "prep", "settle"])
    p.add_argument("--run", action="store_true")
    p.add_argument("--force", action="store_true", help="휴일 체크 무시 (테스트용)")
    p.add_argument("--friday", action=argparse.BooleanOptionalAction, default=None,
                   help="금요일 점심 포함 (--no-friday: 월~목만). 기본: INCLUDE_FRIDAY 설정")
    args = p.parse_args()
    if args.friday is not None:
        set_include_friday(args.friday)
    print(f"lunch days: {'월~금' if 4 not in NO_LUNCH_WEEKDAYS else '월~목'}")

    channel = _setting("SLACK_CHANNEL_ID", "C_TEST_CHANNEL")
    slack = SlackClient(dry_run=args.dry_run)

    # --once가 --test보다 우선 - 둘 다 주면 지정한 job 하나만 실행
    if args.once:
        if args.test:
            print(f"--test 무시: --once {args.once} 만 실행합니다")
        jobs = {"first": job_first, "final": job_final, "sync": job_sync,
                "midnight": job_midnight, "prep": job_prep, "settle": job_settle}
        jobs[args.once](slack, channel, force=args.force)
    elif args.test:
        job_first(slack, channel, force=args.force)
        print(f"... waiting {args.delay}s (지금 이모지를 눌러보세요) ...")
        time.sleep(args.delay)
        job_final(slack, channel, force=args.force)
        print(f"... waiting {args.delay}s (23시 확정 메시지 테스트) ...")
        time.sleep(args.delay)
        job_midnight(slack, channel, force=args.force)
    elif args.run:
        run_scheduler(slack, channel)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
