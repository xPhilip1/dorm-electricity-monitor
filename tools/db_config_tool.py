"""
数据库配置修改工具

用法:
  python tools/db_config_tool.py              # 交互式修改
  python tools/db_config_tool.py --show       # 仅查看当前配置
  python tools/db_config_tool.py --test       # 仅测试当前连接
  python tools/db_config_tool.py --reset      # 恢复默认配置(127.0.0.1 / root / 空密码)
"""
import os
import sys
import copy

# 让脚本在源码运行 / PyInstaller 打包后 / 被外部调用时都能定位项目根目录
if '--root' in sys.argv:
    BASE_DIR = sys.argv[sys.argv.index('--root') + 1]
elif getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(BASE_DIR, 'config', 'config.yaml')

# 移除 --root 参数, 避免干扰后续参数解析
if '--root' in sys.argv:
    idx = sys.argv.index('--root')
    sys.argv.pop(idx)
    if idx < len(sys.argv):
        sys.argv.pop(idx)

# 默认数据库配置
DEFAULTS = {
    'host': '127.0.0.1',
    'port': 3306,
    'user': 'root',
    'password': '',
    'name': 'dorm_electricity',
    'charset': 'utf8mb4',
}

FIELDS = [
    ('host',     '数据库主机',     '127.0.0.1'),
    ('port',     '端口',           '3306'),
    ('user',     '用户名',         'root'),
    ('password', '密码',           '(空)'),
    ('name',     '数据库名',       'dorm_electricity'),
    ('charset',  '字符集',         'utf8mb4'),
]


def load_config():
    """读取 config.yaml，返回 (完整配置dict, database子dict)。失败时退出。"""
    try:
        import yaml
    except ImportError:
        print('!! 缺少 PyYAML，请先 pip install pyyaml')
        sys.exit(1)

    if not os.path.exists(CONFIG_PATH):
        print(f'!! 找不到配置文件: {CONFIG_PATH}')
        sys.exit(1)

    with open(CONFIG_PATH, encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}

    db_cfg = cfg.get('database', {})
    if not db_cfg:
        print('!! config.yaml 中没有 [database] 段，将使用默认值创建')
        db_cfg = dict(DEFAULTS)
        cfg['database'] = db_cfg

    return cfg, db_cfg


def save_config(cfg):
    """写回 config.yaml（保留原有注释和结构，只替换 database 段）。"""
    import yaml

    # 备份旧配置
    backup = CONFIG_PATH + '.bak'
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding='utf-8') as f:
            old_text = f.read()
        with open(backup, 'w', encoding='utf-8') as f:
            f.write(old_text)
        print(f'  旧配置已备份 -> {backup}')

    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f'  配置已保存 -> {CONFIG_PATH}')


def show_db_config(db_cfg):
    """打印当前数据库配置。"""
    print()
    print('=' * 50)
    print('  当前数据库配置')
    print('=' * 50)
    for key, label, _ in FIELDS:
        val = db_cfg.get(key, DEFAULTS.get(key, ''))
        display = val if key != 'password' else ('*' * len(str(val)) if val else '(空)')
        print(f'  {label:12s} ({key:8s}): {display}')
    print('=' * 50)
    print()


