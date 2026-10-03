"""Artwork scraper: R18/FANZA for catalogue titles, FC2 for FC2-PPV titles."""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from io import BytesIO
import json
import os
from pathlib import Path
import re
from urllib.parse import quote, urljoin, urlparse
from xml.etree import ElementTree as ET

from curl_cffi import requests
from loguru import logger
from PIL import Image, ImageOps, UnidentifiedImageError

from .comm import configs


FC2_ID = re.compile(r"FC2(?:[-_ ]?PPV)?[-_ ]?(\d+)", re.IGNORECASE)


def fc2_number(avid: str) -> str | None:
    match = FC2_ID.fullmatch(avid.strip())
    return match.group(1) if match else None


@dataclass
class AVMetadata:
    avid: str
    title: str = ""
    cover: str = ""
    description: str = ""
    duration: str = ""
    release_date: str = ""
    keywords: list[str] = field(default_factory=list)
    actress: dict[str, str] = field(default_factory=dict)
    fanarts: list[str] = field(default_factory=list)
    source: str = ""

    def to_json(self, file_path: str, indent: int = 2) -> bool:
        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=indent), encoding="utf-8")
            return True
        except (OSError, TypeError) as exc:
            logger.error(f"儲存 metadata 失敗: {exc}")
            return False


class _FC2Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.samples: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "meta":
            key = values.get("property") or values.get("name")
            if key and values.get("content"):
                self.meta[key] = values["content"]
        elif tag == "a" and "data-pdp-sample-thumbnail" in values and values.get("href"):
            self.samples.append(values["href"])


