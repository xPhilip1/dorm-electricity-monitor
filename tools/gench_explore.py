"""
用已保存的会话探测建桥缴费中心的电费查询接口

前置: 先运行 python tools/gench_login.py 完成一次登录
用法:  python tools/gench_explore.py [productId]
输出:  logs/gench_explore_result.json + 终端摘要
"""
import json
import os
import sys

import requests
import urllib3

urllib3.disable_warnings()

BASE = 'https://my.gench.edu.cn'
STATE_FILE = os.path.join('logs', 'gench_session.json')
OUT_FILE = os.path.join('logs', 'gench_explore_result.json')


def build_session():
    s = requests.Session()
    s.verify = False
    with open(STATE_FILE, encoding='utf-8') as f:
        state = json.load(f)
    for c in state.get('cookies', []):
        s.cookies.set(
            c['name'], c['value'],
            domain=c.get('domain', '').lstrip('.'),
            path=c.get('path', '/'),
        )
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Referer': f'{BASE}/gench.paycenter/portal/home',
        'X-Requested-With': 'XMLHttpRequest',
    })
    return s


def check_login(s):
    """未登录时该接口返回 errorCode=UnAuthorizePayUser"""
    r = s.get(f'{BASE}/gench.paycenter/api/Product/paymentContext',
              params={'productId': 4299}, timeout=20)
    print(f'[登录检查] paymentContext -> HTTP {r.status_code}')
    try:
        data = r.json()
        ok = data.get('errorCode') != 'UnAuthorizePayUser'
        print(f'    success={data.get("success")}, errorCode={data.get("errorCode")}, '
              f'message={data.get("message")}')
        return ok, data
    except ValueError:
        print(f'    非 JSON 响应(可能被重定向到登录页): {r.url[:90]}')
        return False, None


def main():
    if not os.path.exists(STATE_FILE):
        print('未找到会话文件, 请先运行: python tools/gench_login.py')
        sys.exit(1)

    s = build_session()
    result = {}

    ok, menus = check_login(s)
    result['allMenus'] = menus
    if not ok:
        print('!! 会话无效/已过期, 请重新运行 gench_login.py')
        with open(OUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        sys.exit(2)

    # 1) 商品列表
    for path, params_key in [('Product/list', None), ('Product/dict', None)]:
        r = s.get(f'{BASE}/gench.paycenter/api/{path}', timeout=20)
        print(f'[商品] {path} -> HTTP {r.status_code}')
        try:
            result[path] = r.json()
        except ValueError:
            result[path] = r.text[:2000]

    # 从菜单/商品里挑出候选 productId
    product_ids = []
    try:
        for item in (result.get('Product/list', {}).get('result') or []):
            pid = item.get('id') or item.get('productId')
            name = str(item.get('name') or item.get('productName') or '')
            if pid:
                product_ids.append((pid, name))
    except Exception:
        pass
    if not product_ids:
        try:
            d = result.get('Product/dict', {}).get('result') or {}
            for k, v in (d.items() if isinstance(d, dict) else enumerate(d)):
                product_ids.append((k, str(v)))
        except Exception:
            pass

    print(f'候选 product: {product_ids[:10]}')

    # 2) 对指定或默认 product(普通宿舍充电=4299)拉 detail / paymentContext / canPay
    target = sys.argv[1] if len(sys.argv) > 1 else '4299'
    for host_base in (BASE, 'https://pay.gench.edu.cn'):
        for path in ('Product/detail', 'Product/paymentContext', 'Product/canPay'):
            try:
                r = s.get(f'{host_base}/gench.paycenter/api/{path}',
                          params={'productId': target, 'orgId': 'gench-ali'}, timeout=20)
                print(f'[{host_base.split("//")[1]}] {path} -> HTTP {r.status_code}')
                try:
                    result[f'{host_base}/{path}@{target}'] = r.json()
                except ValueError:
                    result[f'{host_base}/{path}@{target}'] = r.text[:2000]
            except Exception as e:
                print(f'[{host_base}] {path} -> ERROR {e}')

    with open(OUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f'\n完整结果 -> {OUT_FILE}')


if __name__ == '__main__':
    main()
