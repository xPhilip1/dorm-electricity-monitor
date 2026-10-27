"""
支付宝·水电充值中心 电费数据抓取器

数据源: 支付宝 → 卡包 → 会员卡 → 上海建桥学院 → 水电充值中心 → 普通宿舍充电

工作模式(config.yaml -> alipay.mode):
  - "api":     直接调用抓包得到的后台接口(推荐, 轻量快速)
  - "browser": Playwright 无头浏览器读取页面(接口带签名/加密时备用)

首次使用前, 请先运行 tools/capture.py 完成一次抓包,
把得到的接口地址 / token 填入 config.yaml 的 alipay 段。
"""
import json
import logging
import os
import re
import time

import requests

logger = logging.getLogger(__name__)

MOBILE_UA = ('Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 '
             '(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36')


class ChanggongFetcher:
    """
    常工电控(changgongdiankong.gench.edu.cn) 电费余额抓取器
    上海建桥学院 水电费 实际数据源

    流程: GET /auth?aliUserId=<支付宝用户ID> 建立会话
          -> GET /pay/home 服务端渲染页直接解析"剩余购电"
    aliUserId 为 2088 开头的支付宝用户ID, 长期有效(见 tools/gench_login.py 获取方式)
    """

    BASE = 'https://changgongdiankong.gench.edu.cn'

    def query(self, ali_user_id: str) -> dict:
        start = time.time()
        try:
            s = requests.Session()
            s.verify = False
            s.headers.update({'User-Agent': MOBILE_UA})

            r = s.get(f'{self.BASE}/auth', params={'aliUserId': ali_user_id}, timeout=20)
            final = r.url or ''
            if '/msg' in final or 'msg=' in final:
                raise RuntimeError(f'常工系统认证失败(aliUserId 无效或已变更): {final[:120]}')

            r = s.get(f'{self.BASE}/pay/home', timeout=20)
            html = r.text

            def grab(label):
                m = re.search(
                    label + r'</div>\s*<div class="item-after">\s*([\d.]+)\s*度', html)
                return float(m.group(1)) if m else None

            balance = grab('剩余购电')
            if balance is None:
                raise RuntimeError('充值主页中未解析到"剩余购电", 页面结构可能已变化, '
                                   f'页面片段: {html[:200]}')
            subsidy = grab('剩余补助')

            meter_id = room = None
            mm = re.search(r'name="mdInfo" value="(\d+)\|([^"]*)"', html)
            if mm:
                meter_id, room = mm.group(1), mm.group(2).strip()

            logger.info(f'常工电控查询成功: 剩余购电={balance}度, 补助={subsidy}度, '
                        f'房间={room}')
            return {
                'balance': balance,
                'subsidy': subsidy or 0.0,
                'room': room,
                'meter_id': meter_id,
                'usage_today': 0.0,
                'raw': json.dumps({'subsidy': subsidy, 'room': room,
                                   'meter_id': meter_id}, ensure_ascii=False),
                'success': True,
                'duration_ms': int((time.time() - start) * 1000),
            }
        except Exception as e:
            logger.error(f'常工电控查询异常: {e}')
            return {
                'balance': 0.0, 'subsidy': 0.0, 'room': None, 'meter_id': None,
                'usage_today': 0.0, 'raw': str(e), 'success': False,
                'duration_ms': int((time.time() - start) * 1000),
            }


