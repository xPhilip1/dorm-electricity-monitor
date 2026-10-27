from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """系统用户表"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.Enum('admin', 'member'), default='member', nullable=False)
    dorm_room = db.Column(db.String(32), nullable=False, comment='宿舍号，如 6-301')
    campus_account = db.Column(db.String(64), comment='学校统一认证账号')
    campus_password = db.Column(db.String(256), comment='学校统一认证密码（加密存储）')
    alipay_token = db.Column(db.Text, comment='支付宝水电充值接口 token/cookie（抓包获得，优先于全局配置）')
    serverchan_key = db.Column(db.String(128), comment='Server酱 SendKey')
    email = db.Column(db.String(128), comment='通知邮箱')
    created_at = db.Column(db.DateTime, default=datetime.now)
    last_login = db.Column(db.DateTime)

    # 关系
    alerts = db.relationship('AlertRecord', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def set_campus_password(self, password):
        self.campus_password = generate_password_hash(password)

    def check_campus_password(self, password):
        return check_password_hash(self.campus_password, password)


class ElectricityRecord(db.Model):
    """电费查询记录表"""
    __tablename__ = 'electricity_records'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dorm_room = db.Column(db.String(32), nullable=False, index=True)
    balance = db.Column(db.Float, nullable=False, comment='剩余购电（度）')
    subsidy = db.Column(db.Float, default=0, comment='剩余补助（度）')
    usage_today = db.Column(db.Float, default=0, comment='当日用电量（度）')
    status = db.Column(db.Enum('normal', 'warning', 'urgent', 'critical', 'unknown'),
                       default='normal', comment='状态')
    raw_data = db.Column(db.Text, comment='原始返回数据（调试用）')
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)


class AlertRecord(db.Model):
    """告警记录表"""
    __tablename__ = 'alert_records'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    dorm_room = db.Column(db.String(32), nullable=False)
    level = db.Column(db.Enum('warning', 'urgent', 'critical'), nullable=False)
    balance = db.Column(db.Float, nullable=False)
    message = db.Column(db.Text, nullable=False)
    channel = db.Column(db.String(32), comment='通知渠道')
    is_sent = db.Column(db.Boolean, default=False, comment='是否发送成功')
    is_recovered = db.Column(db.Boolean, default=False, comment='是否已恢复')
    recovered_at = db.Column(db.DateTime, comment='恢复时间')
    created_at = db.Column(db.DateTime, default=datetime.now)


class SystemConfig(db.Model):
    """系统配置表（Web 界面可修改的配置）"""
    __tablename__ = 'system_config'

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, nullable=False)
    description = db.Column(db.String(256))
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)


class FetchLog(db.Model):
    """抓取日志表"""
    __tablename__ = 'fetch_logs'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    dorm_room = db.Column(db.String(32), nullable=False)
    success = db.Column(db.Boolean, default=False)
    error_msg = db.Column(db.Text)
    duration_ms = db.Column(db.Integer, comment='耗时（毫秒）')
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)
