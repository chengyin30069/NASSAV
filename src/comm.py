import json
from loguru import logger
import os
from dataclasses import dataclass, asdict, field
from typing import Dict, Any

# 获取项目目录
current_file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(current_file_path))

# 获取配置
with open(project_root+'/cfg/configs.json', 'r', encoding='utf-8') as file:
    configs = json.load(file)
logger.info(configs)

# 初始化日志
logger.add(
    configs["LogPath"]+"/{time:YYYY-MM-DD}.log",
    rotation="00:00",            
    retention="7 days", 
    enqueue=False,
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
)

# 存储到变量中
save_path = configs["SavePath"]
downloaded_path = configs["DBPath"]
queue_path = configs["QueuePath"]
myproxy = configs["Proxy"]
isNeedVideoProxy = configs["IsNeedVideoProxy"]
if myproxy == "":
    myproxy = None
sorted_downloaders = sorted(
    [downloader for downloader in configs["Downloader"] if downloader["weight"] != 0],
    key=lambda x: x["weight"],
    reverse=True  # 降序排序
)
print(sorted_downloaders)
missAVDomain = ""
for downloader in sorted_downloaders:
    if downloader["downloaderName"] == "MissAV":
        missAVDomain = downloader["domain"]
        break
print(f"missav domain: {missAVDomain}")