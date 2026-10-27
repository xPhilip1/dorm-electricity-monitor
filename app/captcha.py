"""
验证码处理模块
支持：图形验证码(OCR)、滑块验证码、手动输入降级
"""
import base64
import io
import logging

logger = logging.getLogger(__name__)


class CaptchaSolver:
    """验证码解决器"""

    def __init__(self, captcha_type='image'):
        self.captcha_type = captcha_type
        self._ocr = None

    @property
    def ocr(self):
        if self._ocr is None:
            try:
                import ddddocr
                self._ocr = ddddocr.DdddOcr(show_ad=False)
                logger.info("ddddocr 加载成功")
            except ImportError:
                logger.warning("ddddocr 未安装，图形验证码识别不可用")
        return self._ocr

    def solve_image(self, image_data: bytes) -> str:
        """
        识别图形验证码
        :param image_data: 图片二进制数据
        :return: 识别结果字符串
        """
        if not self.ocr:
            raise RuntimeError("ddddocr 未安装，无法识别图形验证码")
        try:
            result = self.ocr.classification(image_data)
            logger.info(f"验证码识别结果: {result}")
            return result
        except Exception as e:
            logger.error(f"验证码识别失败: {e}")
            raise

    def solve_image_base64(self, base64_data: str) -> str:
        """识别 base64 编码的图形验证码"""
        image_data = base64.b64decode(base64_data)
        return self.solve_image(image_data)

    def solve_slider(self, bg_image: bytes, slider_image: bytes) -> int:
        """
        滑块验证码：计算滑动距离
        :param bg_image: 背景图二进制
        :param slider_image: 滑块图二进制
        :return: 滑动距离（像素）
        """
        try:
            import cv2
            import numpy as np

            bg = cv2.imdecode(np.frombuffer(bg_image, np.uint8), cv2.IMREAD_COLOR)
            slider = cv2.imdecode(np.frombuffer(slider_image, np.uint8), cv2.IMREAD_COLOR)

            bg_gray = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
            slider_gray = cv2.cvtColor(slider, cv2.COLOR_BGR2GRAY)

            # 边缘检测
            bg_edge = cv2.Canny(bg_gray, 100, 200)
            slider_edge = cv2.Canny(slider_gray, 100, 200)

            # 模板匹配
            result = cv2.matchTemplate(bg_edge, slider_edge, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            distance = max_loc[0]
            logger.info(f"滑块距离计算: {distance}px (置信度: {max_val:.2f})")
            return distance

        except ImportError:
            logger.warning("opencv-python 未安装，滑块验证码识别不可用")
            raise RuntimeError("需要安装 opencv-python: pip install opencv-python")
        except Exception as e:
            logger.error(f"滑块验证码计算失败: {e}")
            raise

    def get_captcha_image_html(self, image_data: bytes, fmt: str = 'png') -> str:
        """
        将验证码图片转为 base64 HTML img 标签（用于手动输入降级场景）
        """
        b64 = base64.b64encode(image_data).decode('utf-8')
        return f'data:image/{fmt};base64,{b64}'
