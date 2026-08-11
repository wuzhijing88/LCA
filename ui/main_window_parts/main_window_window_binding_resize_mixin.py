import logging

logger = logging.getLogger(__name__)


class MainWindowWindowBindingResizeMixin:

    def _apply_multi_window_resize(self):

        """应用多窗口分辨率调整（使用通用窗口管理器）"""

        try:

            logger.debug("开始多窗口分辨率调整")

            target_client_width = self.custom_width

            target_client_height = self.custom_height

            if target_client_width <= 0 or target_client_height <= 0:

                logging.info("未配置自定义分辨率，跳过多窗口大小调整。")

                return

            # 工具 修复：安全检查绑定窗口

            if not hasattr(self, 'bound_windows') or not self.bound_windows:

                logging.warning("没有绑定窗口，跳过多窗口大小调整。")

                return

            # 获取所有启用的绑定窗口

            enabled_windows = [w for w in self.bound_windows if w.get('enabled', True)]

            if not enabled_windows:

                logging.warning("没有启用的绑定窗口，跳过多窗口大小调整。")

                return

            logger.debug(f"准备调整 {len(enabled_windows)} 个窗口的分辨率")

        except Exception as init_error:

            logger.error(f"多窗口分辨率调整初始化失败: {init_error}", exc_info=True)

            return

        try:

            # 工具 修复：安全导入和初始化通用分辨率适配器

            logger.debug("导入通用分辨率适配器")

            from utils.universal_resolution_adapter import get_universal_adapter

            logger.debug("获取适配器实例")

            adapter = get_universal_adapter()

            # 调试：打印窗口信息和检查句柄重复

            logging.info("调试：多窗口调整前的窗口状态:")

            # 检查句柄重复

            hwnd_count = {}

            for i, window_info in enumerate(enabled_windows):

                hwnd = window_info.get('hwnd')

                title = window_info.get('title', '未知窗口')

                if hwnd:

                    hwnd_count[hwnd] = hwnd_count.get(hwnd, 0) + 1

                    debug_info = adapter.debug_window_info(hwnd)

                    logging.info(f"  窗口 {i+1}: {title}")

                    logging.info(f"    HWND: {hwnd}")

                    logging.info(f"    类名: {debug_info.get('class_name', 'N/A')}")

                    logging.info(f"    客户区尺寸: {debug_info.get('client_size', 'N/A')}")

                    logging.info(f"    窗口尺寸: {debug_info.get('window_size', 'N/A')}")

                    logging.info(f"    可见: {debug_info.get('is_visible', 'N/A')}")

                    logging.info(f"    启用: {debug_info.get('is_enabled', 'N/A')}")

                else:

                    logging.warning(f"  窗口 {i+1}: {title} - 无有效句柄")

            # 报告句柄重复情况

            duplicate_hwnds = [hwnd for hwnd, count in hwnd_count.items() if count > 1]

            if duplicate_hwnds:

                logging.error(f"发现重复的窗口句柄: {duplicate_hwnds}")

                for hwnd in duplicate_hwnds:

                    logging.error(f"  句柄 {hwnd} 被 {hwnd_count[hwnd]} 个窗口使用")

            else:

                logging.info("所有窗口句柄都是唯一的")

            # 使用通用窗口管理器批量调整窗口（异步模式）

            from utils.universal_window_manager import get_universal_window_manager

            window_manager = get_universal_window_manager()

            results = []

            for window_info in enabled_windows:

                hwnd = window_info.get('hwnd')

                if hwnd:

                    # 每个窗口使用异步调整

                    result = window_manager.adjust_single_window(

                        hwnd, target_client_width, target_client_height, async_mode=True

                    )

                    results.append(result)

            # 生成调整报告

            report = window_manager.create_adjustment_report(results)

            logging.info(f"多窗口分辨率调整完成:")

            logging.info(f"  总窗口数: {report['summary']['total_windows']}")

            logging.info(f"  成功: {report['summary']['successful']}")

            logging.info(f"  失败: {report['summary']['failed']}")

            logging.info(f"  成功率: {report['summary']['success_rate']}")

            # 记录失败的窗口

            for failed_window in report['failed_windows']:

                logging.error(f"  失败窗口: {failed_window['title']} - {failed_window['reason']}")

            # 调试：打印调整后的窗口状态

            logging.info("调试：多窗口调整后的窗口状态:")

            for i, window_info in enumerate(enabled_windows):

                hwnd = window_info.get('hwnd')

                title = window_info.get('title', '未知窗口')

                if hwnd:

                    debug_info = adapter.debug_window_info(hwnd)

                    logging.info(f"  窗口 {i+1}: {title}")

                    logging.info(f"    调整后客户区尺寸: {debug_info.get('client_size', 'N/A')}")

        except Exception as e:

            logging.error(f"使用通用窗口管理器调整失败: {e}")
