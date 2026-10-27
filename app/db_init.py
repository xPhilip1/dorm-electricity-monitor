"""
数据库初始化脚本
运行方式: python -m app.db_init
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
from app import create_app
from app.models import db, User, SystemConfig


def init_db():
    app = create_app()
    with app.app_context():
        db.create_all()
        print("[OK] 数据表创建成功")

        # 创建默认管理员账号
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                role='admin',
                dorm_room='0-000'
            )
            admin.set_password('admin123')
            db.session.add(admin)
            db.session.commit()
            print('[OK] 默认管理员已创建: admin / admin123 （请登录后立即修改密码）')

        # 写入默认配置
        defaults = {
            'monitor_interval': '30',
            'alert_threshold': '20',
            'alert_level_warning': '20',
            'alert_level_urgent': '10',
            'alert_level_critical': '5',
            'max_fail_count': '3',
        }
        for key, value in defaults.items():
            cfg = SystemConfig.query.get(key)
            if not cfg:
                db.session.add(SystemConfig(key=key, value=value))
        db.session.commit()
        print('[OK] 默认配置已写入')
        print()
        print('初始化完成，请运行 python run.py 启动程序')


if __name__ == '__main__':
    init_db()
