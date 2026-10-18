"""内置和独立脚本共用的中文图像操作；图像只由调用者持有。"""

from __future__ import annotations

from .script_parameters import boolean_parameter, integer_parameter, number_parameter


IMAGE_METHODS = (
    "截帧", "读取", "形状", "元素数", "通道", "灰度", "缩放", "匹配", "最高匹配", "去重",
)


def _libraries():
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ValueError("图像处理缺少依赖，请安装 numpy 和 opencv-python") from exc
    return cv2, np


def _image(value, label="图像"):
    _, np = _libraries()
    if not isinstance(value, np.ndarray) or value.ndim not in (2, 3) or value.size == 0:
        raise ValueError(f"{label}必须是非空的二维或三维数组")
    return value


class ImageApi:
    def __init__(self, read_resource, capture):
        self._read_resource = read_resource
        self._capture = capture

    def close(self):
        self._read_resource = None
        self._capture = None

    def 截帧(self):
        if self._capture is None:
            raise ValueError("图像接口已关闭")
        return _image(self._capture(), "窗口截图")

    def 读取(self, 路径, 要求透明=False):
        required = boolean_parameter(要求透明, "要求透明")
        if not isinstance(路径, str) or not 路径.strip():
            raise ValueError("图像路径必须是非空文本")
        if self._read_resource is None:
            raise ValueError("图像接口已关闭")
        data = self._read_resource(路径)
        if not data:
            raise ValueError("图片资源不存在或为空：" + 路径)
        cv2, np = _libraries()
        try:
            image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
        except cv2.error as exc:
            raise ValueError("图片解码失败：" + 路径) from exc
        if image is None or image.size == 0:
            raise ValueError("图片解码失败：" + 路径)
        if required and (image.ndim != 3 or image.shape[2] != 4 or not np.any(image[:, :, 3])):
            raise ValueError("请使用带有效透明遮罩的图片：" + 路径)
        return image

    @staticmethod
    def 形状(画面):
        return tuple(int(part) for part in _image(画面).shape)

    @staticmethod
    def 元素数(画面):
        return int(_image(画面).size)

    @staticmethod
    def 通道(画面, 序号):
        image = _image(画面)
        index = integer_parameter(序号, "通道序号", minimum=0)
        if image.ndim != 3 or index >= image.shape[2]:
            raise ValueError("通道序号超出图像通道范围")
        return image[:, :, index]

    @staticmethod
    def 灰度(画面):
        cv2, _ = _libraries()
        image = _image(画面)
        if image.ndim == 2:
            return image
        if image.shape[2] not in (3, 4):
            raise ValueError("灰度转换只接受灰度、BGR 或 BGRA 图像")
        code = cv2.COLOR_BGRA2GRAY if image.shape[2] == 4 else cv2.COLOR_BGR2GRAY
        try:
            return cv2.cvtColor(image, code)
        except cv2.error as exc:
            raise ValueError("灰度转换失败，请检查图像数据类型") from exc

    @staticmethod
    def 缩放(画面, 倍率=None, 尺寸=None, 插值="面积"):
        cv2, _ = _libraries()
        image = _image(画面)
        modes = {"面积": cv2.INTER_AREA, "最近邻": cv2.INTER_NEAREST, "线性": cv2.INTER_LINEAR, "三次": cv2.INTER_CUBIC}
        if not isinstance(插值, str) or 插值 not in modes:
            raise ValueError("缩放插值只能是 面积、最近邻、线性 或 三次")
        if (倍率 is None) == (尺寸 is None):
            raise ValueError("图像缩放必须且只能指定倍率或尺寸")
        if 尺寸 is not None:
            if not isinstance(尺寸, (tuple, list)) or len(尺寸) != 2:
                raise ValueError("缩放尺寸必须是（宽, 高）")
            size = tuple(integer_parameter(value, "缩放尺寸", minimum=1) for value in 尺寸)
            try:
                return cv2.resize(image, size, interpolation=modes[插值])
            except cv2.error as exc:
                raise ValueError("图像缩放失败，请检查图像类型和尺寸") from exc
        scale = number_parameter(倍率, "缩放倍率")
        if scale <= 0 or round(image.shape[0] * scale) < 1 or round(image.shape[1] * scale) < 1:
            raise ValueError("缩放倍率必须大于0，且缩放后的宽高不能小于1")
        try:
            return cv2.resize(image, None, fx=scale, fy=scale, interpolation=modes[插值])
        except cv2.error as exc:
            raise ValueError("图像缩放失败，请检查图像类型和倍率") from exc

    @staticmethod
    def 匹配(画面, 模板, 遮罩=None):
        cv2, np = _libraries()
        image, template = _image(画面), _image(模板, "模板")
        if template.shape[0] > image.shape[0] or template.shape[1] > image.shape[1]:
            raise ValueError("模板尺寸不能大于画面")
        if image.dtype != template.dtype or image.dtype not in (np.uint8, np.float32) or image.shape[2:] != template.shape[2:]:
            raise ValueError("画面和模板必须具有相同通道及类型，类型只接受8位整数或32位小数")
        if 遮罩 is not None:
            mask = _image(遮罩, "遮罩")
            if mask.shape[:2] != template.shape[:2] or mask.dtype not in (np.uint8, np.float32):
                raise ValueError("遮罩尺寸必须与模板相同，类型只接受8位整数或32位小数")
            if mask.ndim == 3 and mask.shape[2] != 1 and mask.shape[2:] != template.shape[2:]:
                raise ValueError("遮罩通道必须为单通道或与模板相同")
            if not np.all(np.isfinite(mask)) or not np.any(mask):
                raise ValueError("遮罩必须包含有效像素且不能包含非有限值")
        try:
            scores = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED, mask=遮罩)
        except cv2.error as exc:
            raise ValueError("图像模板匹配失败，请检查画面、模板和遮罩") from exc
        # 无定义的相关性不能作为命中；与原始识别脚本的处理一致。
        np.nan_to_num(scores, copy=False, nan=-1, posinf=-1, neginf=-1)
        return scores

    @staticmethod
    def 最高匹配(热图):
        cv2, np = _libraries()
        scores = _image(热图, "匹配热图")
        if scores.ndim != 2 or scores.dtype not in (np.uint8, np.float32, np.float64) or not np.all(np.isfinite(scores)):
            raise ValueError("匹配热图必须是有限数值的单通道数组")
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        return float(score), int(x), int(y)

    @staticmethod
    def 去重(框, 分数, 阈值=0.8, 重叠阈值=0.3):
        cv2, np = _libraries()
        threshold = number_parameter(阈值, "匹配阈值")
        overlap = number_parameter(重叠阈值, "重叠阈值")
        if not 0 <= threshold <= 1 or not 0 <= overlap <= 1:
            raise ValueError("匹配阈值和重叠阈值必须在0到1之间")
        if not isinstance(框, (list, tuple)) or not isinstance(分数, (list, tuple)) or len(框) != len(分数):
            raise ValueError("框和分数必须是等长列表")
        boxes, scores = [], []
        for box, score in zip(框, 分数):
            if not isinstance(box, (list, tuple)) or len(box) != 4:
                raise ValueError("每个框必须是（左, 顶, 宽, 高）")
            values = [float(number_parameter(value, "框坐标")) for value in box]
            if values[2] <= 0 or values[3] <= 0:
                raise ValueError("框的宽高必须大于0")
            boxes.append(values)
            scores.append(float(number_parameter(score, "匹配分数")))
        if not boxes:
            return []
        indices = cv2.dnn.NMSBoxes(boxes, scores, threshold, overlap)
        return [int(index) for index in np.asarray(indices).reshape(-1)]
