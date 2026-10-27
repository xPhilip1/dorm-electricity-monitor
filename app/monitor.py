import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from app.models import db, ElectricityRecord, AlertRecord, FetchLog, User, SystemConfig
from app.fetcher import AlipayElecFetcher, ChanggongFetcher
from app.notifier import Notifier

logger = logging.getLogger(__name__)


class Monitor:
    """电费监控调度器(数据源: 常工电控, 经支付宝 aliUserId 认证)"""

    def __init__(self, app, config):
        self.app = app
        self.config = config
        self.scheduler = BackgroundScheduler()
        self.notifier = Notifier(config.get('notification', {}))
        self.changgong = ChanggongFetcher()
        self.legacy_fetcher = AlipayElecFetcher(config.get('alipay', {}))
        self.unit = config.get('alipay', {}).get('unit', '度')

    def get_config_value(self, key, default=None):
        """从数据库读取配置"""
        with self.app.app_context():
            cfg = SystemConfig.query.get(key)
            return cfg.value if cfg else default

    def check_user(self, user):
        """检查单个用户的宿舍电费"""
        # 常工电控数据源: 优先用户级 aliUserId, 其次全局配置
        ali = (user.alipay_token or '').strip() or \
              (self.config.get('changgong', {}) or {}).get('ali_user_id', '')
        if ali:
            result = self.changgong.query(ali)
            # 自动同步真实宿舍号(充值主页返回绑定表具的房间)
            room = result.get('room')
            if result['success'] and room and user.dorm_room != room:
                logger.info(f'用户 {user.username} 宿舍号自动同步: '
                            f'{user.dorm_room} -> {room}')
                user.dorm_room = room
                db.session.commit()
        else:
            result = self.legacy_fetcher.query(user.dorm_room, user.alipay_token)

        if not result['success']:
            self._log_fetch(user.dorm_room, False,
                            result.get('raw', '未知错误'),
                            result.get('duration_ms', 0))
            return

        self._log_fetch(user.dorm_room, True, duration_ms=result.get('duration_ms', 0))

        balance = result['balance']                  # 剩余购电
        subsidy = result.get('subsidy') or 0.0       # 剩余补助
        total = balance + subsidy                    # 总可用电量, 告警按此判定
        status = self._get_status(total)

        record = ElectricityRecord(
            dorm_room=user.dorm_room,
            balance=balance,
            subsidy=subsidy,
            usage_today=result.get('usage_today', 0),
            status=status,
            raw_data=result.get('raw', '')
        )
        db.session.add(record)
        db.session.commit()

        self._check_alert(user, user.dorm_room, total, status,
                          balance_part=balance, subsidy=subsidy)

    def _source_configured(self):
        """判断是否配置了自动采集数据源"""
        if (self.config.get('changgong', {}) or {}).get('ali_user_id'):
            return True
        if any((u.alipay_token or '').strip() for u in User.query.all()):
            return True
        cfg = self.config.get('alipay', {}) or {}
        if cfg.get('api_base') and cfg.get('query_path'):
            return True
        if (cfg.get('browser', {}) or {}).get('page_url'):
            return True
        return False

    def check_all(self):
        """检查所有绑定了宿舍的用户"""
        if not self._source_configured():
            logger.info("数据源未配置(支付宝接口无法自动抓取), 跳过自动采集; "
                        "可在仪表盘使用手动记录模式")
            return

        logger.info("=== 开始定时电费检查 ===")
        with self.app.app_context():
            # 常工模式下宿舍号由查询结果自动同步, 不要求用户预先填写宿舍号;
            # 只要有可用数据源(用户级 aliUserId 或全局配置)即纳入检查
            has_global = bool((self.config.get('changgong', {}) or {}).get('ali_user_id'))
            users = [u for u in User.query.all()
                     if has_global or (u.alipay_token or '').strip()]
            if not users:
                logger.warning("没有配置数据源的用户, 跳过检查")
                return

            for user in users:
                try:
                    self.check_user(user)
                except Exception as e:
                    logger.error(f"检查用户 {user.username} 异常: {e}")

            # 清理超过 90 天的历史记录
            cutoff = datetime.now() - timedelta(days=90)
            ElectricityRecord.query.filter(ElectricityRecord.created_at < cutoff).delete()
            db.session.commit()

        logger.info("=== 定时电费检查完成 ===")

    def _get_status(self, balance):
        """根据余额确定状态等级(阈值单位同 alipay.unit)"""
        critical = float(self.get_config_value('alert_level_critical', 5))
        urgent = float(self.get_config_value('alert_level_urgent', 10))
        warning = float(self.get_config_value('alert_level_warning', 20))

        if balance <= critical:
            return 'critical'
        elif balance <= urgent:
            return 'urgent'
        elif balance <= warning:
            return 'warning'
        return 'normal'

    def _check_alert(self, user, dorm_room, balance, status, balance_part=None, subsidy=0.0):
        """检查并触发告警

        balance 参数为总可用电量(购电+补助); balance_part/subsidy 用于消息分项展示
        """
        balance_part = balance if balance_part is None else balance_part

        def _amount_text():
            if subsidy:
                return (f'购电 {balance_part:.2f} + 补助 {subsidy:.2f} '
                        f'= 共 {balance:.2f} {self.unit}')
            return f'{balance:.2f} {self.unit}'

        if status == 'normal':
            # 余额恢复: 关闭未恢复的告警并发送恢复通知
            unrecovered = AlertRecord.query.filter_by(
                user_id=user.id, dorm_room=dorm_room, is_recovered=False
            ).all()
            for alert in unrecovered:
                alert.is_recovered = True
                alert.recovered_at = datetime.now()
            db.session.commit()

            if unrecovered:
                title = f"电费已恢复 - {dorm_room}"
                content = (f"宿舍 {dorm_room} 剩余电量已恢复, 当前{_amount_text()}, "
                           f"告警解除。")
                self.notifier.notify_all(title, content, user, self.config.get('notification', {}))
            return

        # 同等级告警未恢复时不重复发送
        existing = AlertRecord.query.filter_by(
            user_id=user.id, dorm_room=dorm_room,
            level=status, is_recovered=False
        ).first()
        if existing:
            return

        level_names = {'warning': '普通提醒', 'urgent': '紧急提醒', 'critical': '严重告警'}
        title = f"[{level_names.get(status, '告警')}] {dorm_room} 剩余电量不足"
        content = (
            f"宿舍: {dorm_room}\n"
            f"当前可用: {_amount_text()}\n"
            f"告警等级: {level_names.get(status, '未知')}\n"
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"请及时在支付宝-水电充值中心充值, 避免宿舍断电!"
        )

        alert = AlertRecord(
            user_id=user.id,
            dorm_room=dorm_room,
            level=status,
            balance=balance,
            message=content
        )
        db.session.add(alert)

        sent = self.notifier.notify_all(title, content, user, self.config.get('notification', {}))
        alert.channel = ', '.join(sent) if sent else '无可用渠道'
        alert.is_sent = len(sent) > 0
        db.session.commit()

        logger.info(f"告警已触发: {title}, 渠道: {alert.channel}")

    def _log_fetch(self, dorm_room, success, error_msg=None, duration_ms=0):
        """记录抓取日志"""
        log = FetchLog(
            dorm_room=dorm_room,
            success=success,
            error_msg=error_msg,
            duration_ms=duration_ms
        )
        db.session.add(log)
        db.session.commit()

    def start(self):
        """启动定时监控"""
        interval = int(self.get_config_value('monitor_interval', 30))
        self.scheduler.add_job(
            self.check_all,
            'interval',
            minutes=interval,
            id='electricity_check',
            replace_existing=True
        )
        self.scheduler.start()
        logger.info(f"定时监控已启动, 每 {interval} 分钟检查一次")

        # 启动后立即执行一次
        self.check_all()

    def stop(self):
        """停止定时监控"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        logger.info("定时监控已停止")

    def trigger_now(self):
        """手动触发一次检查"""
        self.check_all()
