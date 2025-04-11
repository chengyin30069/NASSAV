# 批量生成 metadata.json和nfo
from src import api
from src.comm import *
from src import data
import os
import time

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

def gen_nfo():
    folders = list_folders(save_path)
    data.batch_insert_bvids(folders, downloaded_path, "MissAV") # 多点脏数据也无所谓
    for folder in folders:
        if folder == "thumb":
            continue

        # 检查文件夹中是否有.nfo文件
        if has_nfo_file(os.path.join(save_path, folder)):
            print(f"已有nfo: {folder}")
            continue

        print(folder)
        scraper = api.MissAVMetaDataScraper(proxy=myproxy)
        print(f"url=https://{domain}/cn/{folder}")
        missav = scraper.scrape(f'https://{domain}/cn/{folder}'.lower())
        logger.info(missav)

        # 保存元数据
        print("保存元数据")
        meta_path = os.path.join(save_path, missav.identity ,'metadata.json')
        print(f"元数据保存到: {meta_path}")
        missav.to_json(meta_path)

        # 保存图片
        print("保存图片")
        path = os.path.join(save_path, missav.identity)
        downloader = api.AssertDownloader(path)
        downloader.ImgDownloader(missav.cover, prefix=f"{folder}-")

        # 保存小姐姐头像
        print("保存头像")
        avatar_path = os.path.join(save_path, "thumb")
        downloader = api.AssertDownloader(avatar_path)
        os.makedirs(path, exist_ok=True)
        for av in missav.actress:
            print(av)
            if os.path.exists(os.path.join(avatar_path, av)):
                continue
            downloader._download_file(missav.actress[av], av+".jpg")

        # 保存nfo
        print("保存nfo")
        nfoGenerator = api.NfoGenerator(os.path.join(save_path, missav.identity))
        nfoGenerator.GenXML()

        time.sleep(5)

if __name__ == "__main__":
    data.initialize_db(downloaded_path, "MissAV")
    gen_nfo()