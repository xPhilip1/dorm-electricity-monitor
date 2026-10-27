"""
建桥电费监控 一键授权工具 v4 (完整链路)

流程:
  阶段1: 学号密码登录学校统一身份认证(含点选验证码)
  阶段2: 自动跳转"普通宿舍充电"商品页 -> 触发支付宝网页授权
         -> 你用【支付宝App扫一次二维码】确认
  完成:  自动捕获 aliUserId + 常工电控系统会话 + H5 全部接口记录
         保存到 logs/gench_session.json 与 logs/gench_oauth_requests.json

之后电费查询全自动, 无需再扫码(除非会话过期, 届时重跑本工具)。
"""
import json
import os
import re
import time
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(BASE_DIR, 'logs')
STATE_FILE = os.path.join(LOGS, 'gench_session.json')
REQ_FILE = os.path.join(LOGS, 'gench_oauth_requests.json')
SSO_URL = 'https://my.gench.edu.cn/gench.paycenter/portal/home'
PRODUCT_URL = ('https://pay.gench.edu.cn/gench.paycenter/portal/ProductDetail'
               '?productId=4299&orgId=gench-ali')
TIMEOUT_MINUTES = 20

records = []


def main():
    os.makedirs(LOGS, exist_ok=True)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=False, channel='msedge')
            print('浏览器: Edge')
        except Exception:
            browser = p.chromium.launch(headless=False)
            print('浏览器: Chromium')

        context = browser.new_context(
            viewport={'width': 480, 'height': 900},
            ignore_https_errors=True,
            user_agent=('Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 '
                        '(KHTML, like Gecko) Chrome/126.0.0.0 Mobile Safari/537.36'),
        )
        page = context.new_page()

        def on_response(resp):
            try:
                req = resp.request
                url = req.url
                item = {'ts': time.strftime('%H:%M:%S'), 'method': req.method,
                        'url': url, 'status': resp.status, 'post_data': req.post_data,
                        'resp_body': None}
                try:
                    ct = resp.headers.get('content-type', '')
                    if any(x in ct for x in ('json', 'text', 'html')):
                        item['resp_body'] = resp.text()[:4000]
                except Exception:
                    pass
                records.append(item)
            except Exception:
                pass

        page.on('response', on_response)

        # ---------- 阶段1: SSO 登录 ----------
        print('打开统一身份认证...')
        page.goto(SSO_URL, timeout=60000)
        print()
        print('=' * 60)
        print('阶段1: 请在弹出的窗口登录学校统一身份认证')
        print('(学号密码+点选验证码, 或扫码)')
        print('=' * 60)

        sso_ok = False
        deadline = time.time() + 15 * 60
        while time.time() < deadline:
            try:
                r = context.request.get(
                    'https://my.gench.edu.cn/gench.paycenter/api/Product/detail?id=4299',
                    timeout=8000)
                if r.status == 200 and r.json().get('success'):
                    sso_ok = True
                    break
            except Exception:
                pass
            time.sleep(2)
        if not sso_ok:
            print('!! SSO 登录超时')
            browser.close()
            sys.exit(1)
        print('>> SSO 登录成功!\n')

        # ---------- 阶段2: 支付宝授权 ----------
        print('=' * 60)
        print('阶段2: 即将打开"普通宿舍充电"页面, 会跳到支付宝授权')
        print('>>> 请用【支付宝App】扫描屏幕上的二维码并确认 <<<')
        print('      (如直接显示授权页, 点同意即可)')
        print('=' * 60)
        try:
            page.goto(PRODUCT_URL, timeout=60000)
        except Exception as e:
            print(f'(页面跳转提示: {e})')

        ali_user_id = None
        oauth_done = False
        deadline = time.time() + 10 * 60
        last_notice = 0
        while time.time() < deadline:
            # 从任何请求/跳转 URL 中抓真实 aliUserId(2088 开头)
            for it in records[-30:]:
                m = re.search(r'[?&]aliUserId=(2088\w{8,24})', it['url'])
                if m:
                    ali_user_id = m.group(1)
                    oauth_done = True
                    break
                # 常工系统落地的成功页面
                if 'changgongdiankong' in it['url'] and it['status'] == 200 \
                        and 'msg=' not in it['url']:
                    oauth_done = True
            if oauth_done:
                break
            if time.time() - last_notice > 20:
                try:
                    print(f'等待支付宝授权中... 当前页面: {page.url[:80]}')
                except Exception:
                    pass
                last_notice = time.time()
            time.sleep(1)

        # 授权成功后再让 H5 跑几秒, 记录它的数据接口
        time.sleep(8)

        context.storage_state(path=STATE_FILE)
        with open(REQ_FILE, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        try:
            page.screenshot(path=os.path.join(LOGS, 'gench_final_page.png'))
        except Exception:
            pass
        browser.close()

    print()
    if ali_user_id:
        print(f'>> 捕获到 aliUserId: {ali_user_id}')
        # 追加保存 aliUserId
        with open(STATE_FILE, encoding='utf-8') as f:
            state = json.load(f)
        state['aliUserId'] = ali_user_id
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    else:
        print('!! 未捕获到 aliUserId (如果页面已进入充值页面, 授权可能已完成,')
        print('   接口记录已保存, 可继续分析 logs/gench_oauth_requests.json)')

    n_xhr = sum(1 for r in records if r['method'] != 'GET' or 'json' in str(r))
    print(f'共记录 {len(records)} 条请求 -> {REQ_FILE}')
    print(f'浏览器会话 -> {STATE_FILE}')
    print('\n常工电控系统的请求(后 20 条):')
    for it in records[-20:]:
        if 'changgongdiankong' in it['url'] or 'alipay' in it['url']:
            print(f"  [{it['ts']}] {it['method']} {it['status']} {it['url'][:100]}")


if __name__ == '__main__':
    main()
