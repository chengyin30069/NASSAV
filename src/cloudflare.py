"""Optional browser credentials for sites protected by Cloudflare."""

from pathlib import Path


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
