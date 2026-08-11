"""
通用系统配置管理器
管理通用分辨率适配系统的所有配置设置
"""

import json
import logging
import os
import shutil
import threading
from typing import Dict, Any, Optional, Union, Tuple
from pathlib import Path

from utils.app_paths import get_user_data_dir

logger = logging.getLogger(__name__)

class UniversalConfigManager:
    """通用系统配置管理器"""
    
    def __init__(self, config_file: Optional[str] = None):
        self._lock = threading.RLock()
        self._config_data: Dict[str, Any] = {}
        self._config_file = config_file or self._get_default_config_file()
        self._load_config()
    
    def _get_default_config_file(self) -> str:
        """获取默认配置文件路径"""
        user_config_file = Path(get_user_data_dir("LCA")) / "config" / "universal_system_config.json"
        legacy_config_file = Path(__file__).resolve().parent.parent / "config" / "universal_system_config.json"

        if not user_config_file.exists() and legacy_config_file.exists():
            try:
                user_config_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(legacy_config_file), str(user_config_file))
            except Exception as e:
                logger.warning(f"迁移通用配置到用户目录失败: {e}")

        return str(user_config_file)
    
    def _load_config(self):
        """加载配置文件"""
        try:
            if os.path.exists(self._config_file):
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    self._config_data = json.load(f)
                logger.info(f"配置文件加载成功: {self._config_file}")
            else:
                logger.info(f"配置文件不存在，创建默认配置: {self._config_file}")
                self._config_data = self._get_default_config()
                # 自动创建并保存默认配置文件
                self.save_config()
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            self._config_data = self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "universal_resolution_adapter": {
                "reference_resolution": {
                    "width": 0,
                    "height": 0,
                    "dpi": 96,
                    "scale_factor": 1.0
                },
                "cache_settings": {
                    "window_state_timeout": 1.0,
                    "enable_caching": True
                }
            },
            "universal_coordinate_system": {
                "default_coordinate_type": "REFERENCE",
                "validation_settings": {
                    "enable_boundary_check": True,
                    "enable_range_validation": True
                }
            },
            "universal_window_manager": {
                "adjustment_settings": {
                    "default_target_width": 0,
                    "default_target_height": 0
                }
            }
        }
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            key_path: 配置键路径，使用点号分隔，如 'universal_resolution_adapter.reference_resolution.width'
            default: 默认值
            
        Returns:
            配置值
        """
        with self._lock:
            try:
                keys = key_path.split('.')
                value = self._config_data
                
                for key in keys:
                    if isinstance(value, dict) and key in value:
                        value = value[key]
                    else:
                        return default
                
                return value
                
            except Exception as e:
                logger.error(f"获取配置值失败: {key_path}, {e}")
                return default
    
    def set(self, key_path: str, value: Any):
        """
        设置配置值
        
        Args:
            key_path: 配置键路径
            value: 配置值
        """
        with self._lock:
            try:
                keys = key_path.split('.')
                config = self._config_data
                
                # 导航到目标位置
                for key in keys[:-1]:
                    if key not in config:
                        config[key] = {}
                    config = config[key]
                
                # 设置值
                config[keys[-1]] = value
                logger.debug(f"配置值已设置: {key_path} = {value}")
                
            except Exception as e:
                logger.error(f"设置配置值失败: {key_path}, {e}")
    
    def save_config(self):
        """保存配置到文件"""
        with self._lock:
            try:
                # 确保目录存在
                os.makedirs(os.path.dirname(self._config_file), exist_ok=True)
                
                with open(self._config_file, 'w', encoding='utf-8') as f:
                    json.dump(self._config_data, f, indent=2, ensure_ascii=False)
                
                logger.info(f"配置文件保存成功: {self._config_file}")
                
            except Exception as e:
                logger.error(f"保存配置文件失败: {e}")
    
    def reload_config(self):
        """重新加载配置文件"""
        with self._lock:
            self._load_config()
            logger.info("配置文件已重新加载")
    
    def get_section(self, section_name: str) -> Dict[str, Any]:
        """获取配置节"""
        return self.get(section_name, {})
    
    def update_section(self, section_name: str, section_data: Dict[str, Any]):
        """更新配置节"""
        with self._lock:
            if section_name not in self._config_data:
                self._config_data[section_name] = {}
            
            self._config_data[section_name].update(section_data)
    
    # 便捷方法：分辨率适配器配置
    def get_reference_resolution(self) -> Dict[str, Union[int, float]]:
        """获取基准分辨率配置"""
        return self.get('universal_resolution_adapter.reference_resolution', {
            'width': 0, 'height': 0, 'dpi': 96, 'scale_factor': 1.0
        })
    
    def get_cache_timeout(self) -> float:
        """获取缓存超时时间"""
        return self.get('universal_resolution_adapter.cache_settings.window_state_timeout', 1.0)
    
    def is_caching_enabled(self) -> bool:
        """检查是否启用缓存"""
        return self.get('universal_resolution_adapter.cache_settings.enable_caching', True)
    
    # 便捷方法：坐标系统配置
    def get_default_coordinate_type(self) -> str:
        """获取默认坐标类型"""
        return self.get('universal_coordinate_system.default_coordinate_type', 'REFERENCE')
    
    def is_boundary_check_enabled(self) -> bool:
        """检查是否启用边界检查"""
        return self.get('universal_coordinate_system.validation_settings.enable_boundary_check', True)
    
    def get_default_random_offset(self) -> int:
        """获取默认随机偏移范围"""
        return self.get('universal_coordinate_system.random_offset.default_range', 5)
    
    # 便捷方法：窗口管理器配置
    def get_default_target_size(self) -> Tuple[int, int]:
        """获取默认目标窗口尺寸"""
        width = self.get('universal_window_manager.adjustment_settings.default_target_width', 0)
        height = self.get('universal_window_manager.adjustment_settings.default_target_height', 0)
        return width, height
    
    def is_window_monitoring_enabled(self) -> bool:
        """检查是否启用窗口监控"""
        return self.get('universal_window_manager.monitoring.enable_window_monitoring', False)
    
    def get_monitoring_interval(self) -> float:
        """获取监控间隔"""
        return self.get('universal_window_manager.monitoring.check_interval', 5.0)
    
    # 便捷方法：任务集成配置
    def is_universal_processing_enabled(self, task_type: str) -> bool:
        """检查指定任务类型是否启用通用处理"""
        return self.get(f'task_integration.{task_type}.enable_universal_processing', True)
    
    def is_legacy_fallback_enabled(self, task_type: str = None) -> bool:
        """检查是否启用传统方法回退"""
        if task_type:
            return self.get(f'task_integration.{task_type}.fallback_to_legacy', True)
        else:
            return self.get('compatibility.enable_legacy_fallback', True)
    
    # 便捷方法：调试配置
    def is_detailed_logging_enabled(self) -> bool:
        """检查是否启用详细日志"""
        return self.get('debugging.enable_detailed_logging', False)
    
    def is_coordinate_logging_enabled(self) -> bool:
        """检查是否启用坐标转换日志"""
        return self.get('debugging.log_coordinate_conversions', False)
    
    def get_debug_output_directory(self) -> str:
        """获取调试输出目录"""
        return self.get('debugging.debug_output_directory', 'debug_output')
    
    # 便捷方法：性能配置
    def is_coordinate_caching_enabled(self) -> bool:
        """检查是否启用坐标缓存"""
        return self.get('performance.enable_coordinate_caching', True)
    
    def get_coordinate_cache_timeout(self) -> float:
        """获取坐标缓存超时时间"""
        return self.get('performance.coordinate_cache_timeout', 0.5)
    
    def get_max_cache_entries(self) -> int:
        """获取最大缓存条目数"""
        return self.get('performance.max_cache_entries', 50)

# 全局配置管理器实例
_config_manager = None
_config_lock = threading.Lock()

def get_universal_config() -> UniversalConfigManager:
    """获取全局配置管理器实例"""
    global _config_manager
    if _config_manager is None:
        with _config_lock:
            if _config_manager is None:
                _config_manager = UniversalConfigManager()
    return _config_manager


# 便捷函数
def get_config(key_path: str, default: Any = None) -> Any:
    """获取配置值的便捷函数"""
    return get_universal_config().get(key_path, default)

def set_config(key_path: str, value: Any):
    """设置配置值的便捷函数"""
    get_universal_config().set(key_path, value)

def save_config():
    """保存配置的便捷函数"""
    get_universal_config().save_config()
