import atexit

import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from app import create_app
from app.models import db
from app.monitor import Monitor
import app.routes as routes_module

app = create_app()


def main():
    with app.app_context():
        db.create_all()

        # 启动监控, 并把实例挂到路由模块供"立即查询"接口使用
        monitor = Monitor(app, app.config['APP_CONFIG'])
        routes_module.monitor_instance = monitor
        monitor.start()
        atexit.register(monitor.stop)

    cfg = app.config['APP_CONFIG']['server']
    print(f"\n{'=' * 50}")
    print(f"  宿舍电费监控系统已启动")
    print(f"  地址: http://{cfg['host']}:{cfg['port']}")
    print(f"  默认账号: admin / admin123")
    print(f"  数据源: 支付宝-水电充值中心(普通宿舍充电)")
    print(f"{'=' * 50}\n")

    # 关闭 reloader, 避免调试模式下调度器被启动两次
    app.run(
        host=cfg['host'],
        port=cfg['port'],
        debug=cfg.get('debug', False),
        use_reloader=False
    )


if __name__ == '__main__':
    main()
