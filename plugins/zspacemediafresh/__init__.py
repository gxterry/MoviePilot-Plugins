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
from app.schemas.types import EventType
from app.utils.http import RequestUtils


class ZspaceMediaFresh(_PluginBase):
    # 插件名称
    plugin_name = "刷新极影视"
    # 插件描述
    plugin_desc = "定时刷新极影视。"
    # 插件图标
    plugin_icon = "Zspace_A.png"
    # 插件版本
    plugin_version = "1.1"
    # 插件作者
    plugin_author = "gxterry"
    # 作者主页
    author_url = "https://github.com/gxterry"
    # 插件配置项ID前缀
    plugin_config_prefix = "zspacemediafresh_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _onlyonce = False
    _cron = None
    _days = None
    _waittime = None
    _zspcookie=None
    _zsphost=None
    _moivelib=None
    _tvlib=None
    _flushall = False
    _startswith = None
    _notify = False
    _EMBY_HOST = settings.EMBY_HOST
    _EMBY_APIKEY = settings.EMBY_API_KEY
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()

        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._cron = config.get("cron")
            self._days = config.get("days") or 5
            self._waittime = config.get("waittime") or 60
            self._zspcookie=config.get("zspcookie")
            self._zsphost=config.get("zsphost")
            self._moivelib = config.get("moivelib")
            self._tvlib=config.get("tvlib")
            self._flushall=config.get("flushall")
            self._startswith=config.get("startswith")
            self._notify = config.get("notify")

            if self._zsphost:           
                if not self._zsphost.startswith("http"):
                    self._zsphost = "http://" + self._zsphost
            # 加载模块
            if self._enabled or self._onlyonce:
                # 定时服务
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)

                # 立即运行一次
                if self._onlyonce:
                    logger.info(f"极影视刷新服务启动，立即运行一次")
                    self._scheduler.add_job(self.refresh, 'date',
                                            run_date=datetime.now(
                                                tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                            name="极影视刷新")
                    # 关闭一次性开关
                    self._onlyonce = False
                    # 保存配置
                    self.__update_config()
                # 周期运行
                if self._cron:
                    try:
                        self._scheduler.add_job(func=self.refresh,
                                                trigger=CronTrigger.from_crontab(self._cron),
                                                name="极影视刷新")
                    except Exception as err:
                        logger.error(f"定时任务配置错误：{str(err)}")
                        # 推送实时消息
                        self.systemmessage.put(f"执行周期配置错误：{err}")
                # 启动任务
                if self._scheduler.get_jobs():
                    self._scheduler.print_jobs()
                    self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    def __update_config(self):
        self.update_config(
            {
                "onlyonce": self._onlyonce,
                "cron": self._cron,
                "enabled": self._enabled,
                "days": self._days,
                "waittime": self._waittime,
                "zspcookie": self._zspcookie,
                "zsphost": self._zsphost,
                "moivelib": self._moivelib,
                "tvlib": self._tvlib,
                "flushall": self._flushall,
                "startswith":self._startswith,
                "notify": self._notify
            }
        )

    def refresh(self):
        """
        刷新极影视
        """
        if not self._flushall:
            # 参数验证
            if not self._startswith:
                logger.error(f"网盘媒体库路径未设置")
                return
            logger.info(f"网盘媒体库路径：{self._startswith}")
            #获取days内入库的媒体
            current_date = datetime.now()
            target_date = current_date - timedelta(days=int(self._days))
            transferhistorys = TransferHistoryOper().list_by_date(target_date.strftime('%Y-%m-%d'))
            if not transferhistorys:
                logger.error(f"{self._days} 天内没有媒体库入库记录-")
                return
            #匹配指定路径的入库数据
            filtered_transferhistorys = [th for th in transferhistorys if th.dest.startswith(self._startswith)]
            if  not filtered_transferhistorys :
                logger.error(f"{self._days} 天内没有网盘媒体库的记录")
                return
            # 提取顶级分类  电影或电视剧
            unique_types = set([th.type for th in filtered_transferhistorys])
            types_list =list(unique_types)
            if "电影" in types_list:
                moivelib_list = self._moivelib.split(",")
            else:
                moivelib_list = []
            if "电视剧" in types_list:
                tvlib_list = self._tvlib.split(",")
            else:
                tvlib_list = []
            classify_list = moivelib_list + tvlib_list
            logger.info(f"开始刷新极影视，最近{self._days}天内网盘入库媒体：{len(filtered_transferhistorys)}个,需刷新媒体库：{classify_list}")
        # 刷新极影视
        self.__refresh_zspmedia(classify_list)
        logger.info(f"刷新极影视完成")

    @eventmanager.register(EventType.PluginAction)
    def remote_sync(self, event: Event):
        """
        远程刷新媒体库
        """
        if event:
            event_data = event.event_data
            if not event_data or event_data.get("action") != "zsp_media_refresh":
                return
            self.post_message(channel=event.event_data.get("channel"),
                              title="开始刷新极影视 ...",
                              userid=event.event_data.get("user"))
        self.refresh()
        if event:
            self.post_message(channel=event.event_data.get("channel"),
                              title="刷新极影视完成！", userid=event.event_data.get("user"))

    def __refresh_zspmedia(self,classify_list):
        """
        刷新极影视
        """
        if not self._zsphost or not self._zspcookie:
            return False
        cookie = RequestUtils.cookie_parse(self._zspcookie)
        token = cookie['token']
        device_id = cookie['device_id']

        # 获取分类列表
        list_url = "%s/zvideo/classification/list?&rnd=%s&webagent=v2" % (self._zsphost, self.generate_string() )
        try:
            with RequestUtils(cookies=self._zspcookie).post_res(list_url) as rsp_body:
                    res = rsp_body.json()
                    logger.info(f"获取极影视分类 ：{res}")
                    if res and res["code"] == "200":
                        if res["data"] and isinstance(res["data"], list):
                            # 获取分类ID
                            name_id_dict = {item["name"]: item["id"] for item in res['data']}
                            # 是否全类型刷新
                            if self._flushall :
                                 classify_list = [item["name"] for item in res['data']]
                            for classify in classify_list:
                                if classify not in name_id_dict:
                                    logger.info(f"分类 {classify} 不存在于极影视分类列表中，跳过刷新")
                                    continue
                                # 提交刷新请求
                                rescan_url = "%s/zvideo/classification/rescan?&rnd=%s&webagent=v2" % (self._zsphost, self.generate_string())
                                formdata = {"classification_id": name_id_dict[classify],"device_id":device_id,"token":token,"device":"PC电脑","plat":"web"}
                                rescanres = RequestUtils(headers={"Content-Type": "application/x-www-form-urlencoded"},cookies=self._zspcookie).post_res(rescan_url,formdata)
                                rescanres_json = rescanres.json()
                                start_time = time.time()# 记录开始时间
                                if rescanres_json["code"] =="200" and rescanres_json["data"]["task_id"]:
                                    logger.info(f"分类：{classify}开始刷新，任务ID：{rescanres_json['data']['task_id']}")
                                    # 查询刷新结果
                                    result_url = "%s/zvideo/classification/rescan/result?&rnd=%s&webagent=v2" % (self._zsphost,self.generate_string())
                                    formdata["task_id"] = rescanres_json['data']['task_id']
                                    logger.info(f"返回数据-----》：{formdata}")
                                    while True:
                                        #轮询状态
                                        resultRep = RequestUtils(headers={"Content-Type": "application/x-www-form-urlencoded"},
                                                                cookies=self._zspcookie).post_res(result_url, formdata)
                                        result_json = resultRep.json()
                                        if result_json and result_json["code"] in ["200","N120024"] and result_json["data"]["task_status"] == 4:
                                            logger.info(f"分类：{classify} 刷新执行中,等待{self._waittime}秒，task_id：{rescanres_json['data']['task_id']}")
                                            time.sleep(int(self._waittime))  #任务状态进行中 等待
                                        else:
                                            logger.info(f"分类：{classify} 刷新任务执行结束,task_id：{rescanres_json['data']['task_id']}，task_status:{result_json['data']['task_status']}")
                                            end_time = time.time()  # 记录结束时间
                                            if self._notify:
                                                self.post_message(
                                                    mtype=NotificationType.Plugin,
                                                    title="【刷新极影视】",
                                                    text=f"分类：{classify} 刷新成功\n"
                                                         f"开始时间： {start_time}\n"
                                                         f"用时： {start_time- end_time} 秒")
                                            break
                                else:
                                    logger.info(f"极影视获取分类列表出错：{rescanres_json}")
                    else:
                        logger.info(f"极影视获取分类列表出错：{res}")
        except Exception as e:
            logger.error(f"极影视获取分类列表出错：" + str(e))
            return False
        return False

    @staticmethod
    def generate_string():
        timestamp = str(time.time())  # 获取当前的时间戳
        four_digit_random = str(random.randint(0,9999))  # 生成四位的随机数
        return f"{timestamp}_{four_digit_random}"  # 返回格式化后的字符串

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [{
            "cmd": "/zsp_media_refresh",
            "event": EventType.PluginAction,
            "desc": "极影视刷新",
            "category": "",
            "data": {
                "action": "zsp_media_refresh"
            }
        }]

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
                                    'md': 3
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
                                    'md': 3
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
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '开启通知',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'flushall',
                                            'label': '刷新全部分类',
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '5位cron表达式，留空自动'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'days',
                                            'label': '时间范围(天)'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'waittime',
                                            'label': '等待时间(秒)'
                                        }
                                    }
                                ]
                            }
                        ],
                    },{
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
                                            'model': 'startswith',
                                            'label': '网盘媒体库路径'
                                        }
                                    }
                                ]
                            },{
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
                            }
                        ],
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
                                            'model': 'moivelib',
                                            'label': '电影分类名',
                                            'placeholder': '多个逗号分割',
                                            'rows': 6
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'tvlib',
                                            'label': '电视剧分类名',
                                            'placeholder': '多个逗号分割',
                                            'rows': 6
                                        }
                                    }
                                ]
                            }
                        ],
                    }, 
                    {
                        "component": "VRow",
                        "content": [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
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
                                            'text': '刷新全部分类：启用后忽略电影、电视剧分类配置,刷新极影视全部分类'
                                                    '时间范围：查询指定N天内入库的资源类型'
                                                    '等待时间：查询指定N天内入库的资源类型'
                                                    '网盘媒体库路径：挂载到极影视网盘的根路径 例如：在极影视看到资源路径是  /cd2/115/电影/华语电影/杀破狼/杀破狼.mp4 此处填 /cd2即可'
                                                    '电影分类名：智能分类这里填 电影 | 有自定义的分类并且需要被刷新 这里填你的自定义分类名，多个逗号间隔'
                                                    '电视剧分类名：智能分类这里填 电视剧| 有自定义的分类并且需要被刷新 这里填你的自定义分类名，多个逗号间隔'
                                                    'cookie：极空间web端cookie,重新登录web段可能会使cookie失效，如失效请更新'
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
            "days": 5
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