"""Offer Sukebei torrents as an interactive fallback."""

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unicodedata
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from curl_cffi import requests
from loguru import logger


_BASE_URL = "https://sukebei.nyaa.si/"
_NYAA = "{https://sukebei.nyaa.si/xmlns/nyaa}"


@dataclass(frozen=True)
class Torrent:
    torrent_id: str
    title: str
    size: str
    seeders: int


def _match_code(avid: str):
    parts = avid.split("-")
    if len(parts) == 3 and parts[:2] == ["FC2", "PPV"]:
        code = rf"FC2[\s_-]*(?:PPV[\s_-]*)?{re.escape(parts[2])}"
    else:
        code = r"[\s_-]*".join(map(re.escape, parts))
    return re.compile(rf"(?<![A-Z0-9]){code}(?![A-Z0-9])", re.IGNORECASE)


def _parse_feed(content: bytes, avid: str) -> list[Torrent]:
    code = _match_code(avid)
    torrents = {}
    for item in ET.fromstring(content).findall("./channel/item"):
        title = item.findtext("title", "")
        try:
            link = urlsplit(item.findtext("link", ""))
        except ValueError:
            continue
        path = re.fullmatch(r"/download/([0-9]+)\.torrent", link.path)
        if not code.search(title) or (link.scheme, link.netloc) != ("https", "sukebei.nyaa.si") or not path:
            continue
        seeders = item.findtext(_NYAA + "seeders", "0").strip()
        torrent_id = path[1]
        torrents[torrent_id] = Torrent(
            torrent_id, title, item.findtext(_NYAA + "size", ""),
            int(seeders) if re.fullmatch(r"[0-9]{1,9}", seeders) else 0,
        )
    return sorted(torrents.values(), key=lambda torrent: torrent.seeders, reverse=True)


def _search(avid: str) -> list[Torrent]:
    queries = [avid]
    if match := re.fullmatch(r"FC2-PPV-([0-9]+)", avid):
        queries.append(match[1])
    for query in queries:
        response = requests.get(
            _BASE_URL, params={"page": "rss", "q": query, "c": "2_2"},
            timeout=15, impersonate="chrome110",
        )
        response.raise_for_status()
        torrents = _parse_feed(response.content, avid)
        if torrents:
            return torrents
    return []


def _menu_text(value: str) -> str:
    return "".join(" " if unicodedata.category(char).startswith("C") else char for char in value)


def _choose(torrents: list[Torrent], avid: str) -> Torrent | None:
    rows = [
        f"{index}\t{torrent.seeders:>5}  {_menu_text(torrent.size):>10}  {_menu_text(torrent.title)}"
        for index, torrent in enumerate(torrents)
    ]
    env = os.environ.copy()
    env.pop("FZF_DEFAULT_OPTS", None)
    env.pop("FZF_DEFAULT_OPTS_FILE", None)
    selection = subprocess.run(
        ["fzf", "--no-multi", "--no-sort", "--delimiter=\t", "--with-nth=2..",
         f"--prompt={avid}> ", "--header=Seeders   Size        Title | Enter 下載，Esc 取消"],
        input="\n".join(rows) + "\n", stdout=subprocess.PIPE, text=True, env=env,
    )
    if selection.returncode != 0:
        return None
    index = selection.stdout.partition("\t")[0]
    return torrents[int(index)] if index.isascii() and index.isdecimal() and int(index) < len(torrents) else None


def _download(torrent: Torrent, output: Path) -> bool:
    url = f"{_BASE_URL}download/{torrent.torrent_id}.torrent"
    response = requests.get(url, timeout=15, impersonate="chrome110")
    response.raise_for_status()
    if not response.content.startswith(b"d"):
        raise ValueError("Sukebei 未回傳有效的 .torrent 檔")
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="nassav-torrent-") as directory:
        torrent_file = Path(directory) / "selected.torrent"
        torrent_file.write_bytes(response.content)
        result = subprocess.run(
            ["aria2c", "--no-conf", f"--dir={output}", "--seed-time=0",
             "--check-integrity=true", "--allow-overwrite=false", "--auto-file-renaming=false",
             "--bt-stop-timeout=180", f"--torrent-file={torrent_file}"],
        )
    if result.returncode:
        logger.error(f"Sukebei BitTorrent 下載失敗 (aria2 exit {result.returncode})")
        return False
    logger.info(f"Sukebei 種子下載完成，檔案位於 {output}")
    return True


def download_from_sukebei(avid: str, video_folder: Path) -> bool:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        logger.info("Sukebei 種子選單需要互動終端（Docker: -it）")
        return False
    if not re.fullmatch(r"[A-Z0-9]+(?:-[A-Z0-9]+)*", avid):
        return False
    try:
        torrents = _search(avid)
        if not torrents:
            logger.info(f"Sukebei 找不到符合 {avid} 的種子")
            return False
        torrent = _choose(torrents, avid)
        if torrent is None:
            logger.info("Sukebei 未選擇種子")
            return False
        return _download(torrent, video_folder / "torrent" / torrent.torrent_id)
    except (OSError, ValueError, ET.ParseError, requests.exceptions.RequestException) as exc:
        logger.error(f"Sukebei 下載流程失敗: {exc}")
        return False
