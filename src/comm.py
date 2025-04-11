import json
from loguru import logger
import os
from dataclasses import dataclass, asdict, field
from typing import Dict, Any
from pathlib import Path

# 获取项目目录
current_file_path = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(current_file_path))

# 获取配置
configs = []
with open(project_root+'/cfg/configs.json', 'r', encoding='utf-8') as file:
    configs = json.load(file)

# 初始化日志
logger.add(
    configs["LogPath"]+"/{time:YYYY-MM-DD}.log",
    rotation="00:00",            
    retention="7 days", 
    enqueue=False,
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
)

save_path = configs["SavePath"]
downloaded_path = configs["DBPath"]
queue_path = configs["QueuePath"]
myproxy = configs["proxy"]
if myproxy == "":
    myproxy = None
domain = configs["MissAVDomain"]

logger.info(f"load config succ: \nsave_path: {save_path}\ndownloaded_path: {downloaded_path}\n\
queue_path: {queue_path}\nproxy: {myproxy}\ndomain: {domain}")

# 数据结构定义
@dataclass
class MissAVInfo:
    m3u8: str = ""
    title: str = ""
    origional_title = ""
    cover: str = ""
    identity: str = ""
    actress: dict = field(default_factory=dict)  # 默认空字典
    description: str = ""
    duration: str = ""
    release_date: str = ""

    def __str__(self):
        return (
            f"=== 元数据详情 ===\n"
            f"番号: {self.identity or '未知'}\n"
            f"标题: {self.title or '未知'}\n"
            f"演员: {self.actress or '未知'}\n"
            f"描述: {self.description or '无'}\n"
            f"封面: {self.cover or '无'}\n"
            f"M3U8: {self.m3u8 or '无'}"
        )
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, file_path: str, indent: int = 2) -> bool:
        try:
            path = Path(file_path) if isinstance(file_path, str) else file_path
            path.parent.mkdir(parents=True, exist_ok=True)
            
            with path.open('w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=indent)
            return True
        except (IOError, TypeError) as e:
            logger.error(f"JSON序列化失败: {str(e)}")
            return False