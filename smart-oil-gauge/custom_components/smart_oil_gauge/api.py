"""
API client for the Smart Oil Gauge web application.

This module is responsible *only* for:
- Talking to the remote HTTP endpoints (login + AJAX tank list)
- Parsing / validating responses
- Converting low-level HTTP/JSON issues into integration-specific exceptions

It deliberately knows nothing about Home Assistant. The integration code
(__init__.py, sensor.py, etc.) uses this client via SmartOilClient and
reacts to AuthError / ApiError accordingly.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, Optional

import aiohttp

from .const import AJAX_URL, LOGIN_URL

_LOGGER = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# Constants & regex helpers
# --------------------------------------------------------------------------------------

# The login form on app.smartoilgauge.com includes a hidden input "ccf_nonce"
# with a random value that must be submitted with credentials.
_NONCE_RE = re.compile(r'name=["\']ccf_nonce["\']\s+value=["\']([^"\']+)["\']', re.I)

# Field names in the login form POST body
USER_FIELD = "username"
PASS_FIELD = "user_pass"

# Timeouts in seconds for HTTP calls
DEFAULT_TIMEOUT = 15


# --------------------------------------------------------------------------------------
# Custom exceptions
# --------------------------------------------------------------------------------------
class AuthError(Exception):
    """Authentication failed or session expired.

    The coordinator treats this as a *recoverable* error that can often
    be fixed by re-logging in with the same credentials, unless the
    credentials are actually invalid (in which case reauth is needed).
    """


class ApiError(Exception):
    """Non-auth API error (network issues, invalid data, etc.)."""


# --------------------------------------------------------------------------------------
# SmartOilClient implementation
# --------------------------------------------------------------------------------------
class SmartOilClient:
    """Thin wrapper around aiohttp.ClientSession for the Smart Oil Gauge API."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """
        Initialize the client with a shared aiohttp session.

        The session is created and managed by Home Assistant via
        async_get_clientsession(hass). We must NOT create our own session
        so that HA can manage connection pools, SSL, proxies, etc.
        """
        self._session = session

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _fetch_nonce(self) -> Optional[str]:
        """
        Fetch the login page and extract the 'ccf_nonce' hidden field.

        This nonce is typically required when posting credentials to the
        login endpoint. If we cannot extract it, we simply proceed without it
        and let the server decide, though it is not expected to work.
        """
        _LOGGER.debug("SmartOilClient: fetching login page to obtain nonce")

        try:
            async with self._session.get(LOGIN_URL, timeout=DEFAULT_TIMEOUT) as resp:
                text = await resp.text()
        except asyncio.TimeoutError as err:
            raise ApiError("Timeout fetching login page") from err
        except aiohttp.ClientError as err:
            raise ApiError(f"Error fetching login page: {err}") from err

        match = _NONCE_RE.search(text)
        if not match:
            _LOGGER.debug(
                "SmartOilClient: no ccf_nonce hidden field found on login page"
            )
            return None

        nonce = match.group(1)
        _LOGGER.debug("SmartOilClient: extracted ccf_nonce=%s", nonce)
        return nonce

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------
    async def login(self, username: str, password: str) -> None:
        """
        Perform login with the given username and password.

        This method:
        - Fetches the nonce from the login page (if available).
        - POSTs the credentials + nonce back to LOGIN_URL.
        - Inspects the resulting HTML to see if we are still on a login page
          or obviously unauthenticated, and raises AuthError in that case.

        On success, any auth cookies set by the server are stored in the
        underlying aiohttp.ClientSession and reused by subsequent requests.
        """
        nonce = await self._fetch_nonce()

        data = {
            USER_FIELD: username,
            PASS_FIELD: password,
        }
        if nonce:
            data["ccf_nonce"] = nonce

        headers = {
            "Origin": "https://app.smartoilgauge.com",
            "Referer": LOGIN_URL,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0",
        }

        _LOGGER.debug("SmartOilClient: posting login for user=%s", username)

        try:
            async with self._session.post(
                LOGIN_URL,
                data=data,
                headers=headers,
                allow_redirects=True,
                timeout=DEFAULT_TIMEOUT,
            ) as resp:
                # If the server returns explicit HTTP errors (4xx/5xx), treat as auth or API error
                if resp.status >= 500:
                    raise ApiError(f"Login failed with HTTP {resp.status}")
                if resp.status in (401, 403):
                    raise AuthError(f"Login unauthorized, HTTP {resp.status}")

                text = await resp.text()

        except asyncio.TimeoutError as err:
            raise ApiError("Timeout posting login form") from err
        except aiohttp.ClientError as err:
            raise ApiError(f"HTTP error during login: {err}") from err

        # Heuristic: if the returned page still looks like a login form, login likely failed.
        # We look for markers like the password field name or typical "Login" text.
        if 'name="user_pass"' in text or "user_pass" in text:
            # This strongly suggests we are still on the login page.
            raise AuthError("Login form still present after POST; bad credentials?")
        if "Login" in text and "Smart Oil Gauge" in text:
            # Some variants may show a generic login page.
            raise AuthError("Login page returned; credentials may be invalid")

        _LOGGER.debug("SmartOilClient: login POST completed without obvious errors")

    async def get_tanks_list(self) -> Dict[str, Any]:
        """
        Fetch the list of tanks via the AJAX API.

        This method:
        - POSTs to AJAX_URL with the appropriate 'action' payload.
        - Requires a valid authenticated session (cookies set by login()).
        - Validates that the response is JSON.
        - Interprets API-level status codes (401/403) as AuthError.
        - Raises ApiError for network problems, timeouts, or malformed data.

        The coordinator expects the returned data to be a dict, ideally with:
            { "tanks": [ { ...tank fields... }, ... ] }
        """
        payload = "action=get_tanks_list&tank_id=0"
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json",
            "Origin": "https://app.smartoilgauge.com",
            "Referer": "https://app.smartoilgauge.com/",
            "User-Agent": "Mozilla/5.0",
        }

        _LOGGER.debug("SmartOilClient: requesting tank list from AJAX endpoint")

        try:
            async with self._session.post(
                AJAX_URL,
                data=payload,
                headers=headers,
                timeout=DEFAULT_TIMEOUT,
            ) as resp:
                # If unauthenticated at HTTP level, raise AuthError immediately
                if resp.status in (401, 403):
                    raise AuthError(
                        f"Tank list request unauthorized, HTTP {resp.status}"
                    )

                # For other 4xx/5xx, treat as a generic API error
                if resp.status >= 400:
                    raise ApiError(f"Tank list request failed with HTTP {resp.status}")

                # Capture Content-Type before reading body
                ctype = resp.headers.get("Content-Type", "")
                text = await resp.text()

                # If the response is not JSON, check if it looks like a login page
                if "application/json" not in ctype:
                    if "ccf_nonce" in text or "user_pass" in text or "Login" in text:
                        # Backend sent us an HTML login page instead of JSON
                        raise AuthError("Session expired or not authenticated")
                    raise ApiError(f"Unexpected content type: {ctype!r}")

                # Now we know it's supposed to be JSON
                try:
                    data: Any = await resp.json()
                except Exception as err:  # JSON decoding error
                    raise ApiError(f"Failed to decode JSON: {err}") from err

        except asyncio.TimeoutError as err:
            raise ApiError("Timeout talking to SmartOilGauge") from err
        except aiohttp.ClientError as err:
            raise ApiError(f"HTTP error talking to SmartOilGauge: {err}") from err

        # Interpret API-level "Status" codes in the JSON body, if present
        if isinstance(data, dict):
            status = data.get("Status")
            if status in (401, 403):
                # Some responses are JSON objects with Status=401
                raise AuthError(f"API returned unauthorized status: {status}")

            # Some successful responses include result: "ok".
            result = data.get("result")
            if result is not None and str(result).lower() != "ok":
                # Non-ok result indicates an application-level error
                raise ApiError(f"API result error: {result}")

        # At this point we consider the data valid.
        _LOGGER.debug(
            "SmartOilClient: successfully fetched tank list (type=%s)",
            type(data),
        )
        return data  # type: ignore[return-value]
