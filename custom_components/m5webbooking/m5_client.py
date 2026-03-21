from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Dict, List
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


_LOGGER = logging.getLogger(__name__)


MONTH_NAME_TO_NUMBER: dict[str, int] = {
    # Swedish
    "jan": 1,
    "januari": 1,
    "feb": 2,
    "februari": 2,
    "mar": 3,
    "mars": 3,
    "apr": 4,
    "april": 4,
    "maj": 5,
    "jun": 6,
    "juni": 6,
    "jul": 7,
    "juli": 7,
    "aug": 8,
    "augusti": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "okt": 10,
    "oktober": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
    # English
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "oct": 10,
    "october": 10,
    "november": 11,
    "december": 12,
}


class M5ClientError(Exception):
    """Base error for M5 client failures."""


class M5InvalidUrlError(M5ClientError):
    """Raised when configured address is not a valid HTTP(S) URL."""


class M5CannotConnectError(M5ClientError):
    """Raised when the M5 endpoint cannot be reached."""


class M5InvalidAuthError(M5ClientError):
    """Raised when credentials do not allow access behind login."""


class M5UnexpectedResponseError(M5ClientError):
    """Raised when endpoint does not match expected M5 pages."""


@dataclass
class RoomStatus:
    name: str          # e.g. "Tvättstuga 2"
    title: str         # e.g. "Tvätt 2 (Ledig)"
    booked_by_me: bool # from hidden input
    occupied: bool     # derived
    next_booking_start: datetime | None = None  # next time it becomes occupied


