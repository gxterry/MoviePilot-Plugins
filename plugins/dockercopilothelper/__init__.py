from datetime import datetime, timedelta

from typing import Optional, Any, List, Dict, Tuple
import time
import pytz
import jwt
import requests
from requests import Session, Response
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.event import eventmanager, Event

from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import EventType, NotificationType
from app.utils.http import RequestUtils


class DockerCopilotHelper(_PluginBase):
    # 插件名称
    plugin_name = "DC助手"
    # 插件描述
    plugin_desc = "配合DockerCopilot,完成更新通知、自动更改、自动备份功能"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/gxterry/MoviePilot-Plugins/main/icons/Docker_Copilot.png"
    # 插件版本
    plugin_version = "1.1"
    # 插件作者
    plugin_author = "gxterry"
    # 作者主页
    author_url = "https://github.com/gxterry"
    # 插件配置项ID前缀
    plugin_config_prefix = "dockercopilothelper_"
    # 加载顺序
    plugin_order = 15
    # 可使用的用户级别
    auth_level = 1

    # 私有属性
    _enabled = False
    _onlyonce = False
    # 可用更新
    _update_cron = None
    _updatable_list = []
    _updatable_notify = False
    _schedule_report = False
    # 自动更新
    _auto_update_cron = None
    _auto_update_list = []
    _auto_update_notify = False
    _delete_images = False
    _intervallimit = None
    _interval = None
    # 备份
    _backup_cron = None
    _backups_notify = False
    _host = None
    _secretKey = None
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        # 停止现有任务
        self.stop_service()
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._update_cron = config.get("updatecron")
            self._updatable_list = config.get("updatablelist")
            self._updatable_notify = config.get("updatablenotify")
            self._auto_update_cron = config.get("autoupdatecron")
            self._auto_update_list = config.get("autoupdatelist")
            self._auto_update_notify = config.get("autoupdatenotify")
            self._schedule_report = config.get("schedulereport")
            self._delete_images = config.get("deleteimages")
            self._backup_cron = config.get("backupcron")
            self._backups_notify = config.get("backupsnotify")
            self._intervallimit = config.get("intervallimit") or 6
            self._interval = config.get("interval") or 10

            self._host = config.get("host")
            self._secretKey = config.get("secretKey")

            # 获取DC列表数据
            if not self._secretKey or not self._host:
                logger.error(f"DC助手服务结束 secretKey或host未填写")
                return False

            # 加载模块
            if self._enabled or self._onlyonce:
                # 定时服务
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                # 立即运行一次
                if self._onlyonce:
                    logger.info(f"DC助手服务启动，立即运行一次")
                    if self._backup_cron:
                        self._scheduler.add_job(self.backup, 'date',
                                                run_date=datetime.now(
                                                    tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                                                name="DC助手-备份")
                    if self._update_cron:
                        self._scheduler.add_job(self.updatable, 'date',
                                                run_date=datetime.now(
                                                    tz=pytz.timezone(settings.TZ)) + timedelta(seconds=6),
                                                name="DC助手-自动更新")
                    if self._auto_update_cron:
                        self._scheduler.add_job(self.auto_update, 'date',
                                                run_date=datetime.now(
                                                    tz=pytz.timezone(settings.TZ)) + timedelta(seconds=10),
                                                name="DC助手-更新通知")
                    # 关闭一次性开关
                    self._onlyonce = False
                    # 保存配置
                    self.__update_config()
                # 周期运行
                if self._backup_cron:
                    try:
                        self._scheduler.add_job(func=self.backup,
                                                trigger=CronTrigger.from_crontab(self._backup_cron),
                                                name="DC助手-备份")
                    except Exception as err:
                        logger.error(f"定时任务配置错误：{str(err)}")
                        # 推送实时消息
                        self.systemmessage.put(f"执行周期配置错误：{err}")
                if self._update_cron:
                    try:
                        self._scheduler.add_job(func=self.updatable,
                                                trigger=CronTrigger.from_crontab(self._update_cron),
                                                name="DC助手-更新通知")
                    except Exception as err:
                        logger.error(f"定时任务配置错误：{str(err)}")
                        # 推送实时消息
                        self.systemmessage.put(f"执行周期配置错误：{err}")
                if self._auto_update_cron:
                    try:
                        self._scheduler.add_job(func=self.auto_update,
                                                trigger=CronTrigger.from_crontab(self._auto_update_cron),
                                                name="DC助手-自动更新")
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

    # def clear_checkbox(self):
    #         self.update_config(
    #             {
    #                 "autoupdatelist":[],
    #                 "updatablelist":[]
    #             }
    #     )

    def __update_config(self):
        self.update_config(
            {
                "onlyonce": self._onlyonce,
                "enabled": self._enabled,
                "updatecron": self._update_cron,
                "updatablelist": self._updatable_list,
                "updatablenotify": self._updatable_notify,
                "autoupdatecron": self._auto_update_cron,
                "autoupdatelist": self._auto_update_list,
                "autoupdatenotify": self._auto_update_notify,
                "schedulereport": self._schedule_report,
                "deleteimages": self._delete_images,
                "backupcron": self._backup_cron,
                "backupsnotify": self._backups_notify,
                "host": self._host,
                "secretKey": self._secretKey,
                "intervallimit": self._intervallimit,
                "interval": self._interval

            }
        )

    def auto_update(self):
        """
        自动更新
        """
        logger.info("DC助手-自动更新-准备执行")
        if self._auto_update_cron:
            # 获取用户选择的容器 循环更新
            jwt = self.get_jwt()
            containers = self.get_docker_list()
            # 清理无标签 and 不在使用种的镜像
            if self._delete_images:
                images_list = self.get_images_list()
                for images in images_list:
                    if not images["inUsed"] and images["tag"]:
                        self.remove_image(images["id"])
            # 自动更新
            for name in self._auto_update_list:
                for container in containers:
                    if container["name"] == name and container["haveUpdate"]:
                        if not container["usingImage"] or container["usingImage"].startswith("sha256:"):
                            self.post_message(
                                mtype=NotificationType.Plugin,
                                title="【DC助手-自动更新】",
                                text=f"监测到您有容器TAG不正确\n【{container['name']}】\n当前镜像:{container['usingImage']}\n状态:{container['status']} "
                                     f"{container['runningTime']}\n构建时间：{container['createTime']}\n"
                                     f"该镜像无法通过DC自动更新,请修改TAG")
                            continue
                        url = '%s/api/container/%s/update' % (self._host, container['id'])
                        usingImage = {container['usingImage']}
                        rescanres = (RequestUtils(headers={"Authorization": jwt})
                                     .post_res(url, {"containerName": name, "imageNameAndTag": usingImage}))
                        data = rescanres.json()
                        if data["code"] == 200 and data["msg"] == "success":
                            self.post_message(
                                mtype=NotificationType.Plugin,
                                title="【DC助手-自动更新】",
                                text=f"【{name}】\n容器更新任务创建成功")
                            if self._schedule_report:
                                iteration = 0
                                while iteration < int(self._intervallimit):
                                    url = '%s/api/progress/%s' % (self._host, data["data"]["taskID"])
                                    rescanres = (RequestUtils(headers={"Authorization": jwt})
                                                 .get_res(url))
                                    report_json = rescanres.json()
                                    if report_json["code"] == 200:
                                        self.post_message(
                                            mtype=NotificationType.Plugin,
                                            title="【DC助手-更新进度】",
                                            text=f"【{name}】\n进度：{report_json['msg']}"
                                        )
                                        if report_json["msg"] == "更新成功":
                                            break
                                    else:
                                        pass
                                    iteration += 1
                                    if iteration >= int(self._intervallimit):
                                        logger.info(f'DC助手-更新进度追踪--{name}-超时')
                                    time.sleep(int(self._interval))  # 暂停N秒后继续下一次请求

    def updatable(self):
        """
        更新通知
        """
        logger.info("DC助手-更新通知-准备执行")
        if self._update_cron:
            docker_list = self.get_docker_list()
            logger.debug(f"DC助手-更新通知-{self._updatable_list}")
            for docker in docker_list:
                if docker["haveUpdate"] and docker["name"] in self._updatable_list:
                    if docker["usingImage"] and not docker["usingImage"].startswith("sha256:"):
                        # 发送通知
                        self.post_message(
                            mtype=NotificationType.Plugin,
                            title="【DC助手-更新通知】",
                            text=f"您有容器可以更新啦！\n【{docker['name']}】\n当前镜像:{docker['usingImage']}\n状态:{docker['status']} {docker['runningTime']}\n构建时间：{docker['createTime']}")
                    else:
                        self.post_message(
                            mtype=NotificationType.Plugin,
                            title="【DC助手-更新通知】",
                            text=f"监测到您有容器TAG不正确\n【{docker['name']}】\n当前镜像:{docker['usingImage']}\n状态:{docker['status']} "
                                 f"{docker['runningTime']}\n构建时间：{docker['createTime']}\n"
                                 f"该镜像无法通过DC自动更新,请修改TAG")
    def backup(self):
        """
        备份
        """
        logger.info(f"DC-备份-准备执行")
        backup_url = '%s/api/container/backup' % (self._host)
        result = (RequestUtils(headers={"Authorization": self.get_jwt()})
                  .get_res(backup_url))
        data = result.json()
        if data["code"] == 200:
            if self._backups_notify:
                self.post_message(
                    mtype=NotificationType.Plugin,
                    title="【DC助手-备份成功】",
                    text=f"镜像备份成功！")
            logger.info(f"DC-备份完成")
        else:
            if self._backups_notify:
                self.post_message(
                    mtype=NotificationType.Plugin,
                    title="【DC助手-备份失败】",
                    text=f"镜像备份失败拉~！\n【失败原因】:{data['msg']}")
            logger.error(f"DC-备份失败 Error code: {data['code']}, message: {data['msg']}")

    @eventmanager.register(EventType.PluginAction)
    def remote_sync(self, event: Event):
        pass

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_jwt(self) -> str:
        # 减少接口请求直接使用jwt
        payload = {
            "exp": int(time.time()) + 28 * 24 * 60 * 60,
            "iat": int(time.time())
        }
        encoded_jwt = jwt.encode(payload, self._secretKey, algorithm="HS256")
        logger.debug(f"DC helper get jwt---》{encoded_jwt}")
        return "Bearer "+encoded_jwt

    # def get_auth(self) -> str:
    #     """
    #     获取授权
    #     """
    #     auth_url = "%s/api/auth" % (self._host)
    #     rescanres = (RequestUtils()
    #                  .post_res(auth_url, {"secretKey": self._secretKey}))
    #     data = rescanres.json()
    #     if data["code"] == 201:
    #         jwt = data["data"]["jwt"]
    #         return jwt
    #     else:
    #         logger.error(f"DC-获取凭证异常 Error code: {data['code']}, message: {data['msg']}")
    #         return ""

    def get_docker_list(self) -> List[Dict[str, Any]]:
        """
        容器列表
        """
        docker_url = "%s/api/containers" % (self._host)
        result = (RequestUtils(headers={"Authorization":self.get_jwt() })
                  .get_res(docker_url))
        data = result.json()
        if data["code"] == 0:
            return data["data"]
        else:
            logger.error(f"DC-获取容器列表异常 Error code: {data['code']}, message: {data['msg']}")
            return []

    def get_images_list(self) -> List[Dict[str, Any]]:
        """
        镜像列表
        """
        images_url = "%s/api/images" % (self._host)
        result = (RequestUtils(headers={"Authorization": self.get_jwt()})
                  .get_res(images_url))
        data = result.json()
        if data["code"] == 200:
            return data["data"]
        else:
            logger.error(f"DC-获取镜像列表异常 Error code: {data['code']}, message: {data['msg']}")
            return []

    def remove_image(self, sha) -> bool:
        """
        清理镜像
        """
        images_url = "%s/api/image/%s?force=false" % (self._host, sha)
        result = self.delete_res(images_url,{"Authorization": self.get_jwt()})
        logger.debug(f'result---{result}')
        data = result.json()
        if data["code"] == 200:
            logger.error(f"DC-清理镜像成功: {sha}")
            return True
        else:
            logger.error(f"DC-清理镜像异常 Error code: {data['code']}, message: {data['msg']}")
            return False

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据： 1、页面配置；2、数据结构
        """
        updatable_list = []
        auto_update_list = []
        if self._secretKey and self._host:
            data = self.get_docker_list()
            # 移除不存在的选项
            names = [item['name'] for item in data]
            if self._updatable_list:
                self._updatable_list = [item for item in self._updatable_list if item in names]
            if self._updatable_list:
                self._auto_update_list = [item for item in self._auto_update_list if item in names]
            if self._auto_update_list or self._updatable_list:
                self.__update_config()
            for item in data:
                updatable_list.append({"title": item["name"], "value": item["name"]})
                auto_update_list.append({"title": item["name"], "value": item["name"]})
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
                    }, {
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
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'host',
                                            'label': '服务器地址',
                                            'hint': 'dockerCopilot服务地址 http(s)://ip:端口'
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
                                            'model': 'secretKey',
                                            'label': 'secretKey',
                                            'hint': 'dockerCopilot秘钥 环境变量查看'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [{
                            'component': 'VCol',
                            'props': {
                                'cols': 12
                            },
                            'content': [{
                                'component': 'VTabs',
                                'props': {
                                    'model': '_tabs',
                                    'height': 40,
                                    'style': {
                                        'margin-top-': '20px',
                                        'margin-bottom-': '60px',
                                        'margin-right': '30px'
                                    }
                                },
                                'content': [{
                                    'component': 'VTab',
                                    'props': {'value': 'C1'},
                                    'text': '更新通知'
                                },
                                    {
                                        'component': 'VTab',
                                        'props': {'value': 'C2'},
                                        'text': '自动更新'
                                    },
                                    {
                                        'component': 'VTab',
                                        'props': {'value': 'C3'},
                                        'text': '自动备份'
                                    }
                                ]
                            },
                                {
                                    'component': 'VWindow',
                                    'props': {
                                        'model': '_tabs'
                                    },
                                    'content': [{
                                        'component': 'VWindowItem',
                                        'props': {
                                            'value': 'C1', 'style': {'margin-top': '30px'}
                                        },
                                        'content': [{
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
                                                            'component': 'VTextField',
                                                            'props': {
                                                                'model': 'updatecron',
                                                                'label': '更新通知周期',
                                                                'placeholder': '15 8-23/2 * * *'
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
                                                            'cols': 12
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'VSelect',
                                                                'props': {
                                                                    'chips': True,
                                                                    'multiple': True,
                                                                    'model': 'updatablelist',
                                                                    'label': '更新通知容器',
                                                                    'items': updatable_list,
                                                                    'hint': '选择容器在有更新时发送通知'
                                                                }
                                                            }
                                                        ]
                                                    }
                                                ],
                                            }, ]
                                    }]
                                },
                                {
                                    'component': 'VWindow',
                                    'props': {
                                        'model': '_tabs'
                                    },
                                    'content': [{
                                        'component': 'VWindowItem',
                                        'props': {'value': 'C2', 'style': {'margin-top': '30px'}},
                                        'content': [
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
                                                                'component': 'VTextField',
                                                                'props': {
                                                                    'model': 'autoupdatecron',
                                                                    'label': '自动更新周期',
                                                                    'placeholder': '15 2 * * *'
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
                                                                'component': 'VTextField',
                                                                'props': {
                                                                    'model': 'interval',
                                                                    'label': '跟踪间隔(秒)',
                                                                    'placeholder': '10',
                                                                    'hint': '开启进度汇报时,每多少秒检查一次进度状态，默认10秒'
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
                                                                'component': 'VTextField',
                                                                'props': {
                                                                    'model': 'intervallimit',
                                                                    'label': '检查次数',
                                                                    'placeholder': '6',
                                                                    'hint': '开启进度汇报，当达限制检查次数后放弃追踪,默认6次'
                                                                }
                                                            }
                                                        ]
                                                    }
                                                ]},
                                            {
                                                'component': 'VRow',
                                                'content': [
                                                    {
                                                        'component': 'VCol',
                                                        'props': {
                                                            'cols': 12,
                                                            'md': 4
                                                        },
                                                        'content': [
                                                            {
                                                                'component': 'VSwitch',
                                                                'props': {
                                                                    'model': 'autoupdatenotify',
                                                                    'label': '自动更新通知',
                                                                    'hint': '更新任务创建成功发送通知'
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
                                                                'component': 'VSwitch',
                                                                'props': {
                                                                    'model': 'schedulereport',
                                                                    'label': '进度汇报',
                                                                    'hint': '追踪更新任务进度并发送通知'
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
                                                                'component': 'VSwitch',
                                                                'props': {
                                                                    'model': 'deleteimages',
                                                                    'label': '清理镜像',
                                                                    'hint': '在下次执行时清理无tag且不在使用中的全部镜像'
                                                                }
                                                            }
                                                        ]
                                                    },
                                                ]},
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
                                                                'component': 'VSelect',
                                                                'props': {
                                                                    'chips': False,
                                                                    'multiple': True,
                                                                    'model': 'autoupdatelist',
                                                                    'label': '自动更新容器',
                                                                    'items': auto_update_list,
                                                                    'hint': '被选则的容器当有新版本时自动更新'
                                                                }
                                                            }
                                                        ]
                                                    }
                                                ],
                                            }, ]
                                    }]
                                }]
                        }]
                    },
                    {
                        'component': 'VWindow',
                        'props': {
                            'model': '_tabs'
                        },
                        'content': [{
                            'component': 'VWindowItem',
                            'props': {
                                'value': 'C3',
                                'style': {'margin-top': '30px'}
                            },
                            'content': [{
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
                                                    'model': 'backupcron',
                                                    'label': '自动备份',
                                                    'placeholder': '0 7 * * *'
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
                                                    'model': 'backupsnotify',
                                                    'label': '备份通知',
                                                    'hint': '备份成功发送通知'
                                                }
                                            }
                                        ]
                                    }
                                ]}]
                        }]
                    }],
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "updatablenotify": False,
            "autoupdatenotify": False,
            "schedulereport": False,
            "deleteimages": False,
            "backupsnotify": False,
            "interval": 10,
            "intervallimit": 6

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

    def delete_res(self, url: str,
                   headers:dict = None,
                   params: dict = None,
                   data: Any = None,
                   json: dict = None,
                   allow_redirects: bool = True,
                   raise_exception: bool = False
                   ) -> Optional[Response]:
        try:
            return requests.delete(url,
                                   params=params,
                                   data=data,
                                   json=json,
                                   verify=False,
                                   headers=headers,
                                   timeout=20,
                                   allow_redirects=allow_redirects,
                                   stream=False)
        except requests.exceptions.RequestException:
            if raise_exception:
                raise requests.exceptions.RequestException
            return None