import os
import sys
import logging
from logging.handlers import RotatingFileHandler

import yaml
from flask import Flask

from app.models import db
from app.auth import login_manager
from app.routes import register_routes, monitor_instance


def _default_config_path():
    """配置文件路径: 打包(exe)模式优先读 exe 旁边的 config/config.yaml(用户可编辑),
    否则用源码目录下的"""
    if getattr(sys, 'frozen', False):
        external = os.path.join(os.path.dirname(sys.executable), 'config', 'config.yaml')
        if os.path.exists(external):
            return external
    return os.path.join(os.path.dirname(__file__), '..', 'config', 'config.yaml')


def create_app(config_path=None):
    """应用工厂"""
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), '..', 'templates'),
        static_folder=os.path.join(os.path.dirname(__file__), '..', 'static')
    )

    # 加载配置
    if config_path is None:
        config_path = _default_config_path()

    with open(config_path, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)

    app.config['SECRET_KEY'] = cfg.get('server', {}).get('secret_key', 'dev-secret-key')

    # 数据库配置
    db_cfg = cfg.get('database', {})
    db_type = db_cfg.get('type', 'sqlite')

    if db_type == 'sqlite':
        # SQLite: 数据库文件放在 exe 旁边或项目根目录的 data/ 文件夹
        db_path = db_cfg.get('path', 'data/dorm_electricity.db')
        if getattr(sys, 'frozen', False):
            db_full_path = os.path.join(os.path.dirname(sys.executable), db_path)
        else:
            db_full_path = os.path.join(os.path.dirname(__file__), '..', db_path)
        os.makedirs(os.path.dirname(db_full_path), exist_ok=True)
        db_uri = f'sqlite:///{db_full_path}'
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {}
    else:
        # MySQL
        db_uri = (
            f"mysql+pymysql://{db_cfg.get('user')}:{db_cfg.get('password')}"
            f"@{db_cfg.get('host')}:{db_cfg.get('port')}/{db_cfg.get('name')}"
            f"?charset={db_cfg.get('charset', 'utf8mb4')}"
        )
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_size': 5,
            'pool_recycle': 3600,
            'pool_pre_ping': True
        }

    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # 存储完整配置供其他模块使用
    app.config['APP_CONFIG'] = cfg

    # 初始化扩展
    db.init_app(app)
    login_manager.init_app(app)

    # 注册路由
    register_routes(app)

    # 日志配置
    _setup_logging(app, cfg)

    return app


def _setup_logging(app, cfg):
    log_cfg = cfg.get('logging', {})
    log_level = getattr(logging, log_cfg.get('level', 'INFO'))
    log_file = log_cfg.get('file', 'logs/app.log')

    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    handler = RotatingFileHandler(
        log_file,
        maxBytes=log_cfg.get('max_size_mb', 10) * 1024 * 1024,
        backupCount=log_cfg.get('backup_count', 5),
        encoding='utf-8'
    )
    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    ))

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(handler)

    # 控制台也输出
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s'
    ))
    root_logger.addHandler(console)
