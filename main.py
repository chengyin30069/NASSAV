from src import downloaderMgr
from src.comm import *
from src import data
import sys
import argparse
from pathlib import Path
from metadata import *

def append_if_not_duplicate(filename, new_content):
    new_content = new_content.strip()
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            existing_lines = [line.strip() for line in file.readlines()]
    except FileNotFoundError:
        existing_lines = []
    
    if new_content not in existing_lines:
        with open(filename, 'a', encoding='utf-8') as file:
            file.write(new_content + '\n')
        return True
    else:
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process some parameters.")
    
    parser.add_argument('-f', '--force', action='store_true', help='跳过DB检查，强制执行')
    parser.add_argument('-t', '--target', type=str, help='指定车牌号')
    parser.add_argument('--no-fan-art', action='store_true', help='跳过 gen_nfo 后处理（NFO、fan art 等）')
    parser.add_argument('--rebuild-fanart', action='store_true', help='修復缺少 fanart 的影片目錄；搭配番號可指定重建單一目錄')
    parser.add_argument('avid', nargs='?', help='車牌號')
    
    args = parser.parse_args()
    target = args.target or args.avid
    if args.rebuild_fanart:
        failures = rebuild_fanart(target.upper() if target else None)
        sys.exit(1 if failures else 0)
    if target is None:
        parser.error("需要提供車牌號，或使用 --rebuild-fanart")
    
    logger.info(f"Force: {args.force}")
    logger.info(f"Target: {target}")

    data.initialize_db(downloaded_path, "MissAV")
    if len(sys.argv) < 2:
        print("用法: python main.py <车牌号>")
        sys.exit(1)

    avid = target.upper()

    video_folder = Path(save_path) / avid
    existing_video = next((video_folder / f"{avid}{suffix}" for suffix in VIDEO_SUFFIXES
                           if (video_folder / f"{avid}{suffix}").is_file()), None)
    if existing_video:
        logger.info(f"{avid} 视频文件已存在: {existing_video}")
        sys.exit(0)

    if not args.force:
        if data.find_in_db(avid, downloaded_path, "MissAV"):
            logger.info(f"{avid} 已在小姐姐数据库中")
            exit(0)
            
    logger.info(f"开始执行 车牌号: {avid}")

    # 文件锁实现全局下载单例
    with open("work", "r") as f:
        content = f.read().strip()
    if content == "1":
        logger.info(f"A download task is running, save {avid} to download queue")
        with open(queue_path, 'a') as f: # 记录到queue中，等待下载
                f.write(f'{avid}\n')
        exit(0)

    with open("work", "w") as f:
        f.write("1")
    
    try:
        mgr = downloaderMgr.DownloaderMgr()
        attempted_missav_sources = set()
        for entry in sorted_downloaders:
            name = entry["downloaderName"]
            downloader = mgr.GetDownloader(name)
            if downloader is None or not downloader.setDomain(entry["domain"]):
                logger.warning(f"下載器 {name} 或其網域設定無效")
                continue

            logger.info(f"尝试使用Downloader: {name} 下载")
            info = downloader.downloadInfo(avid)
            if not info:
                logger.error(f"{avid} 下载元数据失败")
                continue

            source = getattr(info, "direct_url", "") or info.m3u8
            if name == "MissAV" and source:
                if source in attempted_missav_sources:
                    logger.warning(f"MissAV {entry['domain']} 指向本次已下載失敗的相同來源")
                    continue
                attempted_missav_sources.add(source)
            logger.info(info)
            if downloader.downloadM3u8(info.m3u8, avid):
                break
            logger.error(f"{source} 下载视频失败")
        else:
            from src.downloader.sukebei import download_from_sukebei

            if download_from_sukebei(avid, video_folder):
                sys.exit(0)
            raise ValueError(f"{avid} 所有來源未能完成下載")

        if not args.no_fan_art:
            gen_nfo(avid)

    except ValueError as e:
        logger.error(e)
        if append_if_not_duplicate(queue_path, avid):
            logger.info(f"'{avid}' 已成功添加到下载队列。")
        else:
            logger.info(f"'{avid}' 已存在下载队列中。")

    finally: # 一定要执行
        with open("work", "w") as f:
            f.write("0")
