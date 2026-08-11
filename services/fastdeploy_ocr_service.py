#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
支持PPOCRv3 CPU版本，提供更好的性能和部署体验
"""

import logging
import threading
import time
import os
import sys
import gc
from typing import Optional, Dict, List, Any, Tuple
import numpy as np

logger = logging.getLogger(__name__)

# 打包环境支持
def setup_packaged_fastdeploy():
    """设置打包环境的FastDeploy支持"""
    try:
        if getattr(sys, 'frozen', False):
            # 获取打包后的路径
            if hasattr(sys, '_MEIPASS'):
                base_path = sys._MEIPASS
            else:
                exe_path = os.path.abspath(sys.executable)
                try:
                    exe_path = os.path.realpath(exe_path)
                except Exception:
                    pass
                base_path = os.path.dirname(exe_path)

            # FastDeploy DLL 路径 - 按照 venv 的目录结构
            fd_libs = os.path.join(base_path, 'fastdeploy', 'libs')

            possible_paths = [
                # FastDeploy 主库目录
                fd_libs,

                # OpenVINO
                os.path.join(fd_libs, 'third_libs', 'openvino', 'runtime', 'bin'),

                # TBB
                os.path.join(fd_libs, 'third_libs', 'openvino', 'runtime', '3rdparty', 'tbb', 'bin'),

                # Paddle Inference
                os.path.join(fd_libs, 'third_libs', 'paddle_inference', 'paddle', 'lib'),
                os.path.join(fd_libs, 'third_libs', 'paddle_inference', 'third_party', 'install', 'mklml', 'lib'),
                os.path.join(fd_libs, 'third_libs', 'paddle_inference', 'third_party', 'install', 'mkldnn', 'lib'),

                # OpenCV
                os.path.join(fd_libs, 'third_libs', 'opencv', 'build', 'x64', 'vc14', 'bin'),

                # ICU
                os.path.join(fd_libs, 'third_libs', 'fast_tokenizer', 'third_party', 'lib'),

                # 主目录（备用）
                base_path,
            ]

            # 添加所有存在的路径
            for lib_path in possible_paths:
                if os.path.exists(lib_path):
                    try:
                        if hasattr(os, 'add_dll_directory'):
                            os.add_dll_directory(lib_path)

                        current_path = os.environ.get('PATH', '')
                        if lib_path not in current_path:
                            os.environ['PATH'] = lib_path + os.pathsep + current_path

                        logger.debug(f"添加DLL路径: {lib_path}")
                    except Exception as e:
                        logger.warning(f"无法添加路径 {lib_path}: {e}")

    except Exception as e:
        logger.error(f"设置打包环境失败: {e}")

# 延迟导入标志 - 避免在模块导入时立即加载重型库
_fastdeploy_setup_done = False
_fastdeploy_import_attempted = False
FASTDEPLOY_AVAILABLE = False
fd = None
cv2 = None
_FASTDEPLOY_IMPORT_ERROR = None


def _format_exception_detail(exc: Exception) -> str:
    """统一格式化异常详情，便于跨进程透传。"""
    if exc is None:
        return ""
    exc_type = type(exc).__name__
    message = str(exc).strip()
    return f"{exc_type}: {message}" if message else exc_type


def get_fastdeploy_import_error_detail() -> str:
    """返回最近一次 FastDeploy 导入失败详情。"""
    return str(_FASTDEPLOY_IMPORT_ERROR or "").strip()

def _ensure_fastdeploy_setup():
    """确保FastDeploy环境已设置（延迟执行）"""
    global _fastdeploy_setup_done
    if not _fastdeploy_setup_done:
        setup_packaged_fastdeploy()
        _fastdeploy_setup_done = True

def _ensure_fastdeploy_imported():
    """确保FastDeploy已导入（延迟执行）"""
    global _fastdeploy_import_attempted, FASTDEPLOY_AVAILABLE, fd, cv2, _FASTDEPLOY_IMPORT_ERROR

    if _fastdeploy_import_attempted:
        return FASTDEPLOY_AVAILABLE

    _fastdeploy_import_attempted = True
    _FASTDEPLOY_IMPORT_ERROR = None

    # 先设置环境
    _ensure_fastdeploy_setup()

    # 然后尝试导入
    try:
        import fastdeploy as fd_module
        import cv2 as cv2_module
        fd = fd_module
        cv2 = cv2_module
        FASTDEPLOY_AVAILABLE = True
        _FASTDEPLOY_IMPORT_ERROR = None
        logger.debug("FastDeploy 延迟导入成功")
        return True
    except ImportError as e:
        FASTDEPLOY_AVAILABLE = False
        _FASTDEPLOY_IMPORT_ERROR = _format_exception_detail(e)
        logger.warning(f"FastDeploy 未安装: {_FASTDEPLOY_IMPORT_ERROR}")
        logger.warning("请运行: pip install fastdeploy-python")
        return False
    except Exception as e:
        FASTDEPLOY_AVAILABLE = False
        _FASTDEPLOY_IMPORT_ERROR = _format_exception_detail(e)
        logger.error(f"FastDeploy 运行时错误: {_FASTDEPLOY_IMPORT_ERROR}")
        logger.warning("OCR功能将不可用，可能是打包环境问题")
        return False

class FastDeployOCRService:
    """FastDeploy OCR服务管理器 - 支持单例和多实例模式"""

    _instance = None
    _lock = threading.Lock()
    _creation_count = 0  # 跟踪实例创建次数

    def __new__(cls, force_new_instance=False):
        """
        创建实例

        Args:
            force_new_instance: 如果为True,强制创建新实例(用于并发worker)
        """
        if force_new_instance:
            # 并发模式：每次创建新实例
            instance = super(FastDeployOCRService, cls).__new__(cls)
            with cls._lock:
                cls._creation_count += 1
                logger.debug(f"创建FastDeployOCRService新实例 (总数: {cls._creation_count})")
            return instance
        else:
            # 单例模式：复用同一实例
            if cls._instance is None:
                with cls._lock:
                    if cls._instance is None:
                        cls._instance = super(FastDeployOCRService, cls).__new__(cls)
                        cls._creation_count += 1
                        logger.debug(f"创建FastDeployOCRService单例实例 (创建次数: {cls._creation_count})")
            return cls._instance

    def __init__(self, force_new_instance=False):
        # 避免重复初始化（仅对单例模式有效）
        if hasattr(self, '_initialized') and not force_new_instance:
            return

        self._initialized = True
        self._ocr_pipeline = None
        self._det_model = None
        self._cls_model = None
        self._rec_model = None
        self._init_lock = threading.Lock()
        self._recognition_lock = threading.Lock()
        self._is_initializing = False
        self._init_error = None

        # 实例级别的时间控制（不再是类级别）
        self._last_predict_time = 0
        self._min_predict_interval = 0.01  # 10ms

        # 简单状态管理
        self._service_active = False

        # 错误容忍机制
        self._error_count = 0
        self._max_error_count = 5
        self._last_success_time = time.time()

        # 模型路径配置
        self._model_paths = self._get_default_model_paths()

        logger.debug("FastDeploy OCR服务管理器已创建")

    def _get_default_model_paths(self) -> Dict[str, str]:
        """获取默认的PPOCRv3模型路径"""
        # 检查是否为打包环境
        if getattr(sys, 'frozen', False):
            # 打包环境 - 优先使用打包内的模型
            # 【Nuitka兼容】构建可能的路径列表，需要安全检查 _MEIPASS
            possible_paths = []
            source_types = []

            # PyInstaller 使用 _MEIPASS（Nuitka不会设置此属性）
            if hasattr(sys, '_MEIPASS'):
                possible_paths.append(os.path.join(sys._MEIPASS, 'models', 'ppocrv3'))
                source_types.append("打包内模型(PyInstaller)")

            # exe同目录（Nuitka和PyInstaller都适用）
            exe_path = os.path.abspath(sys.executable)
            try:
                exe_path = os.path.realpath(exe_path)
            except Exception:
                pass
            possible_paths.append(os.path.join(os.path.dirname(exe_path), 'models', 'ppocrv3'))
            source_types.append("exe同目录")

            # 用户目录（备用）
            possible_paths.append(os.path.join(os.path.expanduser('~'), '.fastdeploy', 'models', 'ppocrv3'))
            source_types.append("用户目录")

            # 选择第一个存在的路径
            models_path = None
            for i, path in enumerate(possible_paths):
                if os.path.exists(path):
                    models_path = path
                    logger.info(f"找到模型路径: {models_path} ({source_types[i]})")
                    break

            if models_path is None:
                # 如果都不存在，使用用户目录并尝试下载
                models_path = os.path.join(os.path.expanduser('~'), '.fastdeploy', 'models', 'ppocrv3')
                logger.info(f"使用用户目录模型路径: {models_path}")
                logger.info("将尝试下载模型到用户目录")
        else:
            # 开发环境
            models_path = os.path.join(os.getcwd(), 'models', 'ppocrv3')

        return {
            'det_model': os.path.join(models_path, 'ch_PP-OCRv3_det_infer'),
            'cls_model': os.path.join(models_path, 'ch_ppocr_mobile_v2.0_cls_infer'),
            'rec_model': os.path.join(models_path, 'ch_PP-OCRv3_rec_infer')
        }

    def set_model_paths(self, det_model: str = None, cls_model: str = None, rec_model: str = None):
        """设置自定义模型路径"""
        if det_model:
            self._model_paths['det_model'] = det_model
        if cls_model:
            self._model_paths['cls_model'] = cls_model
        if rec_model:
            self._model_paths['rec_model'] = rec_model
        
        logger.info(f"已更新模型路径: {self._model_paths}")

    def _validate_local_models(self) -> bool:
        missing_paths = [
            path
            for path in self._model_paths.values()
            if not os.path.exists(path)
        ]
        models_dir = os.path.dirname(self._model_paths["det_model"])
        dictionary_path = os.path.join(models_dir, "ppocr_keys_v1.txt")
        if not os.path.exists(dictionary_path):
            missing_paths.append(dictionary_path)

        if missing_paths:
            logger.error(
                "本地 OCR 资源不完整，请将模型和字典文件放入 models/ppocrv3：%s",
                ", ".join(missing_paths),
            )
            return False
        return True

    def initialize(self, force_reinit: bool = False) -> bool:
        """初始化FastDeploy OCR引擎"""
        # 延迟导入FastDeploy
        if not _ensure_fastdeploy_imported():
            self._init_error = get_fastdeploy_import_error_detail() or "FastDeploy 延迟导入失败"
            logger.error(f"FastDeploy不可用，无法初始化OCR服务: {self._init_error}")
            return False

        # 如果服务已经激活且不强制重新初始化，直接返回（避免重复初始化）
        if self._service_active and not force_reinit:
            logger.debug("OCR服务已激活，跳过重复初始化")
            return True

        if self._is_initializing:
            logger.debug("OCR引擎正在初始化中，请稍候...")
            return False

        with self._init_lock:
            # 双重检查
            if self._service_active and not force_reinit:
                logger.debug("OCR服务已激活（双重检查），跳过重复初始化")
                return True

            self._is_initializing = True
            self._init_error = None

            try:
                logger.info("开始初始化FastDeploy OCR引擎...")

                # 下载模型（如果需要）
                if not self._validate_local_models():
                    logger.error("模型下载失败，无法初始化OCR服务")
                    logger.error("请检查网络连接或手动下载模型文件")
                    raise RuntimeError("模型文件不可用，无法初始化OCR服务")

                # 创建运行时选项（CPU模式）
                # 【内存优化】设置ONNX Runtime选项减少内存占用
                def create_memory_optimized_option():
                    """创建内存优化的运行时选项"""
                    option = fd.RuntimeOption()
                    option.use_cpu()
                    # 【注意】不再限制CPU线程数（会导致OCR变慢）
                    # 使用默认线程数（-1），让ONNX Runtime自动选择最佳线程数
                    # option.set_cpu_thread_num(1)  # 已移除：导致OCR识别变慢

                    # 【内存优化】配置ONNX Runtime选项
                    try:
                        # 设置ONNX Runtime的图优化级别为基础级别（减少内存使用）
                        # 级别: 0=禁用, 1=基础, 2=扩展, 99=所有
                        option.ort_option.graph_optimization_level = 1

                        # 【内存泄漏修复】禁用内存模式优化，减少内存缓存
                        # 这可能会略微影响性能，但能防止内存增长
                        try:
                            option.ort_option.enable_mem_pattern = False
                        except:
                            pass

                        # 【内存泄漏修复】禁用内存arena（内存池），每次分配后立即释放
                        try:
                            option.ort_option.enable_cpu_mem_arena = False
                        except:
                            pass

                    except Exception as e:
                        logger.debug(f"设置graph_optimization_level失败: {e}")

                    return option

                det_option = create_memory_optimized_option()
                cls_option = create_memory_optimized_option()
                rec_option = create_memory_optimized_option()

                # 初始化各个模型
                try:
                    det_model_file = os.path.join(self._model_paths['det_model'], 'inference.pdmodel')
                    det_params_file = os.path.join(self._model_paths['det_model'], 'inference.pdiparams')
                    self._det_model = fd.vision.ocr.DBDetector(
                        det_model_file, det_params_file,
                        runtime_option=det_option
                    )
                    # 注意：DBDetector不启用static_shape_infer
                    # 因为它处理完整截图，预分配大图缓冲区会导致启动内存过高
                    # 检测模型的形状缓存增长相对较小，主要内存泄漏来自Recognizer
                    logger.debug("检测模型初始化成功")
                except Exception as e:
                    logger.error(f"检测模型初始化失败: {e}")
                    raise RuntimeError(f"检测模型初始化失败: {_format_exception_detail(e)}") from e

                try:
                    cls_model_file = os.path.join(self._model_paths['cls_model'], 'inference.pdmodel')
                    cls_params_file = os.path.join(self._model_paths['cls_model'], 'inference.pdiparams')
                    self._cls_model = fd.vision.ocr.Classifier(
                        cls_model_file, cls_params_file,
                        runtime_option=cls_option
                    )
                    # 注意：Classifier没有static_shape_infer属性，因为其输入尺寸固定
                    logger.debug("分类模型初始化成功")
                except Exception as e:
                    logger.error(f"分类模型初始化失败: {e}")
                    raise RuntimeError(f"分类模型初始化失败: {_format_exception_detail(e)}") from e

                try:
                    rec_model_file = os.path.join(self._model_paths['rec_model'], 'inference.pdmodel')
                    rec_params_file = os.path.join(self._model_paths['rec_model'], 'inference.pdiparams')

                    # 查找字典文件
                    models_dir = os.path.dirname(self._model_paths['det_model'])
                    dict_path = os.path.join(models_dir, 'ppocr_keys_v1.txt')

                    if os.path.exists(dict_path):
                        self._rec_model = fd.vision.ocr.Recognizer(
                            rec_model_file, rec_params_file, dict_path,
                            runtime_option=rec_option
                        )
                    else:
                        # 如果字典文件不存在，不使用字典
                        self._rec_model = fd.vision.ocr.Recognizer(
                            rec_model_file, rec_params_file,
                            runtime_option=rec_option
                        )

                    # 【识别率优化】禁用static_shape_infer以提高识别准确率
                    # static_shape_infer会将所有文字强制resize到固定尺寸，导致：
                    # 1. 长文本被压缩变形
                    # 2. 短文本被拉伸失真
                    # 3. 小字体缩放后模糊
                    # 虽然禁用后可能有轻微内存增长，但识别率提升更重要
                    try:
                        if hasattr(self._rec_model, 'preprocessor'):
                            self._rec_model.preprocessor.static_shape_infer = False
                            logger.info("[识别率优化] Recognizer禁用static_shape_infer，使用动态尺寸以提高识别准确率")
                    except Exception as shape_err:
                        logger.warning(f"[识别率优化] 设置static_shape_infer失败: {shape_err}")

                    logger.debug("识别模型初始化成功")
                except Exception as e:
                    logger.error(f"识别模型初始化失败: {e}")
                    raise RuntimeError(f"识别模型初始化失败: {_format_exception_detail(e)}") from e

                # 创建PPOCRv3管道
                self._ocr_pipeline = fd.vision.ocr.PPOCRv3(
                    det_model=self._det_model,
                    cls_model=self._cls_model,
                    rec_model=self._rec_model
                )

                self._service_active = True
                self._error_count = 0

                logger.info("FastDeploy OCR引擎初始化成功，服务已激活（单例模式）")
                return True

            except Exception as e:
                self._init_error = _format_exception_detail(e)
                logger.error(f"FastDeploy OCR引擎初始化失败: {self._init_error}")
                return False

            finally:
                self._is_initializing = False

    def is_ready(self) -> bool:
        """检查OCR服务是否就绪"""
        return self._service_active and self._ocr_pipeline is not None

    def recognize_text(self, image: np.ndarray, confidence: float = 0.5) -> List[Dict[str, Any]]:
        """
        使用FastDeploy识别文字

        Args:
            image: 输入图像 (numpy数组)
            confidence: 置信度阈值

        Returns:
            识别结果列表，每个元素包含 {'text': str, 'confidence': float, 'bbox': list}
        """
        if not self.is_ready():
            logger.warning("OCR服务未就绪")
            return []

        # 优化: 减少锁竞争 - 先检查和预处理,再加锁推理
        processed_image = None
        result = None
        need_convert = False
        try:
            # 预处理图像(不需要锁)
            # 【内存优化】检查图像是否需要转换，避免不必要的内存分配
            if len(image.shape) == 3 and image.shape[2] == 4:
                # RGBA转RGB - 必须转换
                processed_image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
                need_convert = True
            elif len(image.shape) == 3 and image.shape[2] == 3:
                # 3通道图像 - FastDeploy内部会处理BGR/RGB，避免不必要的转换
                # 【关键修复】不再每次都转换，直接使用原图
                processed_image = image
                need_convert = False
            else:
                # 其他情况直接使用
                processed_image = image
                need_convert = False


            # 只在推理时加锁,减少锁持有时间
            with self._recognition_lock:
                # 添加微小延迟,减少线程竞争导致的上下文切换
                elapsed = time.time() - self._last_predict_time
                if elapsed < self._min_predict_interval:
                    time.sleep(self._min_predict_interval - elapsed)

                # 执行OCR识别
                result = self._ocr_pipeline.predict(processed_image)
                self._last_predict_time = time.time()

            # 【内存泄漏修复】推理完成后立即释放转换后的图像
            if need_convert and processed_image is not None:
                del processed_image
                processed_image = None

            # 结果处理(不需要锁)
            formatted_results = []

            if result and hasattr(result, 'boxes') and hasattr(result, 'text'):
                # 【内存泄漏修复】先提取所有需要的数据到纯Python原生类型（int/float/str）
                # 避免任何numpy标量残留
                boxes_list = []
                texts_list = []
                scores_list = []

                # 【关键修复】显式转换为纯Python类型，避免numpy标量
                for box in result.boxes:
                    if hasattr(box, 'tolist'):
                        # numpy数组 -> Python list
                        py_box = box.tolist()
                    else:
                        py_box = list(box)

                    # 【修复】检查py_box的结构：可能是[[x1,y1],[x2,y2]...]或[x1,y1,x2,y2...]
                    # FastDeploy返回的boxes格式是 [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
                    if py_box and isinstance(py_box[0], (list, tuple)):
                        # 已经是二维列表，确保每个坐标是纯Python float
                        converted_box = []
                        for point in py_box:
                            converted_box.append([float(coord) for coord in point])
                        boxes_list.append(converted_box)
                    else:
                        # 扁平列表，直接转换为float列表
                        boxes_list.append([float(coord) for coord in py_box])

                for text in result.text:
                    texts_list.append(str(text))

                for score in result.rec_scores:
                    # 【关键】确保是纯Python float，不是numpy.float32
                    scores_list.append(float(score))

                # 【关键修复】立即清理result对象 - 在提取数据后立即删除
                # FastDeploy的OCRResult内部持有numpy数组的引用
                try:
                    # 尝试清空内部列表
                    if hasattr(result, 'boxes'):
                        try:
                            result.boxes.clear()
                        except:
                            pass
                    if hasattr(result, 'text'):
                        try:
                            result.text.clear()
                        except:
                            pass
                    if hasattr(result, 'rec_scores'):
                        try:
                            result.rec_scores.clear()
                        except:
                            pass
                    if hasattr(result, 'cls_scores'):
                        try:
                            result.cls_scores.clear()
                        except:
                            pass
                    if hasattr(result, 'cls_labels'):
                        try:
                            result.cls_labels.clear()
                        except:
                            pass
                except:
                    pass

                # 删除result引用
                del result
                result = None

                # 构建结果（使用Python原生类型）
                for bbox, text, conf in zip(boxes_list, texts_list, scores_list):
                    if conf >= confidence:
                        formatted_results.append({
                            'text': text,
                            'confidence': conf,
                            'bbox': bbox
                        })

                # 清理临时列表
                boxes_list.clear()
                texts_list.clear()
                scores_list.clear()
                del boxes_list, texts_list, scores_list
            else:
                # 【内存泄漏修复】即使result为空或没有属性，也要清理
                if result is not None:
                    del result
                    result = None

            self._last_success_time = time.time()
            self._error_count = 0

            return formatted_results

        except Exception as e:
            self._error_count += 1
            logger.error(f"OCR识别失败: {e}")

            # 如果错误次数过多，尝试重新初始化
            if self._error_count >= self._max_error_count:
                logger.warning("OCR错误次数过多，尝试重新初始化...")
                # 【修复闪退】使用锁保护状态变更，防止竞态条件
                with self._init_lock:
                    # 双重检查：避免多个线程同时触发重初始化
                    if self._service_active and not self._is_initializing:
                        self._service_active = False
                        threading.Thread(target=self.initialize, args=(True,), daemon=True).start()
                    elif self._is_initializing:
                        logger.info("OCR服务正在重新初始化中，跳过重复触发")

            return []

        finally:
            # 【内存泄漏修复】确保临时对象被清理
            if processed_image is not None and processed_image is not image:
                del processed_image
            if result is not None:
                del result


    def cleanup(self):
        """清理FastDeploy资源（别名，等价于shutdown(deep_cleanup=True)）"""
        self.shutdown(deep_cleanup=True)

    def shutdown(self, deep_cleanup: bool = False):
        """关闭OCR服务

        Args:
            deep_cleanup: 是否深度清理（释放所有模型内存）
                - False: 只标记服务为非活跃，模型保留在内存（快速重启）
                - True: 彻底释放所有模型内存（防止内存泄露）
        """
        logger.info(f"正在关闭FastDeploy OCR服务（深度清理: {deep_cleanup}）...")

        self._service_active = False

        if deep_cleanup:
            # 【深度清理】彻底释放所有模型引用，触发垃圾回收
            logger.info("执行深度清理：释放所有OCR模型内存...")
            self._ocr_pipeline = None
            self._det_model = None
            self._cls_model = None
            self._rec_model = None
            self._error_count = 0
            self._init_error = None

            try:
                gc.collect()
            except Exception:
                pass

            try:
                import ctypes
                msvcrt = ctypes.CDLL('msvcrt')
                if hasattr(msvcrt, '_heapmin'):
                    msvcrt._heapmin()
            except Exception:
                pass

            logger.info("FastDeploy OCR服务已关闭（深度清理完成）")
        else:
            # 【快速清理】只标记非活跃，保留模型在内存中供下次使用
            logger.info("FastDeploy OCR服务已标记为非活跃（模型保留在内存中）")

    def get_service_info(self) -> Dict[str, Any]:
        """获取服务信息"""
        return {
            'engine_type': 'fastdeploy',
            'model_type': 'PPOCRv3',
            'backend': 'CPU',
            'service_active': self._service_active,
            'error_count': self._error_count,
            'last_success_time': self._last_success_time,
            'model_paths': self._model_paths,
            'init_error': self._init_error
        }


# 全局服务实例
_fastdeploy_ocr_service = None

def get_fastdeploy_ocr_service() -> FastDeployOCRService:
    """获取FastDeploy OCR服务实例（单例）"""
    global _fastdeploy_ocr_service
    if _fastdeploy_ocr_service is None:
        _fastdeploy_ocr_service = FastDeployOCRService()
    return _fastdeploy_ocr_service





