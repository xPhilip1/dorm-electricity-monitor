"""
支付宝·水电充值中心 抓包辅助工具

作用:
  1. 打开一个手机版视口的浏览器窗口, 你在里面手动走一遍查询流程
     (支付宝 → 卡包 → 会员卡 → 上海建桥学院 → 水电充值中心 → 普通宿舍充电)
  2. 工具实时记录所有 XHR/Fetch 请求, 保存到 logs/capture_requests.json
     从中可找到"查询电费"的接口地址 / 请求参数 / token
  3. 关闭浏览器时自动保存登录状态到 logs/storage_state.json
     (browser 模式会复用这份登录态)

用法:
  python tools/capture.py [起始URL]

首次安装(只需一次):
  pip install playwright
  playwright install chromium

提示:
  - 如果支付宝页面在普通浏览器里打不开或提示在支付宝内打开,
    改用手机抓包: 手机装 Charles/Fiddler 抓 HTTPS 包, 同样能拿到
    接口地址和 token, 然后手动填入 config.yaml。
"""
import json
import os
import sys
from datetime import datetime

from playwright.sync_api import sync_playwright

CAPTURE_FILE = os.path.join('logs', 'capture_requests.json')
STATE_FILE = os.path.join('logs', 'storage_state.json')

MOBILE_UA = ('Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 '
             '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36')


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else 'https://www.alipay.com/'
    os.makedirs('logs', exist_ok=True)

    records = []

    def on_response(response):
        try:
            req = response.request
            # 只记录接口类请求(过滤图片/脚本/样式等静态资源)
            if req.resource_type not in ('xhr', 'fetch'):
                return
            item = {
                'time': datetime.now().strftime('%H:%M:%S'),
                'method': req.method,
                'url': req.url,
                'post_data': req.post_data,
                'status': response.status,
                'response': None,
            }
            try:
                ct = response.headers.get('content-type', '')
                if 'json' in ct:
                    item['response'] = response.json()
            except Exception:
                pass
            records.append(item)
            print(f"[{item['time']}] {req.method} {response.status} {req.url[:120]}")
        except Exception as e:
            print(f"记录请求失败: {e}")

    with sync_playwright() as p:
        # 优先用系统自带的 Edge(无需 playwright install), 失败再退回 Chromium
        try:
            browser = p.chromium.launch(headless=False, channel="msedge")
            print("使用浏览器: Microsoft Edge")
        except Exception:
            browser = p.chromium.launch(headless=False)
            print("使用浏览器: Chromium")
        context = browser.new_context(
            user_agent=MOBILE_UA,
            viewport={'width': 393, 'height': 873},
            is_mobile=True,
            has_touch=True,
        )
        page = context.new_page()
        page.on('response', on_response)

        print(f"正在打开: {url}\n")
        print("=" * 60)
        print("请在浏览器中手动完成一次电费查询,")
        print("完成后直接关闭浏览器窗口, 工具会自动保存结果。")
        print("=" * 60 + "\n")

        page.goto(url, timeout=60000)
        page.wait_for_event('close', timeout=0)  # 等待用户关闭页面, 0 表示不限时

        context.storage_state(path=STATE_FILE)
        browser.close()

    with open(CAPTURE_FILE, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"\n共记录 {len(records)} 条接口请求 -> {CAPTURE_FILE}")
    print(f"登录状态已保存 -> {STATE_FILE}")
    print()
    print("下一步:")
    print("  1. 打开 logs/capture_requests.json, 搜索关键词如")
    print("     余额/电量/surplus/balance/elec/room, 找到查询接口那条记录")
    print("  2. 把它的 URL 拆成 api_base + query_path 填入 config.yaml")
    print("  3. 把请求头中的 token/Cookie 填入 alipay.auth_token")
    print("  4. 对照响应 JSON 确认余额字段路径, 填入 alipay.balance_field")


if __name__ == '__main__':
    main()
