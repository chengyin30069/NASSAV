from src import api
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
    elif len(positional_args) > 1:
        logger.error("位置参数只能传入一个车牌号")
        sys.exit(1)
    elif args.target is None:
        logger.error("需要提供车牌号")
        sys.exit(1)
    
    logger.info(f"Force: {args.force}")
    logger.info(f"Plugin: {args.plugin}")
    logger.info(f"Target: {args.target}")

    data.initialize_db(downloaded_path, "MissAV")
    if len(sys.argv) < 2:
        print("用法: python main.py <车牌号>")
        sys.exit(1)

    no = args.target.upper()

    if not args.force:
        if data.find_in_db(no, downloaded_path, "MissAV"):
            logger.info(f"{no} 已在小姐姐数据库中")
            exit(0)
            
    logger.info(f"开始执行 车牌号: {no}")

    # 文件锁实现全局下载单例
    with open("work", "r") as f:
        content = f.read().strip()
    if content == "1":
        logger.info(f"A download task is running, save {no} to download queue")
        with open(queue_path, 'a') as f: # 记录到queue中，等待下载
                f.write(f'{no}\n')
        exit(0)

    with open("work", "w") as f:
        f.write("1")
    
    try:
        scraper = api.MissAVMetaDataScraper(proxy=myproxy)
        # 优先获取无码版本，清晰度最高
        url = f'https://{domain}/cn/{no}-uncensored-leak'.lower()
        missav = scraper.scrape(url)
        if missav is None:
            # 其次尝试获取字幕版本
            url = f'https://{domain}/cn/{no}-chinese-subtitle'.lower()
            missav = scraper.scrape(url)
        if missav is None:
            # 最后尝试获取原版
            url = f'https://{domain}/cn/{no}'.lower()
            missav = scraper.scrape(url)
        if missav is None:
            logger.error("请检查网络代理！如果网络没有问题，那么是车牌号不在missav中")
            raise ValueError("网络连接有问题，请检查代理！")

        logger.info(missav)
        if missav.m3u8 == "":
            raise ValueError("没有找到视频下载链接，请切换节点再尝试。")

        # 保存元数据
        meta_path = os.path.join(save_path, missav.identity ,'metadata.json')
        logger.debug(f"元数据保存到: {meta_path}")
        missav.to_json(meta_path)

        # 开始下载
        path = os.path.join(save_path, missav.identity)
        video_path = os.path.join(path, f'{missav.identity}.mp4')
        downloader = api.AssertDownloader(path)
        if downloader.M3u8Downloader(missav.m3u8, missav.identity):
            logger.info(f"视频下载完成：{video_path}")
            if downloader.MetaDataInserter(video_path, missav):
                logger.info(f"元数据嵌入完成：{video_path}")
                # 保存db
                data.batch_insert_bvids([missav.identity], downloaded_path, "MissAV")
                logger.info(f"{missav.identity} 记录到小姐姐数据库")
            # 生成nfo
            metadata.gen_nfo()
        else:
            raise ValueError("视频下载失败，请检查代理！")

    except:
        logger.error(f"视频下载失败：{no}")
        with open(queue_path, 'a') as f:
            f.write(f'{no.upper()}\n')

    finally:
        with open("work", "w") as f:
            f.write("0")