def test_connection(db_cfg):
    """测试 MySQL 连接，返回 (成功bool, 消息str)。"""
    try:
        import pymysql
    except ImportError:
        return False, '缺少 PyMySQL，请先 pip install pymysql'

    host = str(db_cfg.get('host', '127.0.0.1'))
    port = int(db_cfg.get('port', 3306))
    user = str(db_cfg.get('user', 'root'))
    password = str(db_cfg.get('password', ''))
    name = str(db_cfg.get('name', 'dorm_electricity'))

    # 第一步：测试基础连接（不指定数据库）
    try:
        conn = pymysql.connect(
            host=host, port=port, user=user, password=password,
            charset='utf8mb4', connect_timeout=5,
        )
        conn.close()
    except pymysql.err.OperationalError as e:
        return False, f'连接 MySQL 失败 ({host}:{port}): {e}'
    except Exception as e:
        return False, f'连接出错: {e}'

    # 第二步：检查数据库是否存在
    try:
        conn = pymysql.connect(
            host=host, port=port, user=user, password=password,
            charset='utf8mb4', connect_timeout=5,
        )
        with conn.cursor() as c:
            c.execute(f"SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='{name}'")
            exists = c.fetchone() is not None
        conn.close()
    except Exception as e:
        return False, f'检查数据库时出错: {e}'

    if exists:
        return True, f'连接成功! 数据库 [{name}] 已存在'
    else:
        return True, f'连接成功! 但数据库 [{name}] 不存在（首次启动时会自动创建）'


def interactive_edit(db_cfg):
    """交互式逐项修改，回车保留原值。"""
    print('逐项修改数据库配置（直接回车保留原值）:\n')
    new_cfg = dict(db_cfg)

    for key, label, default_hint in FIELDS:
        current = db_cfg.get(key, DEFAULTS.get(key, ''))
        if key == 'password':
            display = ('*' * len(str(current)) if current else '(空)')
        else:
            display = current

        prompt = f'  {label} [{display}]: '
        try:
            val = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print('\n(已取消)')
            return None

        if val:
            if key == 'port':
                try:
                    val = int(val)
                    if not (1 <= val <= 65535):
                        raise ValueError
                except ValueError:
                    print(f'    !! 端口必须是 1~65535 的整数，跳过')
                    continue
            new_cfg[key] = val

    return new_cfg


def reset_config():
    """恢复默认数据库配置。"""
    cfg, db_cfg = load_config()
    print('\n将恢复为默认数据库配置:')
    for key, label, default_val in FIELDS:
        db_cfg[key] = DEFAULTS[key] if key != 'port' else int(DEFAULTS[key])
    show_db_config(db_cfg)

    try:
        confirm = input('确认覆盖? (y/N): ').strip().lower()
    except (EOFError, KeyboardInterrupt):
        print('\n(已取消)')
        return

    if confirm == 'y':
        cfg['database'] = db_cfg
        save_config(cfg)
        print('>> 已恢复默认配置')
    else:
        print('(已取消)')


def main():
    # 命令行参数
    if '--reset' in sys.argv:
        reset_config()
        return

    cfg, db_cfg = load_config()

    if '--show' in sys.argv:
        show_db_config(db_cfg)
        return

    if '--test' in sys.argv:
        show_db_config(db_cfg)
        ok, msg = test_connection(db_cfg)
        print(f'  {"OK" if ok else "FAIL"}: {msg}')
        sys.exit(0 if ok else 1)

    # 默认：交互式修改
    print()
    print('=' * 50)
    print('  数据库配置修改工具')
    print('=' * 50)
    show_db_config(db_cfg)

    new_cfg = interactive_edit(db_cfg)
    if new_cfg is None:
        return

    # 显示修改后的配置
    print('\n修改后的配置:')
    show_db_config(new_cfg)

    # 测试连接
    print('正在测试连接...')
    ok, msg = test_connection(new_cfg)
    print(f'  {"OK" if ok else "FAIL"}: {msg}')

    if not ok:
        try:
            force = input('\n连接失败，是否仍要保存? (y/N): ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print('\n(已取消)')
            return
        if force != 'y':
            print('(已放弃保存)')
            return

    try:
        confirm = input('\n确认保存? (y/N): ').strip().lower()
    except (EOFError, KeyboardInterrupt):
        print('\n(已取消)')
        return

    if confirm == 'y':
        cfg['database'] = new_cfg
        save_config(cfg)
        print('\n>> 配置已更新! 重启监控程序后生效。')
    else:
        print('(已放弃保存)')


if __name__ == '__main__':
    main()
