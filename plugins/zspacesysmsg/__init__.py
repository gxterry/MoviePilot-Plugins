from datetime import datetime, timedelta
from typing import Optional, Any, List, Dict, Tuple

import pytz
import re
import random
import time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.event import eventmanager, Event
from app.db.transferhistory_oper import TransferHistoryOper
from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils


class ZspaceSysMsg(_PluginBase):
    # 插件名称
    plugin_name = "极空间系统通知"
    # 插件描述
    plugin_desc = "获取极空间系统消息,推送到MP的消息渠道"
    # 插件图标
    plugin_icon = "Zspace_A.png"
    # 插件版本
    plugin_version = "0.1"
    # 插件作者
    plugin_author = "gxterry"
    # 作者主页
    author_url = "https://github.com/gxterry"
    # 插件配置项ID前缀
    plugin_config_prefix = "zspacesysmsg_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _onlyonce = False
    _cron = None
    _zspcookie=None
    _zsphost=None
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")      
            self._zspcookie=config.get("zspcookie")
            self._zsphost=config.get("zsphost")        
            if self._zsphost:           
                if not self._zsphost.startswith("http"):
                    self._zsphost = "http://" + self._zsphost
                if  self._zsphost.endswith("/"):
                    self._zsphost = self._zsphost[:-1]
            # 加载模块
            if self._enabled or self._onlyonce:
                # 定时服务
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                # 立即运行一次
                if self._onlyonce:
                    logger.info(f"极空间系统通知服务启动，立即运行一次")
                    self._scheduler.add_job(self.pushmsg, 'date',
                                            run_date=datetime.now(
                                                tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                            name="极空间系统通知")
                    # 关闭一次性开关
                    self._onlyonce = False
                    # 保存配置
                    self.__update_config()
                # 周期运行
                if self._cron:
                    try:
                        self._scheduler.add_job(func=self.pushmsg,
                                                trigger=CronTrigger.from_crontab(self._cron),
                                                name="极空间系统通知")
                    except Exception as err:
                        logger.error(f"定时任务配置错误：{str(err)}")
                        # 推送实时消息
                        self.systemmessage.put(f"执行周期配置错误：{err}")
                # 启动任务
                if self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()

  
    def __update_config(self):
        self.update_config(
            {
                "onlyonce": self._onlyonce,
                "cron": self._cron,
                "enabled": self._enabled,    
                "zspcookie": self._zspcookie,
                "zsphost": self._zsphost            
            }
        )

    def pushmsg(self):
        """
        极空间系统通知推送
        """
        if not self._zsphost or not self._zspcookie:
            return False
        cookie = RequestUtils.cookie_parse(self._zspcookie)
        token = cookie['token']
        #device_id = cookie['device_id']  
        # 只获取notify类型消息 
        formdata = {"type":  "notify","start_id":0,"num":"20","token":token}
        # 获取消息列表
        list_url = "%s/action/list?&rnd=%s&webagent=v2" % (self._zsphost, self.generate_string() )
        try:
            rsp_body=RequestUtils(cookies=self._zspcookie).post_res(list_url,formdata)
            res = rsp_body.json()
            logger.debug(f"获取极空间系统消息 ：{res}")
            if res and res["code"] == "200":
                if res["data"]["list"] and isinstance(res["data"]["list"], list):     
                    for message in res["data"]["list"]:     
                        self.post_message(
                            mtype=NotificationType.Plugin,
                            title="【极空间系统消息】",
                            text= f"内容:{message['content']} \n 时间:{message['created_at']}")                        
            else:
                logger.info(f"获取极空间系统消息{res}")
        except Exception as e:
            logger.error(f"极空间系统消息推送" + str(e))
            return False
        return False

    @staticmethod
    def generate_string():
        timestamp = str(time.time())  # 获取当前的时间戳
        four_digit_random = str(random.randint(1000,9999))  # 生成四位的随机数
        return f"{timestamp}_{four_digit_random}"  # 返回格式化后的字符串

    def get_state(self) -> bool:
        return self._enabled

    @eventmanager.register(EventType.PluginAction)
    def remote_sync(self, event: Event):
        pass


    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '5位cron表达式，留空不运行'
                                        }
                                    }
                                ]
                            }
                            ,{
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'zsphost',
                                            'label': '极空间webip+端口',
                                            'placeholder': 'http://127.0.0.1:5055'
                                        }
                                    }               
                                ]
                            },
                        ],
                    },{
                        "component": "VRow",
                        "content": [  
                            {
                                        'component': 'VCol',
                                        'props': {
                                            'cols': 12\
                                        },
                                        'content': [
                                            {
                                                'component': 'VTextField',
                                                'props': {
                                                    'model': 'zspcookie',
                                                    'label': 'cookie',
                                                    'rows': 5
                                                }
                                            }
                                        ]
                                    }
                        ],
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '- cookie：极空间web端cookie',
                                            'style': 'white-space: pre-line;'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ],
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "cron": "5 1 * * *",
            "timescope": 1,
            "waittime":60,
            "unit":"day"
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))