"""
桌面版启动器(供 PyInstaller 打包为 exe)

启动流程:
  1. 确保数据目录存在 (SQLite 自动创建数据库文件, 无需外部数据库)
  2. 抓取支付宝 aliUserId → 打开浏览器登录SSO, 自动捕获并保存
  3. 启动 Flask 服务, 打开浏览器进入登录/仪表盘
"""
import os
import sys
import re
import json
import shutil
import time
import atexit
import signal
import subprocess
import threading
import webbrowser
import ctypes


def base_dir():
    """exe 所在目录(打包后) 或 项目根目录(源码运行)"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def kill_port_processes(port):
    """杀掉所有占用指定端口的进程, 防止旧实例残留"""
    try:
        result = subprocess.run(
            f'netstat -ano | findstr ":{port}" | findstr "LISTENING"',
            shell=True, capture_output=True, text=True, timeout=10)
        pids = set()
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if parts:
                pid = parts[-1]
                if pid.isdigit() and int(pid) != os.getpid():
                    pids.add(pid)
        for pid in pids:
            try:
                subprocess.run(f'taskkill //F //PID {pid}',
                               shell=True, capture_output=True, timeout=5)
            except Exception:
                pass
        if pids:
            print(f'已清理 {len(pids)} 个占用端口 {port} 的旧进程')
            time.sleep(1)  # 等待端口释放
    except Exception:
        pass


def _cleanup_on_exit():
    """程序退出时清理, 确保端口释放"""
    try:
        # 杀掉当前进程的所有子进程
        subprocess.run(
            f'taskkill //F //PID {os.getpid()} //T',
            shell=True, capture_output=True, timeout=5)
    except Exception:
        pass


# 注册退出清理
atexit.register(_cleanup_on_exit)

# Windows 控制台关闭事件处理
def _console_handler(ctrl_type):
    """处理 Ctrl+C / 控制台关闭事件"""
    _cleanup_on_exit()
    return True

try:
    ctypes.windll.kernel32.SetConsoleCtrlHandler(
        ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)(_console_handler), 1)
except Exception:
    pass


def fatal(msg):
    """无控制台模式下, 用消息框报告致命错误"""
    try:
        ctypes.windll.user32.MessageBoxW(0, msg, '宿舍电费监控 - 启动失败', 0x10)
    except Exception:
        pass
    sys.exit(1)


def msgbox(msg, title='宿舍电费监控', style=0):
    """弹出 Windows 消息框"""
    try:
        return ctypes.windll.user32.MessageBoxW(0, msg, title, style)
    except Exception:
        return 0


# ============================================================
#  步骤1: 确保数据目录存在 (SQLite 模式)
# ============================================================

def ensure_data_dir(root):
    """SQLite 模式下确保 data/ 目录存在, 返回 (True, 消息)"""
    import yaml
    cfg_path = os.path.join(root, 'config', 'config.yaml')
    with open(cfg_path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    db_cfg = cfg.get('database', {})
    db_type = db_cfg.get('type', 'sqlite')

    if db_type == 'sqlite':
        db_path = db_cfg.get('path', 'data/dorm_electricity.db')
        data_dir = os.path.join(root, os.path.dirname(db_path))
        os.makedirs(data_dir, exist_ok=True)
        return True, f'SQLite 数据目录: {data_dir}'
    else:
        # MySQL 模式: 仅做基本连接检查
        return _check_mysql_connection(db_cfg)


def _check_mysql_connection(db_cfg):
    """MySQL 模式下的连接检查, 返回 (成功bool, 消息str)"""
    try:
        import pymysql
        db_name = str(db_cfg.get('name', '')).strip()
        if not db_name:
            return False, '数据库名称未配置'
        conn = pymysql.connect(
            host=str(db_cfg.get('host', '127.0.0.1')),
            port=int(db_cfg.get('port', 3306)),
            user=str(db_cfg.get('user', 'root')),
            password=str(db_cfg.get('password', '')),
            charset='utf8mb4', connect_timeout=5,
        )
        with conn.cursor() as c:
            c.execute(f"SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='{db_name}'")
            exists = c.fetchone() is not None
        conn.close()
        if exists:
            return True, f'数据库 [{db_name}] 连接正常'
        else:
            return True, f'连接成功, 数据库 [{db_name}] 将在启动时自动创建'
    except Exception as e:
        return False, str(e)


# ============================================================
#  步骤2: 抓取支付宝 aliUserId
# ============================================================

def get_ali_user_id(root):
    """从 config.yaml 读取已保存的 aliUserId"""
    import yaml
    cfg_path = os.path.join(root, 'config', 'config.yaml')
    with open(cfg_path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    val = (cfg.get('changgong') or {}).get('ali_user_id', '')
    return str(val).strip() if val else ''


def save_ali_user_id(root, ali_user_id):
    """将 aliUserId 写入 config.yaml"""
    import yaml
    cfg_path = os.path.join(root, 'config', 'config.yaml')
    with open(cfg_path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    if 'changgong' not in cfg or cfg['changgong'] is None:
        cfg['changgong'] = {}
    cfg['changgong']['ali_user_id'] = ali_user_id
    with open(cfg_path, 'w', encoding='utf-8') as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def launch_capture_tool(root):
    """
    启动 aliUserId 授权工具 v2 (Flask Web 界面 + QR 码)。
    用户扫码 → 支付宝登录 → 粘贴 URL → 保存 aliUserId → 工具自动关闭。
    返回 (成功bool, aliUserId或None)
    """
    tool = os.path.join(root, 'tools', 'capture_ali_user_id_v2.py')
    if not os.path.exists(tool):
        msgbox(f'找不到授权工具:\n{tool}', 'aliUserId 授权')
        return False, None

    # 冻结模式下 sys.executable 指向 exe 自身, 必须改用系统 Python 解释器
    if getattr(sys, 'frozen', False):
        python_exe = shutil.which('python') or shutil.which('python3') or shutil.which('py')
        if not python_exe:
            msgbox('未找到系统 Python 解释器, 无法启动授权工具。\n\n'
                   '请在"个人设置"中手动填写 aliUserId。',
                   '宿舍电费监控 - 缺少 Python', 0x30)
            return False, None
    else:
        python_exe = sys.executable

    cmd = f'start "aliUserId 授权" "{python_exe}" "{tool}"'
    proc = subprocess.call(cmd, shell=True)

    # 工具关闭后, 重新读取 aliUserId
    ali_user_id = get_ali_user_id(root)
    if ali_user_id:
        msgbox(f'aliUserId 已保存!\n\n{ali_user_id}\n\n'
               f'程序将自动使用此 ID 查询电费。',
               '宿舍电费监控 - 授权完成', 0x40)
        return True, ali_user_id
    else:
        msgbox('尚未完成授权。\n你可以在"个人设置"中手动填写 aliUserId。',
               '宿舍电费监控', 0x30)
        return False, None


# ============================================================
#  主流程
# ============================================================

def main():
    # 校园网自签名证书会触发警告, 抑制之
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    autostart = '--autostart' in sys.argv
    root = base_dir()
    os.chdir(root)
    os.makedirs('logs', exist_ok=True)

    # 首次运行: 释放内置配置和工具到 exe 旁边
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        cfg_external = os.path.join(root, 'config', 'config.yaml')
        if not os.path.exists(cfg_external):
            bundled = os.path.join(meipass, 'config')
            if os.path.isdir(bundled):
                shutil.copytree(bundled, os.path.join(root, 'config'), dirs_exist_ok=True)
        # 工具脚本也需要释放出来(供子进程调用)
        tools_external = os.path.join(root, 'tools')
        bundled_tools = os.path.join(meipass, 'tools')
        if os.path.isdir(bundled_tools):
            shutil.copytree(bundled_tools, tools_external, dirs_exist_ok=True)

    # ----------------------------------------------------------
    #  步骤1: 确保数据目录存在 (SQLite 自动创建数据库文件)
    # ----------------------------------------------------------
    db_ok, db_msg = ensure_data_dir(root)
    if not db_ok:
        msgbox(f'数据库准备失败:\n\n{db_msg}\n\n请检查 config/config.yaml 中的 database 配置。',
               '宿舍电费监控 - 数据库配置', 0x30)
        fatal('数据库配置未完成, 无法启动。')
        return

    # ----------------------------------------------------------
    #  步骤2: 抓取支付宝 aliUserId (没有才抓)
    # ----------------------------------------------------------
    ali_user_id = get_ali_user_id(root)
    if not ali_user_id:
        msgbox('尚未配置支付宝用户ID。\n即将打开抓取工具, 请配合完成操作。',
               '宿舍电费监控 - 支付宝授权', 0x40)
        launch_capture_tool(root)

    # ----------------------------------------------------------
    #  步骤3: 启动 Flask 服务
    # ----------------------------------------------------------
    try:
        from app import create_app
        from app.models import db
        from app.monitor import Monitor
        import app.routes as routes_module
    except Exception as e:
        fatal(f'程序初始化失败:\n{e}')
        return

    try:
        app = create_app()
    except Exception as e:
        fatal(f'读取配置失败, 请检查 config/config.yaml:\n{e}')
        return

    url = None
    try:
        with app.app_context():
            db.create_all()

            from app.models import User
            if not User.query.first():
                admin = User(username='admin', role='admin', dorm_room='0-000')
                admin.set_password('admin123')
                db.session.add(admin)
                db.session.commit()

            monitor = Monitor(app, app.config['APP_CONFIG'])
            routes_module.monitor_instance = monitor
            monitor.start()

        cfg = app.config['APP_CONFIG']['server']
        host = cfg.get('host', '127.0.0.1')
        port = int(cfg.get('port', 5000))
        url = f'http://{host}:{port}'

        # 启动前清理占用该端口的旧进程
        kill_port_processes(port)

        if not autostart:
            threading.Timer(2.0, lambda: webbrowser.open(url)).start()

        print('=' * 50)
        print('宿舍电费监控系统已启动' + ('(开机自启)' if autostart else ''))
        print(f'地址: {url}' + ('' if autostart else '  (浏览器将自动打开)'))
        print('=' * 50)

        app.run(host=host, port=port, debug=False, use_reloader=False)
    except OSError as e:
        fatal(f'服务启动失败(端口可能被占用, 或已有实例在运行):\n{e}\n\n'
              f'若已在运行, 直接访问 {url or "http://127.0.0.1:5000"}')
    except Exception as e:
        import traceback
        _log_path = os.path.join(root, 'logs', 'startup_error.log')
        os.makedirs(os.path.dirname(_log_path), exist_ok=True)
        with open(_log_path, 'w', encoding='utf-8') as _f:
            _f.write(traceback.format_exc())
        fatal(f'运行出错:\n{e}\n\n详细日志: {_log_path}')


if __name__ == '__main__':
    main()
