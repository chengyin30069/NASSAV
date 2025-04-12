from src import downloaderMgr
from src.comm import *
from src import data
import sys
import metadata
import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process some parameters.")
    
    parser.add_argument('-f', '--force', action='store_true', help='跳过DB检查，强制执行')
    parser.add_argument('-p', '--plugin', type=str, help='指定下载插件，MissAV、Jable...')
    parser.add_argument('-t', '--target', type=str, help='指定车牌号')
    
    args, unknown = parser.parse_known_args()
    if not args and not unknown:
        logger.error(f"Error: Unknown arguments are not allowed: {args, unknown}")
        sys.exit(1)
    
    # 获取位置参数
    positional_args = [arg for arg in sys.argv[1:] if not arg.startswith('-')]
    
    if len(positional_args) == 1:
        args.target = positional_args[0]
    elif args.target is None:
        logger.error("需要提供车牌号")
        sys.exit(1)
    
    if not args.plugin:
        args.plugin = "MissAV"
    
    logger.info(f"Force: {args.force}")
    logger.info(f"Plugin: {args.plugin}")
    logger.info(f"Target: {args.target}")

    data.initialize_db(downloaded_path, "MissAV")
    if len(sys.argv) < 2:
        print("用法: python main.py <车牌号>")
        sys.exit(1)

    avid = args.target.upper()

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
        downloader = mgr.GetDownloader(args.plugin)
        if downloader is None:
            logger.error(f"下载器{args.plugin} 没有找到")
            raise ValueError(f"下载器{args.plugin} 没有找到")
        logger.info(f"尝试使用Downloader: {downloader.getDownloaderName()} 下载")

        # 视频源使用不同的Downloader
        metadata = downloader.downloadMetaData(avid)
        if not metadata:
            logger.error(f"{avid} 下载元数据失败")
            raise ValueError(f"{avid} 下载元数据失败")
        if not downloader.downloadM3u8(metadata.m3u8, avid):
            logger.error(f"{metadata.m3u8} 下载失败")
            raise ValueError(f"{metadata.m3u8} 下载失败")
        
        # 元数据还是使用MissAV
        if downloader.getDownloaderName() != "MissAV":
            downloader = mgr.GetDownloader("MissAV")
            metadata = downloader.downloadMetaData(avid)
        if not metadata:
            logger.error(f"{avid} 下载元数据失败")
            raise ValueError(f"{avid} 下载元数据失败")
        if not downloader.downloadIMG(metadata):
            logger.error(f"{metadata.m3u8} 图片下载失败")
            raise ValueError(f"{metadata.m3u8} 图片下载失败")
        if not downloader.genNFO(metadata):
            logger.error(f"{metadata.m3u8} nfo生成失败")
            raise ValueError(f"{metadata.m3u8} nfo生成失败")
        
    except ValueError as e:
        logger.error(e)
        # 添加到下载队列
        with open(queue_path, "a+") as f:
            f.write(f"{avid}\n")

    finally:
        with open("work", "w") as f:
            f.write("0")