"""
支付宝 aliUserId 抓取工具 v2

用法:
  python tools/capture_ali_user_id.py              # 抓取并自动写入 config.yaml
  python tools/capture_ali_user_id.py --no-save    # 只抓取, 不写入配置

依赖:
  pip install playwright
  playwright install chromium

流程:
  1. 打开学校 SSO 登录页, 用户完成学号登录
  2. 打开充值页面, 显示支付宝授权链接
  3. 用户复制链接, 在手机支付宝中打开并完成授权
  4. 授权后支付宝跳转到常工系统, URL 中包含 aliUserId
  5. 用户复制跳转后的 URL 粘贴到终端, 脚本自动提取 aliUserId
"""
import os
import sys
import re
import time


def find_project_root():
    """从脚本位置往上找, 直到找到 config/config.yaml"""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        if os.path.isfile(os.path.join(d, 'config', 'config.yaml')):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.getcwd()


def extract_ali_user_id_from_url(url):
    """从 URL 中提取 aliUserId"""
    if not url:
        return None
    m = re.search(r'[?&]aliUserId=(2088\w{8,24})', url)
    if m:
        return m.group(1)
    return None


def main():
    no_save = '--no-save' in sys.argv

    print('=' * 60)
    print('  支付宝 aliUserId 抓取工具 v2')
    print('  (上海建桥学院 - 常工电控)')
    print('=' * 60)
    print()

    # --- 检查 Playwright ---
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('[错误] 未安装 Playwright, 请先执行:')
        print('  pip install playwright')
        print('  playwright install chromium')
        input('\n按回车退出...')
        return

    # --- URL 配置 ---
    SSO_URL = 'https://my.gench.edu.cn/gench.paycenter/portal/home'
    PRODUCT_URL = (
        'https://pay.gench.edu.cn/gench.paycenter/portal/ProductDetail'
        '?productId=4299&orgId=gench-ali'
    )

    with sync_playwright() as p:
        # 启动浏览器
        print('正在启动浏览器...')
        try:
            browser = p.chromium.launch(headless=False, channel='msedge')
            print('      使用 Microsoft Edge')
        except Exception:
            try:
                browser = p.chromium.launch(headless=False, channel='chrome')
                print('      使用 Google Chrome')
            except Exception:
                browser = p.chromium.launch(headless=False)
                print('      使用 Playwright Chromium')

        # 模拟手机环境
        context = browser.new_context(
            viewport={'width': 480, 'height': 900},
            ignore_https_errors=True,
            user_agent=(
                'Mozilla/5.0 (Linux; Android 14; Pixel 8) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/126.0.0.0 Mobile Safari/537.36'
            ),
        )
        page = context.new_page()

        # --- 阶段1: 学校 SSO 登录 ---
        print()
        print('[步骤 1/4] 请在浏览器中登录学校统一身份认证')
        print('           (输入学号、密码、验证码)')
        print()
        page.goto(SSO_URL, timeout=60000)

        input('           登录完成后, 回到这里按回车继续...')
        print()
        print('           学校登录成功!')
        print()

        # --- 阶段2: 打开充值页面, 获取支付宝授权链接 ---
        print('[步骤 2/4] 正在打开充值页面...')
        try:
            page.goto(PRODUCT_URL, timeout=30000)
            time.sleep(2)
        except Exception:
            pass

        # 获取当前页面显示的授权链接
        auth_url = page.url
        print()
        print('[步骤 3/4] 请在手机支付宝中完成授权')
        print()
        print('           方法 A: 如果页面显示二维码')
        print('             -> 用支付宝 App 扫描二维码')
        print()
        print('           方法 B: 如果页面显示"请在支付宝客户端打开"')
        print('             -> 复制地址栏的链接')
        print('             -> 打开手机支付宝, 在搜索框粘贴链接并搜索')
        print('             -> 完成授权')
        print()
        print('           授权完成后, 支付宝会跳转到常工系统页面')
        print('           请复制跳转后的完整 URL (地址栏的链接)')
        print()
        
        redirected_url = input('           粘贴跳转后的 URL (或直接回车手动输入 aliUserId): ').strip()
        
        ali_user_id = extract_ali_user_id_from_url(redirected_url)
        
        if ali_user_id:
            print(f'           从 URL 中提取到: {ali_user_id}')
        else:
            print()
            print('           未能从 URL 中提取 aliUserId')
            print('           请检查 URL 是否包含 aliUserId=2088...')
            print()
            manual = input('           请直接输入 aliUserId (2088 开头): ').strip()
            if re.match(r'^2088\d{8,24}$', manual):
                ali_user_id = manual
                print(f'           使用手动输入: {ali_user_id}')

        browser.close()

    # --- 结果 ---
    print()
    print('=' * 60)
    if ali_user_id:
        print(f'  抓取成功!  aliUserId = {ali_user_id}')
        print('=' * 60)
        print()

        if not no_save:
            root = find_project_root()
            
            # 写入 config.yaml
            cfg_path = os.path.join(root, 'config', 'config.yaml')
            if os.path.isfile(cfg_path):
                try:
                    import yaml
                    with open(cfg_path, encoding='utf-8') as f:
                        cfg = yaml.safe_load(f) or {}
                    if not cfg.get('changgong'):
                        cfg['changgong'] = {}
                    cfg['changgong']['ali_user_id'] = ali_user_id
                    with open(cfg_path, 'w', encoding='utf-8') as f:
                        yaml.dump(cfg, f, default_flow_style=False,
                                  allow_unicode=True, sort_keys=False)
                    print(f'  已写入配置文件: {cfg_path}')
                except Exception as e:
                    print(f'  写入配置失败: {e}')
                    print(f'  请手动填入 config.yaml:')
                    print(f'    changgong:')
                    print(f'      ali_user_id: "{ali_user_id}"')
            else:
                print(f'  未找到 config.yaml, 请手动创建并填入:')
                print(f'    changgong:')
                print(f'      ali_user_id: "{ali_user_id}"')

            # 写入 SQLite 数据库
            db_path = os.path.join(root, 'data', 'dorm_electricity.db')
            if os.path.isfile(db_path):
                try:
                    import sqlite3
                    conn = sqlite3.connect(db_path)
                    cur = conn.cursor()
                    cur.execute('SELECT id, username FROM users LIMIT 1')
                    row = cur.fetchone()
                    if row:
                        user_id, username = row
                        cur.execute(
                            'UPDATE users SET alipay_token = ? WHERE id = ?',
                            (ali_user_id, user_id))
                        conn.commit()
                        print(f'  已写入数据库: users.alipay_token = {ali_user_id}')
                    else:
                        print('  数据库中暂无用户记录, 请先在 Web 界面创建用户')
                    conn.close()
                except Exception as e:
                    print(f'  写入数据库失败: {e}')
            else:
                print(f'  未找到数据库: {db_path}')
        else:
            print('  (--no-save 模式, 不写入配置文件)')
    else:
        print('  未获取到 aliUserId')
        print('=' * 60)
        print()
        print('  提示: aliUserId 是 2088 开头的 16 位数字')

    print()
    input('按回车退出...')


if __name__ == '__main__':
    main()
