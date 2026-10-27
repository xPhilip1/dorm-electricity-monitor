import logging
import os
import sys
import winreg
import yaml
from datetime import datetime, timedelta

from flask import (
    Flask, render_template, redirect, url_for,
    request, flash, jsonify, current_app
)
from flask_login import (
    login_user, logout_user, login_required, current_user
)
from werkzeug.security import generate_password_hash

from app.models import db, User, ElectricityRecord, AlertRecord, SystemConfig, FetchLog
from app.auth import login_manager, admin_required
from app.monitor import Monitor

logger = logging.getLogger(__name__)

monitor_instance: Monitor = None


def register_routes(app: Flask):
    global monitor_instance

    # ---- 认证路由 ----

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        first_run = (User.query.count() == 0)
        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                login_user(user, remember=True)
                user.last_login = datetime.now()
                db.session.commit()
                next_page = request.args.get('next')
                return redirect(next_page or url_for('index'))
            flash('用户名或密码错误', 'danger')
        return render_template('login.html', first_run=first_run)

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('login'))

    # ---- 仪表盘 ----

    @app.route('/')
    @login_required
    def index():
        dorm_room = current_user.dorm_room

        # 当前用户或所有用户可见的宿舍（管理员看全部）
        if current_user.role == 'admin':
            rooms = db.session.query(
                User.dorm_room
            ).filter(User.dorm_room != '0-000').distinct().all()
            selected_room = request.args.get('room', dorm_room)
        else:
            selected_room = dorm_room

        # 最新一条记录
        latest = ElectricityRecord.query.filter_by(
            dorm_room=selected_room
        ).order_by(ElectricityRecord.created_at.desc()).first()

        # 最近 7 天记录（用于图表）
        week_ago = datetime.now() - timedelta(days=7)
        week_records = ElectricityRecord.query.filter(
            ElectricityRecord.dorm_room == selected_room,
            ElectricityRecord.created_at >= week_ago
        ).order_by(ElectricityRecord.created_at.asc()).all()

        # 最近 10 条告警
        recent_alerts = AlertRecord.query.filter_by(
            dorm_room=selected_room
        ).order_by(AlertRecord.created_at.desc()).limit(10).all()

        # 估算日均消耗
        daily_usage = _estimate_daily_usage(selected_room)

        return render_template('dashboard.html',
                               latest=latest,
                               week_records=week_records,
                               recent_alerts=recent_alerts,
                               selected_room=selected_room,
                               daily_usage=daily_usage,
                               rooms=rooms if current_user.role == 'admin' else [])

    # ---- 历史数据 API ----

    @app.route('/api/history')
    @login_required
    def api_history():
        dorm_room = request.args.get('room', current_user.dorm_room)
        days = int(request.args.get('days', 7))
        start = datetime.now() - timedelta(days=days)
        records = ElectricityRecord.query.filter(
            ElectricityRecord.dorm_room == dorm_room,
            ElectricityRecord.created_at >= start
        ).order_by(ElectricityRecord.created_at.asc()).all()
        return jsonify([
            {
                'time': r.created_at.strftime('%m-%d %H:%M'),
                'balance': round((r.balance or 0) + (r.subsidy or 0), 2),
                'status': r.status
            }
            for r in records
        ])

    # ---- 开机自启 ----

    AUTOSTART_RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
    AUTOSTART_VALUE_NAME = 'DormElectricityMonitor'

    def _autostart_enabled():
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_RUN_KEY) as k:
                winreg.QueryValueEx(k, AUTOSTART_VALUE_NAME)
                return True
        except OSError:
            return False

    @app.route('/api/autostart', methods=['GET', 'POST'])
    @login_required
    def api_autostart():
        if not getattr(sys, 'frozen', False):
            return jsonify({'code': -1, 'enabled': _autostart_enabled(),
                            'msg': '仅打包版(exe)支持此功能'})

        exe = sys.executable
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            enable = bool(data.get('enable'))
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_RUN_KEY,
                                    0, winreg.KEY_SET_VALUE) as k:
                    if enable:
                        winreg.SetValueEx(k, AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ,
                                          f'"{exe}" --autostart')
                    else:
                        try:
                            winreg.DeleteValue(k, AUTOSTART_VALUE_NAME)
                        except FileNotFoundError:
                            pass
            except OSError as e:
                return jsonify({'code': -1, 'enabled': _autostart_enabled(),
                                'msg': f'注册表操作失败: {e}'})

        enabled = _autostart_enabled()
        msg = ('已开启开机自启: 登录 Windows 后自动后台运行(不弹浏览器), '
               '访问 http://127.0.0.1:5000 查看面板' if enabled else '已关闭开机自启')
        return jsonify({'code': 0, 'enabled': enabled, 'msg': msg})

    # ---- 发送测试通知(验证推送渠道是否配置正确) ----

    @app.route('/api/test_notify', methods=['POST'])
    @login_required
    def api_test_notify():
        from app.notifier import Notifier

        data = request.get_json(silent=True) or {}
        key = (data.get('key') or current_user.serverchan_key or '').strip()
        if not key:
            return jsonify({'code': -1, 'msg': '请先填写 Server酱 SendKey'})

        cfg = current_app.config.get('APP_CONFIG', {})
        notifier = Notifier(cfg.get('notification', {}))
        latest = ElectricityRecord.query.filter_by(
            dorm_room=current_user.dorm_room
        ).order_by(ElectricityRecord.created_at.desc()).first()

        balance_text = (f'{latest.balance:.2f} 度(另有补助 {latest.subsidy:.2f} 度)'
                        if latest and latest.subsidy else
                        f'{latest.balance:.2f} 度' if latest else '暂无记录')
        title = '电费监控 - 测试通知'
        content = (f'收到这条消息说明微信推送配置成功!\n\n'
                   f'宿舍: {current_user.dorm_room}\n'
                   f'当前剩余: {balance_text}\n'
                   f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n\n'
                   f'当剩余电量低于告警阈值时, 会推送同样的消息提醒你充值。')
        ok = notifier.send_serverchan(key, title, content)
        if ok:
            return jsonify({'code': 0, 'msg': '测试消息已发送, 请查看微信「方糖」服务号'})
        return jsonify({'code': -1, 'msg': '发送失败: SendKey 无效或已达每日上限(免费版5条/天)'})

    # ---- 启动 aliUserId 授权工具 ----

    @app.route('/api/launch_auth_tool', methods=['POST'])
    @login_required
    def api_launch_auth_tool():
        """启动 aliUserId 授权工具 (Flask Web 界面 + QR 码)"""
        import subprocess
        import shutil

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if getattr(sys, 'frozen', False):
            root = os.path.dirname(sys.executable)

        tool = os.path.join(root, 'tools', 'capture_ali_user_id_v2.py')
        if not os.path.exists(tool):
            return jsonify({'code': -1, 'msg': '找不到授权工具脚本'})

        # 冻结模式用系统 Python, 源码模式用当前解释器
        if getattr(sys, 'frozen', False):
            python_exe = shutil.which('python') or shutil.which('python3') or shutil.which('py')
            if not python_exe:
                return jsonify({'code': -1, 'msg': '未找到系统 Python, 无法启动授权工具'})
        else:
            python_exe = sys.executable

        try:
            # 在独立窗口中启动, 不阻塞主程序
            subprocess.Popen(
                [python_exe, tool],
                creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0,
                cwd=root,
            )
            return jsonify({'code': 0, 'msg': '授权工具已启动, 浏览器将自动打开'})
        except Exception as e:
            return jsonify({'code': -1, 'msg': f'启动失败: {e}'})

    # ---- 手动记录(数据源不可自动抓取时的兜底方案) ----

    def _status_for_balance(balance):
        """根据系统配置的阈值判断余额状态"""
        def val(key, default):
            cfg = SystemConfig.query.get(key)
            try:
                return float(cfg.value) if cfg else float(default)
            except (TypeError, ValueError):
                return float(default)

        if balance <= val('alert_level_critical', 5):
            return 'critical'
        if balance <= val('alert_level_urgent', 10):
            return 'urgent'
        if balance <= val('alert_level_warning', 20):
            return 'warning'
        return 'normal'

    @app.route('/api/manual_record', methods=['POST'])
    @login_required
    def api_manual_record():
        data = request.get_json(silent=True) or request.form
        try:
            balance = round(float(data.get('balance')), 2)
        except (TypeError, ValueError):
            return jsonify({'code': -1, 'msg': '请输入有效的数字'})
        if balance < 0:
            return jsonify({'code': -1, 'msg': '数值不能为负数'})

        dorm = current_user.dorm_room
        status = _status_for_balance(balance)

        record = ElectricityRecord(
            dorm_room=dorm,
            balance=balance,
            subsidy=0,
            usage_today=0,
            status=status,
            raw_data='manual'
        )
        db.session.add(record)
        db.session.commit()

        # 复用监控的告警逻辑(分级去重/恢复通知/推送)
        if monitor_instance:
            monitor_instance._check_alert(current_user, dorm, balance, status)
            level_names = {'warning': '普通提醒', 'urgent': '紧急提醒', 'critical': '严重告警'}
            msg = (f'已记录(手动输入按总剩余口径), 当前状态: {level_names.get(status, status)}'
                   if status != 'normal' else '已记录, 电量充足')
        else:
            msg = '已记录(监控未启动)'
        return jsonify({'code': 0, 'msg': msg, 'status': status})

    # ---- 手动触发检查 ----

    @app.route('/api/trigger', methods=['POST'])
    @login_required
    def api_trigger():
        if monitor_instance:
            monitor_instance.trigger_now()
            return jsonify({'code': 0, 'msg': '已触发检查'})
        return jsonify({'code': -1, 'msg': '监控未启动'})

    # ---- 个人设置 ----

    @app.route('/settings', methods=['GET', 'POST'])
    @login_required
    def settings():
        if request.method == 'POST':
            action = request.form.get('action')

            if action == 'profile':
                current_user.dorm_room = request.form.get('dorm_room', current_user.dorm_room)
                current_user.email = request.form.get('email', '')
                current_user.serverchan_key = request.form.get('serverchan_key', '')
                db.session.commit()
                flash('个人设置已保存', 'success')

            elif action == 'password':
                old_pwd = request.form.get('old_password', '')
                new_pwd = request.form.get('new_password', '')
                if not current_user.check_password(old_pwd):
                    flash('原密码错误', 'danger')
                elif len(new_pwd) < 6:
                    flash('新密码至少 6 位', 'warning')
                else:
                    current_user.set_password(new_pwd)
                    db.session.commit()
                    flash('密码已修改', 'success')

            elif action == 'alipay':
                alipay_token = request.form.get('alipay_token', '').strip()
                if alipay_token:
                    current_user.alipay_token = alipay_token
                db.session.commit()
                flash('支付宝会话凭据已保存', 'success')

            return redirect(url_for('settings'))

        config_ali_id = (current_app.config.get('APP_CONFIG', {}).get('changgong', {}) or {}).get('ali_user_id', '')
        return render_template('settings.html', config_ali_id=str(config_ali_id).strip())

    # ---- 管理员：用户管理 ----

    @app.route('/admin/users')
    @login_required
    @admin_required
    def admin_users():
        users = User.query.all()
        return render_template('admin_users.html', users=users)

    @app.route('/admin/users/<int:uid>/delete', methods=['POST'])
    @login_required
    @admin_required
    def admin_delete_user(uid):
        if uid == current_user.id:
            flash('不能删除自己', 'danger')
        else:
            user = User.query.get_or_404(uid)
            db.session.delete(user)
            db.session.commit()
            flash(f'已删除用户 {user.username}', 'success')
        return redirect(url_for('admin_users'))

    @app.route('/admin/users/create', methods=['POST'])
    @login_required
    @admin_required
    def admin_create_user():
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'member')
        dorm_room = request.form.get('dorm_room', '')

        if User.query.filter_by(username=username).first():
            flash('用户名已存在', 'danger')
            return redirect(url_for('admin_users'))

        user = User(username=username, role=role, dorm_room=dorm_room)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash(f'已创建用户 {username}', 'success')
        return redirect(url_for('admin_users'))

    # ---- 管理员：系统配置 ----

    @app.route('/admin/config', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def admin_config():
        if request.method == 'POST':
            for key, value in request.form.items():
                if key.startswith('cfg_'):
                    cfg_key = key[4:]
                    cfg = SystemConfig.query.get(cfg_key)
                    if cfg:
                        cfg.value = value
                    else:
                        db.session.add(SystemConfig(key=cfg_key, value=value))
            db.session.commit()

            # 如果修改了监控间隔，重启调度器
            if monitor_instance:
                monitor_instance.stop()
                monitor_instance.start()

            flash('系统配置已保存', 'success')
            return redirect(url_for('admin_config'))

        configs = SystemConfig.query.all()
        return render_template('admin_config.html', configs=configs)

    # ---- 管理员：抓取日志 ----

    @app.route('/admin/logs')
    @login_required
    @admin_required
    def admin_logs():
        page = request.args.get('page', 1, type=int)
        per_page = 30
        pagination = FetchLog.query.order_by(
            FetchLog.created_at.desc()
        ).paginate(page=page, per_page=per_page)
        return render_template('admin_logs.html', pagination=pagination)

    # ---- 上下文处理器 ----

    @app.context_processor
    def inject_globals():
        status_colors = {
            'normal': '#28a745',
            'warning': '#f0ad4e',
            'urgent': '#fd7e14',
            'critical': '#dc3545',
            'unknown': '#6c757d'
        }
        alipay_cfg = current_app.config.get('APP_CONFIG', {}).get('alipay', {})

        def _cfg_val(key, default):
            cfg = SystemConfig.query.get(key)
            try:
                return float(cfg.value) if cfg else float(default)
            except (TypeError, ValueError):
                return float(default)

        return dict(
            now=datetime.now(),
            status_colors=status_colors,
            elec_unit=alipay_cfg.get('unit', '度'),
            thresholds={
                'warning': _cfg_val('alert_level_warning', 20),
                'urgent': _cfg_val('alert_level_urgent', 10),
                'critical': _cfg_val('alert_level_critical', 5),
            }
        )


def _estimate_daily_usage(dorm_room):
    """估算日均耗电量(按总剩余=购电+补助的口径)"""
    records = ElectricityRecord.query.filter(
        ElectricityRecord.dorm_room == dorm_room
    ).order_by(ElectricityRecord.created_at.desc()).limit(48).all()

    if len(records) < 2:
        return None

    def _total(r):
        return (r.balance or 0) + (r.subsidy or 0)

    oldest = records[-1]
    newest = records[0]
    hours = (newest.created_at - oldest.created_at).total_seconds() / 3600
    if hours < 1:
        return None

    usage = _total(oldest) - _total(newest)
    if usage <= 0:
        return 0

    daily_usage = usage / hours * 24
    return round(daily_usage, 2)
