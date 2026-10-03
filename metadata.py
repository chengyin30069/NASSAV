# 批量生成 metadata.json和nfo
from src.comm import *
from src import data
import os
import time
from src.scraper import ArtworkScraper
from pathlib import Path

VIDEO_SUFFIXES = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".ts"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def _has_video(folder: Path) -> bool:
    return any(item.is_file() and item.suffix.lower() in VIDEO_SUFFIXES for item in folder.iterdir())


def _has_fanart(folder: Path) -> bool:
    prefix = folder.name.lower() + "-fanart"
    return any(
        item.is_file() and item.name.lower().startswith(prefix) and item.suffix.lower() in IMAGE_SUFFIXES
        for item in folder.iterdir()
    )


def rebuild_fanart(target: str | None = None) -> list[str]:
    """Repair artwork in video directories without fanart; a target forces one directory."""
    root = Path(save_path)
    if not root.is_dir():
        logger.error(f"影片目錄不存在: {root}")
        return [target or str(root)]
    if target:
        if Path(target).name != target or target in {".", ".."}:
            logger.error(f"無效的番號: {target}")
            return [target]
        folders = [root / target]
    else:
        folders = sorted(folder for folder in root.iterdir() if folder.is_dir() and folder.name != "thumb")

    failed = []
    selected = 0
    succeeded = 0
    for folder in folders:
        if not folder.is_dir() or not _has_video(folder):
            if target:
                logger.error(f"找不到含影片檔的目錄: {folder}")
                failed.append(folder.name)
            continue
        if not target and _has_fanart(folder):
            continue
        selected += 1
        logger.info(f"重建 fanart: {folder.name}")
        try:
            result = ArtworkScraper(str(root), myproxy).scrape(folder.name, preserve_existing_nfo=True)
        except Exception as exc:
            logger.error(f"{folder.name} 重建 fanart 時發生錯誤: {exc}")
            result = None
        if result is None or not _has_fanart(folder):
            failed.append(folder.name)
            logger.error(f"{folder.name} 重建 fanart 失敗")
        else:
            succeeded += 1

    logger.info(f"fanart 修復完成：待修 {selected}，成功 {succeeded}，失敗 {len(failed)}")
    return failed

def list_folders(path):
    """返回指定路径下的所有文件夹名称"""
    folders = []
    for item in os.listdir(path):
        item_path = os.path.join(path, item)
        if os.path.isdir(item_path):
            folders.append(item)
    return folders

def has_nfo_file(folder_path):
    """检查包括隐藏文件在内的所有.nfo文件"""
    for root, _, files in os.walk(folder_path):
        for file in files:
            if file.lower().endswith('.nfo'):
                return True
    return False

def gen_nfo(target=None):
    folders = [target] if target else list_folders(save_path)
    data.batch_insert_bvids(folders, downloaded_path, "MissAV") # 多点脏数据也无所谓
    for index, folder in enumerate(folders):
        if folder == "thumb":
            continue

        # 检查文件夹中是否有.nfo文件
        if has_nfo_file(os.path.join(save_path, folder)):
            print(f"已有nfo: {folder}")
            continue
        # if os.path.exists(f"{folder}.html"):
        #     print(f"已刮削: {folder}")
        #     continue

        print(folder)
        scraper = ArtworkScraper(save_path, myproxy)
        scraper.scrape(folder)

        if index + 1 < len(folders):
            time.sleep(5)

if __name__ == "__main__":
    data.initialize_db(downloaded_path, "MissAV")
    gen_nfo()
