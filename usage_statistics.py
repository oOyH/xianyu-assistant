#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版用户使用统计模块
支持自建统计服务、批量上报、容错机制、认证等功能
"""

import asyncio
import hashlib
import platform
import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path

import aiohttp
from loguru import logger


class EnhancedUsageStatistics:
    """增强版用户使用统计收集器"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        # 加载配置
        self.config = config or self._load_default_config()
        
        # 基础配置
        self.enabled = self.config.get('enabled', True)
        self.api_endpoint = self.config.get('endpoint', 'https://stats.ivy.dpdns.org/api/v1/stats')
        self.api_token = self.config.get('token', '8f89b531ef1d7f53f9cf43590f675b33')
        self.timeout = self.config.get('timeout', 10)
        self.retry_count = self.config.get('retry_count', 3)
        self.batch_size = self.config.get('batch_size', 10)
        self.batch_interval = self.config.get('batch_interval', 60)  # 60秒
        
        # 生成持久化的匿名用户ID和会话ID
        self.anonymous_id = self._get_or_create_anonymous_id()
        self.session_id = self._generate_session_id()
        
        # 批量上报相关
        self.pending_data = []
        self.last_batch_time = time.time()
        self.batch_task = None
        
        # 事件和功能追踪
        self.events = []
        self.features_used = set()
        self.session_start_time = time.time()
        
        # 批量上报任务将在首次使用时启动

    def _load_default_config(self) -> Dict[str, Any]:
        """加载默认配置"""
        # 尝试从环境变量加载
        import os
        
        config = {
            'enabled': os.getenv('STATS_ENABLED', 'true').lower() == 'true',
            'endpoint': os.getenv('STATS_ENDPOINT', 'https://stats.ivy.dpdns.org/api/v1/stats'),
            'token': os.getenv('STATS_TOKEN', '8f89b531ef1d7f53f9cf43590f675b33'),
            'timeout': int(os.getenv('STATS_TIMEOUT', '10')),
            'retry_count': int(os.getenv('STATS_RETRY_COUNT', '3')),
            'batch_size': int(os.getenv('STATS_BATCH_SIZE', '10')),
            'batch_interval': int(os.getenv('STATS_BATCH_INTERVAL', '60'))
        }
        
        # 尝试从配置文件加载
        config_file = Path('stats_client_config.json')
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    file_config = json.load(f)
                config.update(file_config)
                logger.debug(f"从配置文件加载统计配置: {config_file}")
            except Exception as e:
                logger.debug(f"加载统计配置文件失败: {e}")
        
        return config

    def _get_or_create_anonymous_id(self) -> str:
        """获取或创建持久化的匿名用户ID"""
        # 保存到数据库中，确保Docker重建时ID不变
        try:
            from db_manager import db_manager
            
            # 尝试从数据库获取ID
            existing_id = db_manager.get_system_setting('anonymous_user_id')
            if existing_id and len(existing_id) >= 16:
                return existing_id
                
        except Exception:
            pass

        # 生成新的匿名ID
        new_id = self._generate_anonymous_id()

        # 保存到数据库
        try:
            from db_manager import db_manager
            db_manager.set_system_setting('anonymous_user_id', new_id, '匿名用户统计ID')
            logger.debug(f"生成新的匿名用户ID: {new_id}")
        except Exception as e:
            logger.debug(f"保存匿名用户ID失败: {e}")

        return new_id

    def _generate_anonymous_id(self) -> str:
        """生成匿名用户ID"""
        try:
            # 使用机器特征生成唯一ID
            machine_info = f"{platform.node()}-{platform.machine()}-{platform.processor()}"
            hash_obj = hashlib.md5(machine_info.encode())
            return hash_obj.hexdigest()[:16]
        except Exception:
            # 如果获取机器信息失败，使用时间戳
            import time
            return hashlib.md5(str(time.time()).encode()).hexdigest()[:16]

    def _generate_session_id(self) -> str:
        """生成会话ID"""
        return str(uuid.uuid4())[:16]

    def _start_batch_task(self):
        """启动批量上报任务"""
        try:
            if self.batch_task is None or self.batch_task.done():
                self.batch_task = asyncio.create_task(self._batch_upload_loop())
        except RuntimeError:
            # 没有运行的事件循环，任务将在首次使用时启动
            pass

    async def _batch_upload_loop(self):
        """批量上报循环"""
        while self.enabled:
            try:
                await asyncio.sleep(self.batch_interval)
                
                if self.pending_data:
                    await self._flush_batch_data()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"批量上报循环异常: {e}")
                await asyncio.sleep(30)  # 异常时等待30秒

    def _prepare_statistics_data(self, include_events: bool = True) -> Dict[str, Any]:
        """准备统计数据"""
        # 获取系统信息
        system_info = self._get_system_info()
        
        data = {
            "anonymous_id": self.anonymous_id,
            "timestamp": datetime.now().isoformat(),
            "project": "xianyu-assistant",
            "version": "2025.9.9",
            "session_id": self.session_id,
            "info": system_info
        }
        
        # 添加事件数据
        if include_events and self.events:
            data["events"] = self.events.copy()
            self.events.clear()  # 清空已上报的事件
        
        # 添加功能使用数据
        if self.features_used:
            data["features"] = list(self.features_used)
            # 不清空功能列表，因为可能会重复使用
        
        return data

    def _get_system_info(self) -> Dict[str, Any]:
        """获取系统信息"""
        try:
            import sys

            info = {
                "os": platform.system(),
                "os_version": platform.version(),
                "arch": platform.machine(),
                "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                "hostname": platform.node()
            }

            # 检测Docker环境（可选）
            try:
                if Path('/.dockerenv').exists():
                    info["docker_version"] = "detected"

                    # 尝试获取Docker版本（如果docker模块可用）
                    try:
                        import docker
                        client = docker.from_env()
                        info["docker_version"] = client.version()["Version"]
                    except ImportError:
                        # docker模块不可用，保持"detected"
                        pass
                    except Exception:
                        # 其他Docker相关错误
                        pass
            except Exception:
                # 非Docker环境或其他错误
                pass

            return info

        except Exception as e:
            logger.debug(f"获取系统信息失败: {e}")
            return {
                "os": platform.system(),
                "os_version": platform.version(),
                "arch": platform.machine(),
                "python_version": "unknown",
                "hostname": platform.node()
            }

    async def _send_statistics(self, data: Dict[str, Any], is_batch: bool = False) -> bool:
        """发送统计数据到远程API"""
        if not self.enabled:
            return False

        endpoint = self.api_endpoint
        if is_batch:
            endpoint = endpoint.replace('/statistics', '/statistics/batch')
            data = {"data": data}  # 批量接口需要包装在data字段中

        for attempt in range(self.retry_count):
            try:
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    headers = {
                        'Content-Type': 'application/json',
                        'User-Agent': 'XianyuAutoReply/2.2.0'
                    }
                    
                    # 添加认证头
                    if self.api_token:
                        headers['Authorization'] = f'Bearer {self.api_token}'

                    async with session.post(
                        endpoint,
                        json=data,
                        headers=headers
                    ) as response:
                        if response.status in [200, 201]:
                            logger.debug(f"统计数据上报成功 ({'批量' if is_batch else '单个'})")
                            return True
                        else:
                            response_text = await response.text()
                            logger.debug(f"统计数据上报失败，状态码: {response.status}, 响应: {response_text}")

            except asyncio.TimeoutError:
                logger.debug(f"统计数据上报超时，第{attempt + 1}次尝试")
            except Exception as e:
                logger.debug(f"统计数据上报异常: {e}")

            if attempt < self.retry_count - 1:
                await asyncio.sleep(2 ** attempt)  # 指数退避

        return False

    async def report_usage(self) -> bool:
        """报告用户使用统计"""
        try:
            # 确保批量任务已启动
            if self.enabled and (self.batch_task is None or self.batch_task.done()):
                self._start_batch_task()

            data = self._prepare_statistics_data()

            # 如果启用批量上报，添加到待上报队列
            if self.batch_size > 1:
                self.pending_data.append(data)
                
                # 检查是否需要立即上报
                if (len(self.pending_data) >= self.batch_size or 
                    time.time() - self.last_batch_time >= self.batch_interval):
                    return await self._flush_batch_data()
                else:
                    return True  # 添加到队列成功
            else:
                # 立即上报
                return await self._send_statistics(data)
                
        except Exception as e:
            logger.debug(f"报告使用统计失败: {e}")
            return False

    async def _flush_batch_data(self) -> bool:
        """刷新批量数据"""
        if not self.pending_data:
            return True
        
        try:
            batch_data = self.pending_data.copy()
            self.pending_data.clear()
            self.last_batch_time = time.time()
            
            success = await self._send_statistics(batch_data, is_batch=True)
            
            if not success:
                # 如果上报失败，重新加入队列（但限制重试次数）
                for data in batch_data:
                    retry_count = data.get('_retry_count', 0)
                    if retry_count < 3:
                        data['_retry_count'] = retry_count + 1
                        self.pending_data.append(data)
            
            return success
            
        except Exception as e:
            logger.debug(f"批量上报失败: {e}")
            return False

    def track_event(self, event_type: str, event_data: Optional[Dict[str, Any]] = None):
        """追踪事件"""
        if not self.enabled:
            return
        
        event = {
            "type": event_type,
            "data": event_data or {},
            "timestamp": datetime.now().isoformat()
        }
        
        self.events.append(event)
        
        # 限制事件数量
        if len(self.events) > 100:
            self.events = self.events[-50:]  # 保留最近50个事件

    def track_feature_usage(self, feature_name: str):
        """追踪功能使用"""
        if not self.enabled:
            return
        
        self.features_used.add(feature_name)

    async def report_session_end(self):
        """报告会话结束"""
        if not self.enabled:
            return
        
        session_duration = time.time() - self.session_start_time
        
        self.track_event("session_end", {
            "duration_seconds": int(session_duration),
            "events_count": len(self.events),
            "features_count": len(self.features_used)
        })
        
        # 强制上报所有待处理数据
        await self._flush_batch_data()
        
        # 取消批量上报任务
        if self.batch_task and not self.batch_task.done():
            self.batch_task.cancel()

    def get_anonymous_id(self) -> str:
        """获取匿名用户ID"""
        return self.anonymous_id

    def get_session_id(self) -> str:
        """获取会话ID"""
        return self.session_id

    def get_stats_summary(self) -> Dict[str, Any]:
        """获取统计摘要"""
        return {
            "anonymous_id": self.anonymous_id,
            "session_id": self.session_id,
            "enabled": self.enabled,
            "pending_events": len(self.events),
            "pending_batch_data": len(self.pending_data),
            "features_used": list(self.features_used),
            "session_duration": time.time() - self.session_start_time,
            "config": {
                "endpoint": self.api_endpoint,
                "batch_size": self.batch_size,
                "batch_interval": self.batch_interval
            }
        }