class ArtworkScraper:
    def __init__(self, path: str, proxy: str | None = None, timeout: int = 15):
        self.path = Path(path)
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.timeout = timeout
        settings = configs.get("Fanart", {})
        self.impersonate = settings.get("Impersonate", "chrome120")
        self.max_preview_images = max(0, min(int(settings.get("MaxPreviewImages", 20)), 50))

    def _get(self, url: str):
        response = requests.get(
            url, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "*/*",
            },
            proxies=self.proxies, timeout=self.timeout,
            impersonate=self.impersonate, allow_redirects=True,
        )
        response.raise_for_status()
        return response

    def _regular_metadata(self, avid: str) -> AVMetadata | None:
        url = f"https://r18.dev/videos/vod/movies/detail/-/dvd_id={quote(avid, safe='')}/json"
        try:
            payload = self._get(url).json()
            content_id = payload.get("content_id", "")
            if not re.fullmatch(r"[a-zA-Z0-9_]+", content_id):
                raise ValueError("R18 未提供有效商品 ID")
            jacket = payload.get("images", {}).get("jacket_image", {})
            cover = jacket.get("large2", "").strip() or jacket.get("large", "").strip()
            image_base = f"https://pics.dmm.co.jp/digital/video/{content_id}/"
            samples = [f"{image_base}{content_id}jp-{i}.jpg" for i in range(1, self.max_preview_images + 1)]
            return AVMetadata(
                avid=avid, title=payload.get("title") or avid,
                cover=cover, release_date=payload.get("release_date") or "",
                duration=str(payload.get("runtime_minutes") or ""),
                fanarts=samples, source="R18/FANZA",
            )
        except (requests.exceptions.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
            logger.warning(f"R18/FANZA 資料取得失敗: {avid}: {exc}")
            return None

    def _fc2_metadata(self, avid: str, number: str) -> AVMetadata | None:
        url = f"https://adult.contents.fc2.com/article/{number}/"
        try:
            page = _FC2Page()
            page.feed(self._get(url).text)
            title = page.meta.get("og:title", "")
            if title.startswith(f"FC2-PPV-{number}") and page.meta.get("og:image"):
                return AVMetadata(
                    avid=avid, title=title, cover=urljoin(url, page.meta["og:image"]),
                    description=page.meta.get("og:description", ""),
                    fanarts=list(dict.fromkeys(urljoin(url, image) for image in page.samples))[:self.max_preview_images],
                    source="FC2 Content Market",
                )
            logger.warning(f"FC2 官方商品頁沒有作品圖片: {avid}")
        except requests.exceptions.RequestException as exc:
            logger.warning(f"FC2 官方商品頁讀取失敗: {avid}: {exc}")

        # Removed products may retain a cover in the independent catalogue.
        fallback_url = f"https://fc2cmadb.com/articles/{number}"
        try:
            response = self._get(fallback_url)
            match = re.search(r'<script\s+data-page="app"\s+type="application/json">(.*?)</script>', response.text, re.S)
            if not match:
                raise ValueError("找不到 FC2CMADB 商品資料")
            article = json.loads(match.group(1)).get("props", {}).get("article", {})
            if str(article.get("video_id")) != number or not article.get("image_url"):
                raise ValueError("FC2CMADB 商品 ID 或封面無效")
            return AVMetadata(
                avid=avid, title=article.get("title") or avid,
                cover=article["image_url"], release_date=article.get("release_date") or "",
                duration=article.get("duration") or "", source="FC2CMADB",
            )
        except (requests.exceptions.RequestException, ValueError, TypeError) as exc:
            logger.warning(f"FC2CMADB 備援資料取得失敗: {avid}: {exc}")
            return None

    def _download_image(self, url: str, target: Path) -> Image.Image | None:
        if urlparse(url).scheme != "https":
            logger.warning(f"略過非 HTTPS 圖片: {url}")
            return None
        try:
            response = self._get(url)
            if not response.headers.get("Content-Type", "").lower().startswith("image/"):
                raise ValueError("回應不是圖片")
            with Image.open(BytesIO(response.content)) as original:
                image = ImageOps.exif_transpose(original).convert("RGB")
            if image.width < 200 or image.height < 200:
                raise ValueError(f"圖片尺寸過小 ({image.width}x{image.height})")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".tmp")
            try:
                image.save(temporary, format="JPEG", quality=90)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            return image
        except (requests.exceptions.RequestException, OSError, ValueError, UnidentifiedImageError) as exc:
            logger.warning(f"圖片下載失敗: {url}: {exc}")
            return None

    def _write_artwork(self, metadata: AVMetadata) -> list[str]:
        folder = self.path / metadata.avid
        folder.mkdir(parents=True, exist_ok=True)
        prefix = metadata.avid + "-"
        downloaded: list[str] = []
        cover = self._download_image(metadata.cover, folder / f"{prefix}fanart-1.jpg") if metadata.cover else None
        def save_poster(image: Image.Image) -> None:
            width, height = image.size
            if width / height > 565 / 800:
                target_width = int(height * 565 / 800)
                image = image.crop((width - target_width, 0, width, height))
            image.save(folder / f"{prefix}poster.jpg", format="JPEG", quality=90)

        if cover:
            save_poster(cover)
            downloaded.append(f"{prefix}fanart-1.jpg")

        for image_url in metadata.fanarts:
            name = f"{prefix}fanart-{len(downloaded) + 1}.jpg"
            image = self._download_image(image_url, folder / name)
            if image:
                if not downloaded:
                    save_poster(image)
                downloaded.append(name)
            elif metadata.source == "R18/FANZA":
                # FANZA returns a 90x122 placeholder beyond the end of a gallery.
                break
        return downloaded

    def _write_nfo(self, metadata: AVMetadata, artwork: list[str], preserve_existing: bool = False) -> None:
        path = self.path / metadata.avid / f"{metadata.avid}.nfo"
        root = None
        if preserve_existing and path.is_file():
            try:
                root = ET.parse(path).getroot()
                if root.tag != "movie":
                    raise ValueError("NFO 根節點不是 movie")
            except (ET.ParseError, ValueError) as exc:
                logger.warning(f"既有 NFO 無法解析，將重建: {path}: {exc}")
                root = None
        if root is None:
            root = ET.Element("movie")
            ET.SubElement(root, "title").text = metadata.title
            ET.SubElement(root, "plot").text = metadata.description
            ET.SubElement(root, "outline").text = metadata.description[:100]
            if metadata.release_date:
                try:
                    release_date = datetime.strptime(metadata.release_date, "%Y-%m-%d").strftime("%Y-%m-%d")
                except ValueError:
                    release_date = ""
                if release_date:
                    ET.SubElement(root, "premiered").text = release_date
                    ET.SubElement(root, "releasedate").text = release_date
            if metadata.duration:
                ET.SubElement(root, "runtime").text = metadata.duration
            for keyword in metadata.keywords[:5]:
                ET.SubElement(root, "genre").text = keyword
        if artwork:
            art = root.find("art")
            if art is None:
                art = ET.SubElement(root, "art")
            else:
                for item in list(art):
                    if item.tag in {"poster", "fanart"}:
                        art.remove(item)
            if (self.path / metadata.avid / f"{metadata.avid}-poster.jpg").exists():
                ET.SubElement(art, "poster").text = f"{metadata.avid}-poster.jpg"
            for name in artwork:
                ET.SubElement(art, "fanart").text = name
        temporary = path.with_name(path.name + ".tmp")
        try:
            ET.ElementTree(root).write(temporary, encoding="utf-8", xml_declaration=True)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def scrape(self, avid: str, preserve_existing_nfo: bool = False) -> AVMetadata | None:
        avid = avid.strip().upper()
        number = fc2_number(avid)
        metadata = self._fc2_metadata(avid, number) if number else self._regular_metadata(avid)
        if not metadata:
            logger.error(f"找不到 {avid} 的圖片資料")
            return None
        logger.info(f"{avid} 使用圖片來源: {metadata.source}")
        artwork = self._write_artwork(metadata)
        if not artwork:
            logger.error(f"{avid} 沒有可下載的封面或預覽圖，保留重試機會")
            return None
        self._write_nfo(metadata, artwork, preserve_existing=preserve_existing_nfo)
        return metadata