class M5Client:
    def __init__(self, address: str, username: str, password: str) -> None:
        self._address = address.rstrip("/")
        self._base = self._normalize_base_url(self._address)
        self._username = username
        self._password = password
        self._session: requests.Session | None = None
        self._request_timeout = 10

    @staticmethod
    def _normalize_base_url(address: str) -> str:
        """Return base URL ending in M5WebBokning unless a valid M5 path is provided."""
        parsed = urlparse(address)
        path = parsed.path.rstrip("/")
        lower_path = path.lower()

        if lower_path.endswith("/m5webbokning") or lower_path.endswith("/m5webbooking"):
            base_path = path
        elif path:
            base_path = f"{path}/M5WebBokning"
        else:
            base_path = "/M5WebBokning"

        normalized = parsed._replace(path=base_path, params="", query="", fragment="")
        return normalized.geturl().rstrip("/")

    @property
    def _login_url(self) -> str:
        return f"{self._base}/Default.aspx"

    @property
    def _protected_url(self) -> str:
        return f"{self._base}/Booking/BookingMain.aspx"

    @staticmethod
    def _is_valid_http_url(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)

    @staticmethod
    def _looks_like_login_page(soup: BeautifulSoup) -> bool:
        username_input = soup.find("input", id=lambda i: i and i.endswith("tbUsername"))
        password_input = soup.find("input", id=lambda i: i and i.endswith("tbPassword"))
        return username_input is not None and password_input is not None

    @staticmethod
    def _extract_hidden_field(soup: BeautifulSoup, name: str) -> str:
        field = soup.find("input", {"name": name})
        if field is None or "value" not in field.attrs:
            raise M5UnexpectedResponseError(f"Missing hidden field: {name}")
        return field["value"]

    def _request(self, session: requests.Session, method: str, url: str, **kwargs) -> requests.Response:
        _LOGGER.debug("M5 request: %s %s", method.upper(), url)
        kwargs.setdefault("timeout", self._request_timeout)
        try:
            response = session.request(method=method, url=url, **kwargs)
        except requests.Timeout as err:
            raise M5CannotConnectError("Request timed out") from err
        except requests.RequestException as err:
            raise M5CannotConnectError("Request failed") from err
        _LOGGER.debug(
            "M5 response: %s %s -> %s (final_url=%s)",
            method.upper(),
            url,
            response.status_code,
            response.url,
        )
        return response

    def _response_is_login(self, response: requests.Response, soup: BeautifulSoup) -> bool:
        """Return True if a protected request ended up on the login page."""
        return "default.aspx" in str(response.url).lower() or self._looks_like_login_page(soup)

    def _invalidate_session(self) -> None:
        """Drop the current HTTP session and force a fresh login on next request."""
        self._session = None

    def _get_protected_soup(self, url: str) -> BeautifulSoup:
        """Fetch a protected page, re-authenticating once if session expired."""
        session = self._ensure_session()
        response = self._request(session, "get", url)
        soup = BeautifulSoup(response.text, "html.parser")

        if not self._response_is_login(response, soup):
            return soup

        _LOGGER.info("M5 session appears expired; attempting re-authentication")
        self._invalidate_session()

        session = self._ensure_session()
        retry_response = self._request(session, "get", url)
        retry_soup = BeautifulSoup(retry_response.text, "html.parser")
        if self._response_is_login(retry_response, retry_soup):
            raise M5InvalidAuthError("Re-authentication failed for protected page")

        return retry_soup

    @staticmethod
    def _infer_year_for_month_day(month: int, day: int, reference: datetime | None = None) -> int:
        """Infer year for parsed month/day close to a reference date.

        This avoids year-boundary errors when pages omit explicit year.
        """
        ref = reference or datetime.now()
        candidates: list[tuple[int, int]] = []
        for year in (ref.year - 1, ref.year, ref.year + 1):
            try:
                candidate = datetime(year, month, day)
            except ValueError:
                continue
            distance = abs((candidate.date() - ref.date()).days)
            candidates.append((distance, year))

        if not candidates:
            return ref.year

        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def validate_connection(self) -> None:
        """Validate endpoint availability and that credentials can access a protected page."""
        if not self._is_valid_http_url(self._address):
            raise M5InvalidUrlError("Address must be a valid HTTP(S) URL")

        session = requests.Session()

        try:
            login_resp = self._request(session, "get", self._login_url, timeout=10)
        except requests.RequestException as err:
            raise M5CannotConnectError("Unable to reach login endpoint") from err

        if login_resp.status_code != 200:
            raise M5CannotConnectError(f"Login endpoint returned status {login_resp.status_code}")

        login_soup = BeautifulSoup(login_resp.text, "html.parser")

        try:
            viewstate = self._extract_hidden_field(login_soup, "__VIEWSTATE")
            eventvalidation = self._extract_hidden_field(login_soup, "__EVENTVALIDATION")
            viewstategenerator = self._extract_hidden_field(login_soup, "__VIEWSTATEGENERATOR")
        except M5UnexpectedResponseError as err:
            raise M5InvalidUrlError("Endpoint is reachable but not a valid M5 login page") from err

        data = {
            "__EVENTTARGET": "ctl00$ContentPlaceHolder1$btOK",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstategenerator,
            "__EVENTVALIDATION": eventvalidation,
            "ctl00$MessageType": "ERROR",
            "ctl00$ContentPlaceHolder1$tbUsername": self._username,
            "ctl00$ContentPlaceHolder1$tbPassword": self._password,
        }

        try:
            login_post_resp = self._request(session, "post", self._login_url, data=data, timeout=10)
            protected_resp = self._request(session, "get", self._protected_url, timeout=10)
        except requests.RequestException as err:
            raise M5CannotConnectError("Unable to complete login request") from err

        if login_post_resp.status_code != 200:
            raise M5CannotConnectError(f"Login POST returned status {login_post_resp.status_code}")

        if protected_resp.status_code != 200:
            raise M5CannotConnectError(
                f"Protected page returned status {protected_resp.status_code}"
            )

        protected_soup = BeautifulSoup(protected_resp.text, "html.parser")
        if "default.aspx" in str(protected_resp.url).lower() or self._looks_like_login_page(
            protected_soup
        ):
            raise M5InvalidAuthError("Credentials are not accepted")

        self._session = session

    def _ensure_session(self) -> requests.Session:
        if self._session is not None:
            return self._session

        session = requests.Session()
        login_url = self._login_url

        resp = self._request(session, "get", login_url)
        soup = BeautifulSoup(resp.text, "html.parser")

        viewstate = soup.find("input", {"name": "__VIEWSTATE"})["value"]
        eventvalidation = soup.find("input", {"name": "__EVENTVALIDATION"})["value"]
        viewstategenerator = soup.find("input", {"name": "__VIEWSTATEGENERATOR"})["value"]

        data = {
            "__EVENTTARGET": "ctl00$ContentPlaceHolder1$btOK",
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstategenerator,
            "__EVENTVALIDATION": eventvalidation,
            "ctl00$MessageType": "ERROR",
            "ctl00$ContentPlaceHolder1$tbUsername": self._username,
            "ctl00$ContentPlaceHolder1$tbPassword": self._password,
        }

        self._request(session, "post", login_url, data=data)
        self._session = session
        return session

    def _get_soup(self, url: str) -> BeautifulSoup:
        return self._get_protected_soup(url)

    def fetch_status(self) -> List[RoomStatus]:
        status_url = f"{self._base}/Machine/MachineGroupStat.aspx"
        soup = self._get_protected_soup(status_url)

        boxes = soup.select("div[style*='border: thin solid'][style*='width: 365px']")
        rooms: List[RoomStatus] = []

        for box in boxes:
            header = box.find_previous(
                "div",
                style=lambda s: s and "clear: left; height: 29px;" in s,
            )

            machine_name = None
            if header:
                name_span = header.find(
                    "span",
                    id=lambda i: i and i.endswith("MachineName"),
                )
                if name_span:
                    machine_name = name_span.get_text(strip=True)

            title_span = box.find(
                "span",
                id=lambda i: i and i.endswith("MaskGrpTitle"),
            )
            title = title_span.get_text(strip=True) if title_span else ""

            booked_input = box.find(
                "input",
                id=lambda i: i and i.endswith("BookedByMe"),
            )
            booked_by_me = booked_input["value"] == "True" if booked_input else False

            label = machine_name or title or f"item_{len(rooms) + 1}"

            text_lower = title.lower()
            # Treat as occupied if it says not free / booked
            occupied = any(
                marker in text_lower
                for marker in ("ej ledig", "bokad", "not free", "booked", "occupied")
            )

            rooms.append(
                RoomStatus(
                    name=label,
                    title=title,
                    booked_by_me=booked_by_me,
                    occupied=occupied,
                )
            )

        return rooms

    # --- Booking calendar helpers ---

    def list_prechoices(self) -> list[dict[str, str]]:
        """Return all selectable resources from Prechoices.aspx.

        Each item is {"name": display_name, "event_target": postback target}.
        """
        prechoices_url = f"{self._base}/Booking/Prechoices.aspx"
        soup = self._get_soup(prechoices_url)

        table = soup.find("table", id="ctl00_ContentPlaceHolder1_dgForval")
        if not table:
            return []

        results: list[dict[str, str]] = []
        rows = table.find_all("tr")
        for row in rows:
            link = row.find("a", href=True)
            if not link:
                continue
            name = link.get_text(strip=True)
            href = link["href"]

            event_target: str | None = None
            if "__doPostBack(" in href:
                try:
                    inside = href.split("(", 1)[1].rsplit(")", 1)[0]
                    first_arg = inside.split(",", 1)[0].strip()
                    event_target = first_arg.strip("'\"")
                except Exception:
                    event_target = None

            if event_target:
                results.append({"name": name, "event_target": event_target})

        return results

    def _select_prechoice(self, name: str) -> bool:
        """Post to Prechoices.aspx to select a resource by name."""
        prechoices_url = f"{self._base}/Booking/Prechoices.aspx"
        session = self._ensure_session()

        resp = self._request(session, "get", prechoices_url)
        soup = BeautifulSoup(resp.text, "html.parser")

        viewstate = soup.find("input", {"name": "__VIEWSTATE"})["value"]
        eventvalidation = soup.find("input", {"name": "__EVENTVALIDATION"})["value"]
        viewstategenerator = soup.find("input", {"name": "__VIEWSTATEGENERATOR"})["value"]

        table = soup.find("table", id="ctl00_ContentPlaceHolder1_dgForval")
        if not table:
            return False

        event_target: str | None = None
        for row in table.find_all("tr"):
            link = row.find("a", href=True)
            if not link:
                continue
            display_name = link.get_text(strip=True)
            if display_name != name:
                continue
            href = link["href"]
            if "__doPostBack(" in href:
                try:
                    inside = href.split("(", 1)[1].rsplit(")", 1)[0]
                    first_arg = inside.split(",", 1)[0].strip()
                    event_target = first_arg.strip("'\"")
                except Exception:
                    event_target = None
            break

        if not event_target:
            return False

        data = {
            "__EVENTTARGET": event_target,
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstategenerator,
            "__EVENTVALIDATION": eventvalidation,
        }

        self._request(session, "post", prechoices_url, data=data)
        return True

    def fetch_booked_slots(self, resource_name: str) -> list[dict]:
        """Return booked/blocked time slots for a given resource over the current week.

        Each item is a dict with keys: date (date), start (datetime), end (datetime), status (str).
        """
        if not self._select_prechoice(resource_name):
            return []

        calendar_url = f"{self._base}/Booking/BookingCalendar.aspx"
        soup = self._get_protected_soup(calendar_url)

        # Month and year
        month_label = soup.find("span", id=lambda i: i and i.endswith("lbCalendarDatum"))
        month_str = month_label.get_text(strip=True).lower() if month_label else ""
        month = MONTH_NAME_TO_NUMBER.get(month_str, datetime.now().month)

        # Day headers: lbCalendarDag0..lbCalendarDag6 → map column index → date
        col_dates: dict[int, datetime.date] = {}
        day_numbers: dict[int, int] = {}
        for idx in range(7):
            span = soup.find("span", id=lambda i, idx=idx: i and i.endswith(f"lbCalendarDag{idx}"))
            if not span:
                continue
            text = span.get_text(separator=" ", strip=True)
            parts = text.split()
            if len(parts) < 2:
                continue
            try:
                day_num = int(parts[-1])
            except ValueError:
                continue
            day_numbers[idx] = day_num

        if day_numbers:
            first_idx = min(day_numbers)
            first_day = day_numbers[first_idx]
            cur_month = month
            cur_year = self._infer_year_for_month_day(cur_month, first_day)
            prev_day: int | None = None

            for idx in sorted(day_numbers):
                day_num = day_numbers[idx]
                if prev_day is not None and day_num < prev_day:
                    cur_month += 1
                    if cur_month > 12:
                        cur_month = 1
                        cur_year += 1

                try:
                    col_dates[idx] = datetime(cur_year, cur_month, day_num).date()
                except ValueError:
                    fallback_year = self._infer_year_for_month_day(cur_month, day_num)
                    col_dates[idx] = datetime(fallback_year, cur_month, day_num).date()
                prev_day = day_num

        # Find the calendar row that contains the time-slot columns
        calendar_tables = soup.find_all("table")
        slot_tds = []
        for table in calendar_tables:
            rows = table.find_all("tr", recursive=False)
            for row in rows:
                tds = row.find_all("td", recursive=False)
                day_like = [td for td in tds if td.get("width") == "85"]
                if len(day_like) >= 7 and any(td.find("input", {"type": "image"}) for td in day_like):
                    slot_tds = day_like
                    break
            if slot_tds:
                break

        if not slot_tds:
            return []

        bookings: list[dict] = []

        for col_index, td in enumerate(slot_tds):
            if col_index not in col_dates:
                continue
            col_date = col_dates[col_index]

            inputs = td.find_all("input", {"type": "image"})
            for inp in inputs:
                title = inp.get("title")
                if not title:
                    continue

                # title like "20:00-23:00 (Ledigt)" or "08:00-11:00 (Ej bokningsbar)"
                try:
                    time_part, status_part = title.split("(", 1)
                except ValueError:
                    continue

                time_part = time_part.strip()
                status = status_part.rstrip(")").strip()

                # Only treat non-Ledigt as booked/blocked; adjust if needed
                status_lower = status.lower()
                if status_lower.startswith(("ledigt", "free", "available")):
                    continue

                try:
                    start_str, end_str = [t.strip() for t in time_part.split("-")]
                    start_t = datetime.strptime(start_str, "%H:%M").time()
                    end_t = datetime.strptime(end_str, "%H:%M").time()
                except ValueError:
                    continue

                start_dt = datetime.combine(col_date, start_t)
                end_dt = datetime.combine(col_date, end_t)
                if end_dt <= start_dt:
                    end_dt += timedelta(days=1)

                bookings.append(
                    {
                        "date": col_date,
                        "start": start_dt,
                        "end": end_dt,
                        "status": status,
                        "resource": resource_name,
                    }
                )

        # Sort by start time
        bookings.sort(key=lambda b: b["start"])
        return bookings

    # --- User booking list ("My bookings") ---

    def fetch_user_bookings(self) -> list[dict]:
        """Return current user's bookings as a list of dicts.

        Each dict has: date (str as shown on page), name (str), start (datetime), end (datetime).
        """
        bookings_url = f"{self._base}/Booking/BookingMain.aspx"
        soup = self._get_protected_soup(bookings_url)

        table = soup.find("table", id="ctl00_ContentPlaceHolder1_DataGridBookings")
        if not table:
            return []

        bookings: list[dict] = []
        rows = table.find_all("tr")
        for row in rows:
            cols = row.find_all("td")
            values = [c.get_text(strip=True) for c in cols]
            if len(values) < 5:
                continue

            date_str = values[0]
            name = values[1]
            start_time_str = values[2]
            end_time_str = values[4]

            parts = date_str.split()
            if len(parts) < 3:
                continue

            day_str = parts[1]
            month_str = parts[2].lower()
            if month_str not in MONTH_NAME_TO_NUMBER:
                continue

            try:
                day = int(day_str)
            except ValueError:
                continue

            month = MONTH_NAME_TO_NUMBER[month_str]
            year = self._infer_year_for_month_day(month, day)
            date = datetime(year, month, day)

            try:
                start_t = datetime.strptime(start_time_str, "%H:%M").time()
                end_t = datetime.strptime(end_time_str, "%H:%M").time()
            except ValueError:
                continue

            start_dt = datetime.combine(date.date(), start_t)
            end_dt = datetime.combine(date.date(), end_t)
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)

            bookings.append(
                {
                    "date": date_str,
                    "name": name,
                    "start": start_dt,
                    "end": end_dt,
                }
            )

        bookings.sort(key=lambda b: b["start"])
        return bookings