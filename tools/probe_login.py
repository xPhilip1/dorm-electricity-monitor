"""
探测建桥统一身份认证(FAP5.IdentityServer)的登录接口:
打开登录页 -> 填假账号提交 -> 记录整个过程的网络请求
"""
import json
import os
import time

from playwright.sync_api import sync_playwright

OUT = os.path.join('logs', 'gench_login_probe.json')
records = []

FAKE_USER = 'probe_test_001'
FAKE_PWD = 'ProbeTest#12345'


def main():
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, channel='msedge')
        except Exception:
            browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={'width': 1280, 'height': 800},
                                  ignore_https_errors=True)
        page = ctx.new_page()

        def on_response(resp):
            try:
                req = resp.request
                if req.resource_type not in ('xhr', 'fetch', 'document', 'redirect'):
                    return
                item = {
                    'ts': time.strftime('%H:%M:%S'),
                    'type': req.resource_type,
                    'method': req.method,
                    'url': req.url,
                    'status': resp.status,
                    'post_data': req.post_data,
                    'resp_body': None,
                }
                try:
                    ct = resp.headers.get('content-type', '')
                    if 'json' in ct or 'text' in ct:
                        item['resp_body'] = resp.text()[:3000]
                except Exception:
                    pass
                records.append(item)
            except Exception:
                pass

        page.on('response', on_response)

        print('打开缴费中心首页(会跳到统一身份认证)...')
        page.goto('https://my.gench.edu.cn/gench.paycenter/portal/home',
                  timeout=45000, wait_until='networkidle')
        time.sleep(2)
        print('当前URL:', page.url)
        print('页面标题:', page.title())

        # 截图留档
        page.screenshot(path='logs/gench_login_page.png')
        print('截图: logs/gench_login_page.png')

        # 探测登录表单输入框
        inputs = page.locator('input:visible')
        n = inputs.count()
        print(f'可见输入框: {n} 个')
        for i in range(n):
            el = inputs.nth(i)
            print(f'  [{i}] type={el.get_attribute("type")} '
                  f'placeholder={el.get_attribute("placeholder")} '
                  f'name={el.get_attribute("name")} id={el.get_attribute("id")}')

        # 填假账号密码提交
        filled = 0
        for i in range(n):
            el = inputs.nth(i)
            t = (el.get_attribute('type') or '').lower()
            ph = (el.get_attribute('placeholder') or '')
            if t == 'password':
                el.fill(FAKE_PWD)
                filled += 1
            elif t in ('text', 'tel') or '号' in ph or 'user' in ph.lower() or '账号' in ph:
                if filled == 0:
                    el.fill(FAKE_USER)
        print(f'已填入假凭据, 尝试提交...')

        # 找登录按钮
        btn = page.locator('button:has-text("登 录"), button:has-text("登录"), '
                           'input[type=submit], a:has-text("登录"), '
                           'button:has-text("Sign"), .login-btn').first
        try:
            btn.click(timeout=5000)
        except Exception:
            page.keyboard.press('Enter')
        time.sleep(5)

        page.screenshot(path='logs/gench_login_after.png')
        print('提交后URL:', page.url)

        browser.close()

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    print(f'\n共记录 {len(records)} 条请求 -> {OUT}')
    for r in records:
        if r['type'] in ('xhr', 'fetch'):
            print(f"  [{r['ts']}] {r['method']} {r['status']} {r['url'][:110]}")
            if r['post_data']:
                print(f"      body: {r['post_data'][:200]}")


if __name__ == '__main__':
    main()