# 全局统计实例（兼容原有代码）
usage_stats = EnhancedUsageStatistics()


async def report_user_count():
    """报告用户数量统计（兼容原有接口）"""
    try:
        logger.info("正在上报用户统计...")
        success = await usage_stats.report_usage()
        if success:
            logger.info("✅ 用户统计上报成功")
        else:
            logger.debug("用户统计上报失败")
    except Exception as e:
        logger.debug(f"用户统计异常: {e}")


def get_anonymous_id() -> str:
    """获取匿名用户ID（兼容原有接口）"""
    return usage_stats.get_anonymous_id()


def track_event(event_type: str, event_data: Optional[Dict[str, Any]] = None):
    """追踪事件"""
    usage_stats.track_event(event_type, event_data)


def track_feature_usage(feature_name: str):
    """追踪功能使用"""
    usage_stats.track_feature_usage(feature_name)


# 测试函数
async def test_enhanced_statistics():
    """测试增强版统计功能"""
    print(f"匿名ID: {get_anonymous_id()}")
    print(f"会话ID: {usage_stats.get_session_id()}")
    
    # 测试事件追踪
    track_event("test_event", {"test_data": "hello"})
    track_feature_usage("auto_reply")
    track_feature_usage("qq_integration")
    
    # 测试上报
    await report_user_count()
    
    # 显示统计摘要
    summary = usage_stats.get_stats_summary()
    print(f"统计摘要: {json.dumps(summary, indent=2, ensure_ascii=False)}")


if __name__ == "__main__":
    asyncio.run(test_enhanced_statistics())
