"""
mitmproxy 附加脚本: 自动记录含电费关键词的响应 + 所有可达域名
随 mitmdump 加载:  mitmdump -s alipay_capture_addon.py ...
"""
import json
import re
import time

KEYWORDS = re.compile(
    r'(elec|electric|room|surplus|balance|charge|rest|power|money|yue|dian|qfei|df)', re.I)
TEXT_HINTS = ('宿舍', '余额', '剩余', '电量', '充值', '水电')
URL_LOG = r'E:\dorm-electricity-monitor\logs\mitm_urls.log'
HIT_LOG = r'E:\dorm-electricity-monitor\logs\mitm_hits.jsonl'


def _log_hit(flow):
    entry = {
        'time': time.strftime('%H:%M:%S'),
        'method': flow.request.method,
        'url': flow.request.pretty_url,
        'req_headers': dict(flow.request.headers),
        'req_body': flow.request.get_text(strict=False) or '',
        'status': flow.response.status_code,
        'resp_headers': dict(flow.response.headers),
        'resp_body': (flow.response.get_text(strict=False) or '')[:8000],
    }
    with open(HIT_LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


class CaptureAddon:
    def response(self, flow):
        try:
            url = flow.request.pretty_url
            with open(URL_LOG, 'a', encoding='utf-8') as f:
                f.write(f"{time.strftime('%H:%M:%S')} {flow.response.status_code} "
                        f"{flow.request.method} {url}\n")
            body = ''
            ct = flow.response.headers.get('content-type', '')
            if 'json' in ct or 'text' in ct or 'html' in ct or 'javascript' in ct:
                body = flow.response.get_text(strict=False) or ''
            if KEYWORDS.search(url) or any(h in body for h in TEXT_HINTS):
                _log_hit(flow)
                print(f"[HIT] {flow.request.method} {url}")
        except Exception as e:
            print(f"[addon-error] {e}")

    def tls_failed_client(self, client_addr, data):
        print(f"[TLS-FAIL-client] {client_addr} {getattr(data, 'sni', '')}")

    def tls_failed_server(self, server_addr, data):
        print(f"[TLS-FAIL-server] {server_addr} {getattr(data, 'sni', '')}")


addons = [CaptureAddon()]
