"""
通知推送模块
支持：Server酱（微信）、邮件、企业微信机器人
"""
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests

logger = logging.getLogger(__name__)


class Notifier:
    """通知推送管理器"""

    def __init__(self, config):
        self.config = config or {}

    def send_serverchan(self, sendkey: str, title: str, content: str) -> bool:
        """Server酱 微信推送"""
        try:
            url = f"https://sctapi.ftqq.com/{sendkey}.send"
            resp = requests.post(url, data={'title': title, 'desp': content}, timeout=10)
            result = resp.json()
            if result.get('code') == 0:
                logger.info("Server酱推送成功")
                return True
            else:
                logger.warning(f"Server酱推送失败: {result}")
                return False
        except Exception as e:
            logger.error(f"Server酱推送异常: {e}")
            return False

    def send_email(self, smtp_config: dict, receivers: list, subject: str, body: str) -> bool:
        """邮件通知"""
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = smtp_config.get('smtp_user', '')
            msg['To'] = ', '.join(receivers)

            # 纯文本 + HTML 双格式
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            html_body = body.replace('\n', '<br>')
            html_body = f'<div style="font-family:sans-serif;padding:20px;">{html_body}</div>'
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))

            if smtp_config.get('smtp_port', 465) == 465:
                server = smtplib.SMTP_SSL(smtp_config['smtp_server'], smtp_config['smtp_port'], timeout=10)
            else:
                server = smtplib.SMTP(smtp_config['smtp_server'], smtp_config['smtp_port'], timeout=10)
                server.starttls()

            server.login(smtp_config['smtp_user'], smtp_config['smtp_password'])
            server.sendmail(smtp_config['smtp_user'], receivers, msg.as_string())
            server.quit()
            logger.info(f"邮件发送成功: {receivers}")
            return True
        except Exception as e:
            logger.error(f"邮件发送异常: {e}")
            return False

    def send_wecom_bot(self, webhook_url: str, content: str) -> bool:
        """企业微信机器人推送"""
        try:
            payload = {
                'msgtype': 'text',
                'text': {'content': content}
            }
            resp = requests.post(webhook_url, json=payload, timeout=10)
            result = resp.json()
            if result.get('errcode') == 0:
                logger.info("企业微信推送成功")
                return True
            else:
                logger.warning(f"企业微信推送失败: {result}")
                return False
        except Exception as e:
            logger.error(f"企业微信推送异常: {e}")
            return False

    def notify_all(self, title: str, content: str, user=None, notification_config: dict = None):
        """
        根据配置发送所有启用的通知渠道
        :param title: 通知标题
        :param content: 通知内容
        :param user: User 对象（获取用户个人配置）
        :param notification_config: 通知配置段
        """
        sent_channels = []
        nc = notification_config or {}

        # Server酱: 用户填了自己的 SendKey 即视为启用; 或全局配置开启
        user_key = (user.serverchan_key if user else '') or ''
        if user_key or nc.get('serverchan', {}).get('enabled'):
            sendkey = user_key or nc['serverchan'].get('sendkey', '')
            if sendkey:
                if self.send_serverchan(sendkey, title, content):
                    sent_channels.append('Server酱')

        # 邮件
        if nc.get('email', {}).get('enabled'):
            receivers = [user.email] if user and user.email else nc['email'].get('receivers', [])
            smtp_cfg = nc['email']
            if receivers and smtp_cfg.get('smtp_user'):
                if self.send_email(smtp_cfg, receivers, title, content):
                    sent_channels.append('邮件')

        # 企业微信
        if nc.get('wecom_bot', {}).get('enabled'):
            webhook = nc['wecom_bot'].get('webhook_url', '')
            if webhook:
                if self.send_wecom_bot(webhook, content):
                    sent_channels.append('企业微信')

        if not sent_channels:
            logger.warning("没有可用的通知渠道，请检查配置")
        return sent_channels