class AlipayElecFetcher:
    """支付宝水电充值中心数据抓取器"""

    def __init__(self, config):
        self.config = config or {}
        self.mode = self.config.get('mode', 'api')

    # ---------- 公共入口 ----------

    def query(self, room: str, token: str = None) -> dict:
        """
        查询宿舍电费
        :param room: 宿舍号
        :param token: 用户级 token(优先); 未提供则用 config 中的全局 token
        :return: {'balance': float, 'usage_today': float, 'success': bool, 'raw': str, 'duration_ms': int}
        """
        start = time.time()
        try:
            if self.mode == 'browser':
                result = self._query_browser(room)
            else:
                result = self._query_api(room, token)
            result.setdefault('duration_ms', int((time.time() - start) * 1000))
            return result
        except Exception as e:
            logger.error(f"电费查询异常: {e}")
            return {
                'balance': 0.0,
                'usage_today': 0.0,
                'raw': str(e),
                'success': False,
                'duration_ms': int((time.time() - start) * 1000)
            }

    # ---------- API 模式 ----------

    def _query_api(self, room, token):
        api_base = self.config.get('api_base', '').rstrip('/')
        query_path = self.config.get('query_path', '')
        if not api_base or not query_path:
            raise RuntimeError("alipay.api_base / query_path 未配置, 请先运行 tools/capture.py 抓包并填写配置")

        url = api_base + query_path
        token = token or self.config.get('auth_token', '')
        headers = {
            'User-Agent': self.config.get(
                'user_agent',
                'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'),
            **self._auth_headers(token),
        }

        # 房间参数: 模板中的 {room} 替换为宿舍号
        params_tpl = self.config.get('room_params', {}) or {}
        params = {k: str(v).format(room=room) for k, v in params_tpl.items()}

        method = self.config.get('method', 'POST').upper()
        if method == 'GET':
            resp = requests.get(url, params=params, headers=headers, timeout=15, verify=False)
        elif self.config.get('body_style') == 'json':
            headers['Content-Type'] = 'application/json'
            resp = requests.post(url, json=params, headers=headers, timeout=15, verify=False)
        else:
            resp = requests.post(url, data=params, headers=headers, timeout=15, verify=False)

        if resp.status_code in (401, 403):
            raise RuntimeError(f"token 可能已过期 (HTTP {resp.status_code}), 请重新运行 tools/capture.py 更新")
        resp.raise_for_status()

        # JSON 响应: 按字段路径提取余额
        try:
            data = resp.json()
        except ValueError:
            # 非 JSON 响应: 从文本中提取数字
            balance = self._parse_number(resp.text)
            if balance is None:
                raise RuntimeError(f"响应既不是 JSON 也解析不出数字: {resp.text[:300]}")
            return {'balance': balance, 'usage_today': 0.0,
                    'raw': resp.text[:2000], 'success': True}

        balance = self._extract_field(data, self.config.get('balance_field', ''))
        if balance is None:
            raise RuntimeError(
                f"未能从响应中提取余额, 请检查 balance_field 配置. 响应: {json.dumps(data, ensure_ascii=False)[:500]}")

        return {'balance': float(balance), 'usage_today': 0.0,
                'raw': json.dumps(data, ensure_ascii=False)[:2000], 'success': True}

    def _auth_headers(self, token):
        """根据 auth_style 构造认证请求头"""
        style = self.config.get('auth_style', 'bearer')
        header_name = self.config.get('auth_header', 'Authorization')
        if not token:
            return {}
        if style == 'bearer':
            return {header_name: f'Bearer {token}'}
        if style == 'cookie':
            return {'Cookie': token}
        return {header_name: token}

    # ---------- 浏览器模式 ----------

    def _query_browser(self, room):
        browser_cfg = self.config.get('browser', {}) or {}
        page_url = browser_cfg.get('page_url', '')
        selector = browser_cfg.get('balance_selector', '')
        if not page_url or not selector:
            raise RuntimeError("alipay.browser.page_url / balance_selector 未配置")

        from playwright.sync_api import sync_playwright

        # 登录态由 tools/capture.py 首次运行时保存
        state_path = os.path.join('logs', 'storage_state.json')
        with sync_playwright() as p:
            # 默认用系统自带 Edge, 可通过 browser.channel 配置(如 "chrome"/"msedge")
            channel = browser_cfg.get('channel', 'msedge')
            try:
                browser = p.chromium.launch(headless=browser_cfg.get('headless', True),
                                            channel=channel)
            except Exception:
                browser = p.chromium.launch(headless=browser_cfg.get('headless', True))
            context = browser.new_context(
                storage_state=state_path if os.path.exists(state_path) else None,
                user_agent=('Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'),
                viewport={'width': 393, 'height': 873},
                is_mobile=True,
            )
            page = context.new_page()
            page.goto(page_url, timeout=30000, wait_until='domcontentloaded')
            page.wait_for_selector(selector, timeout=20000)
            text = page.inner_text(selector)
            browser.close()

        balance = self._parse_number(text)
        if balance is None:
            raise RuntimeError(f"无法从页面文本解析余额: {text[:200]}")
        return {'balance': balance, 'usage_today': 0.0, 'raw': text[:2000], 'success': True}

    # ---------- 工具方法 ----------

    @staticmethod
    def _extract_field(data, path):
        """按 'a.b.c' 路径从嵌套 JSON 中提取字段值"""
        if not path:
            return None
        cur = data
        for part in path.split('.'):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        if isinstance(cur, (int, float)):
            return float(cur)
        m = re.search(r'[\d.]+', str(cur))
        return float(m.group()) if m else None

    @staticmethod
    def _parse_number(text):
        """从任意文本中提取第一个数字"""
        m = re.search(r'[\d]+\.?\d*', str(text).replace(',', ''))
        return float(m.group()) if m else None
