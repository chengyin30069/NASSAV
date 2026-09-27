"""Optional browser credentials for sites protected by Cloudflare."""

from pathlib import Path
import json
from urllib.request import Request, urlopen


def browser_headers(settings: dict, project_root: str) -> dict[str, str]:
    """Read an optional two-line cookie/UA file, then apply explicit overrides."""
    cookie = ""
    user_agent = ""
    cookie_file = settings.get("CookieFile", "")
    if cookie_file:
        path = Path(cookie_file)
        if not path.is_absolute():
            path = Path(project_root) / path
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ValueError(f"Cannot read Cloudflare CookieFile: {path}") from exc
        if len(lines) != 2:
            raise ValueError("Cloudflare CookieFile must contain a cookie and a user agent on separate lines")
        cookie, user_agent = (line.strip() for line in lines)

    cookie = settings.get("Cookie", "").strip() or cookie
    user_agent = settings.get("UserAgent", "").strip() or user_agent
    headers = {}
    if cookie:
        headers["Cookie"] = cookie
    if user_agent:
        headers["User-Agent"] = user_agent
    return headers


def solve_page(url: str, solver_url: str, timeout: int = 30) -> str:
    """Retrieve a challenged page through a browser-based solver service."""
    request = Request(
        solver_url,
        data=json.dumps({"cmd": "request.get", "url": url, "maxTimeout": timeout * 1000}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=timeout + 10) as response:
        result = json.load(response)
    solution = result.get("solution") or {}
    html = solution.get("response") or ""
    if result.get("status") != "ok" or solution.get("status") != 200:
        raise ValueError("Browser solver did not return a successful page")
    if "Just a moment..." in html or not html:
        raise ValueError("Browser solver returned a Cloudflare challenge")
    return html
