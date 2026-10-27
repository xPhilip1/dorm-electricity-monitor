"""
支付宝 aliUserId 手动配置工具 (Flask Web 界面)

由于常工电控页面通过支付宝 JSAPI 静默获取 aliUserId,
URL 中不会暴露该参数, 因此改为纯手动输入模式。

用法:
  python tools/capture_ali_user_id_v2.py
  浏览器自动打开 http://127.0.0.1:5002
  按页面提示操作即可

依赖: Flask, requests, PyYAML
"""
import os
import sys
import re
import threading
import webbrowser

# ------------------------------------------------------------------
#  定位项目根目录
# ------------------------------------------------------------------
def find_project_root():
    """从脚本位置往上找, 直到找到 config/config.yaml"""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        if os.path.isfile(os.path.join(d, 'config', 'config.yaml')):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.getcwd()


ROOT = find_project_root()
os.chdir(ROOT)

# 把 templates 目录加入 Flask 搜索路径
TEMPLATE_DIR = os.path.join(ROOT, 'templates')

from flask import Flask, render_template_string, request, jsonify
import yaml

# ------------------------------------------------------------------
#  配置读写
# ------------------------------------------------------------------
def read_config():
    cfg_path = os.path.join(ROOT, 'config', 'config.yaml')
    if os.path.isfile(cfg_path):
        with open(cfg_path, encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}


def write_ali_user_id(ali_user_id):
    cfg_path = os.path.join(ROOT, 'config', 'config.yaml')
    cfg = read_config()
    if not cfg.get('changgong'):
        cfg['changgong'] = {}
    cfg['changgong']['ali_user_id'] = ali_user_id
    with open(cfg_path, 'w', encoding='utf-8') as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True,
                  sort_keys=False)


# ------------------------------------------------------------------
#  HTML 模板
# ------------------------------------------------------------------
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>支付宝凭证配置 - 宿舍电费监控</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', sans-serif;
            background: #0f0f1a;
            color: #e0e0e0;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: flex-start;
            padding: 30px 16px;
        }
        .container { max-width: 560px; width: 100%; }
        .header {
            text-align: center;
            margin-bottom: 28px;
        }
        .header h1 {
            font-size: 22px;
            color: #60a5fa;
            margin-bottom: 6px;
        }
        .header p {
            font-size: 13px;
            color: #888;
        }
        .card {
            background: #1a1a2e;
            border: 1px solid #2a2a4a;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 16px;
        }
        .card h3 {
            font-size: 15px;
            color: #f0f0f0;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .step-num {
            background: #3b82f6;
            color: white;
            width: 24px; height: 24px;
            border-radius: 50%;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 13px;
            font-weight: bold;
            flex-shrink: 0;
        }
        .tip {
            background: rgba(59, 130, 246, 0.08);
            border: 1px solid rgba(59, 130, 246, 0.25);
            border-radius: 8px;
            padding: 12px 14px;
            margin: 12px 0;
            font-size: 13px;
            line-height: 1.7;
            color: #b0b0c0;
        }
        .tip strong { color: #60a5fa; }
        .tip .warn { color: #fbbf24; }
        .tip .green { color: #34d399; }
        .form-group { margin-bottom: 14px; }
        .form-group label {
            display: block;
            font-size: 13px;
            color: #aaa;
            margin-bottom: 6px;
        }
        input[type="text"] {
            width: 100%;
            background: #0f0f1a;
            border: 1px solid #2a2a4a;
            border-radius: 8px;
            color: #e0e0e0;
            padding: 10px 12px;
            font-size: 14px;
            font-family: 'Consolas', 'Courier New', monospace;
            transition: border-color 0.2s;
        }
        input[type="text"]:focus {
            outline: none;
            border-color: #3b82f6;
        }
        .btn {
            display: inline-block;
            padding: 10px 28px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            border: none;
            transition: all 0.2s;
        }
        .btn-primary {
            background: #3b82f6;
            color: white;
        }
        .btn-primary:hover { background: #2563eb; }
        .btn-primary:disabled {
            background: #333;
            color: #666;
            cursor: not-allowed;
        }
        .btn-secondary {
            background: transparent;
            color: #888;
            border: 1px solid #2a2a4a;
            font-size: 12px;
            padding: 6px 14px;
        }
        .btn-secondary:hover {
            color: #bbb;
            border-color: #444;
        }
        .status {
            padding: 14px;
            border-radius: 8px;
            margin-top: 14px;
            font-size: 14px;
            display: none;
        }
        .status.success {
            background: rgba(52, 211, 153, 0.1);
            border: 1px solid rgba(52, 211, 153, 0.3);
            color: #34d399;
            display: block;
        }
        .status.error {
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid rgba(239, 68, 68, 0.3);
            color: #ef4444;
            display: block;
        }
        .status.info {
            background: rgba(96, 165, 250, 0.1);
            border: 1px solid rgba(96, 165, 250, 0.3);
            color: #60a5fa;
            display: block;
        }
        .current-id {
            background: rgba(52, 211, 153, 0.08);
            border: 1px solid rgba(52, 211, 153, 0.2);
            border-radius: 8px;
            padding: 14px;
            text-align: center;
            margin-bottom: 16px;
        }
        .current-id .label {
            font-size: 12px;
            color: #888;
            margin-bottom: 4px;
        }
        .current-id .value {
            font-size: 18px;
            color: #34d399;
            font-family: 'Consolas', monospace;
            font-weight: bold;
        }
        .guide-steps {
            counter-reset: step;
        }
        .guide-step {
            position: relative;
            padding: 10px 0 10px 36px;
            font-size: 13px;
            line-height: 1.7;
            color: #b0b0c0;
            border-left: 2px solid #2a2a4a;
            margin-left: 12px;
        }
        .guide-step:last-child { border-left-color: transparent; }
        .guide-step::before {
            counter-increment: step;
            content: counter(step);
            position: absolute;
            left: -13px;
            top: 10px;
            width: 24px; height: 24px;
            background: #3b82f6;
            color: white;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            font-weight: bold;
        }
        .guide-step strong { color: #e0e0e0; }
        .guide-step code {
            background: #0f0f1a;
            padding: 1px 6px;
            border-radius: 4px;
            font-family: 'Consolas', monospace;
            font-size: 12px;
            color: #60a5fa;
        }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>&#x1F511; 支付宝凭证配置</h1>
        <p>宿舍电费监控系统 - 常工电控 aliUserId 配置工具</p>
    </div>

    {% if current_id %}
    <div class="current-id">
        <div class="label">当前已配置的 aliUserId</div>
        <div class="value">{{ current_id }}</div>
    </div>
    {% endif %}

    <!-- 步骤1: 获取 aliUserId -->
    <div class="card">
        <h3><span class="step-num">1</span> 获取你的 aliUserId</h3>

        <div class="tip" style="margin-top:0;">
            <strong>什么是 aliUserId?</strong><br>
            它是支付宝分配给你账号的 <span class="green">固定用户 ID</span> (2088 开头),
            <strong>永不过期</strong>。获取一次后, 程序即可永久自动查询宿舍电费。
        </div>

        <p style="font-size:13px; color:#aaa; margin:14px 0 10px;">
            获取方法 (需使用抓包工具):
        </p>

        <div class="guide-steps">
            <div class="guide-step">
                在电脑上打开抓包工具 <strong>Reqable</strong> (或 Fiddler / Charles)
            </div>
            <div class="guide-step">
                手机连接电脑代理, 打开 <strong>支付宝 App</strong>
            </div>
            <div class="guide-step">
                在支付宝中进入: <strong>校园生活 → 缴费中心 → 常工电控</strong>
                <br><span style="color:#888;">(或搜索 "上海建桥学院" 进入电控缴费页面)</span>
            </div>
            <div class="guide-step">
                在抓包工具中找到 <code>changgongdiankong.gench.edu.cn</code> 的请求
                <br><span style="color:#888;">URL 中会包含 <code>aliUserId=2088xxxxxxxx</code> 参数</span>
            </div>
            <div class="guide-step">
                复制该 <code>2088</code> 开头的数字, 粘贴到下方输入框
            </div>
        </div>

        <div class="tip" style="margin-top:14px;">
            <span class="warn">提示:</span> 如果你之前已经知道自己的 aliUserId,
            可以直接在下方输入, 无需重复抓包。
        </div>
    </div>

    <!-- 步骤2: 输入并保存 -->
    <div class="card">
        <h3><span class="step-num">2</span> 输入 aliUserId 并保存</h3>

        <div class="form-group">
            <label>aliUserId (2088 开头的数字)</label>
            <input type="text" id="manualInput" placeholder="2088xxxxxxxxxxxxxxxx" maxlength="20">
        </div>

        <button class="btn btn-primary" id="saveBtn" onclick="saveId()">
            保存凭证
        </button>
        <button class="btn btn-secondary" style="margin-left:8px;" onclick="testConnection()">
            测试连接
        </button>

        <div class="status" id="statusBox"></div>
    </div>
</div>

<script>
    function saveId() {
        var aliId = document.getElementById('manualInput').value.trim();
        if (!aliId) {
            showStatus('请先输入 aliUserId', 'error');
            return;
        }
        if (!/^2088\d{8,24}$/.test(aliId)) {
            showStatus('aliUserId 格式不正确, 应为 2088 开头的 12~28 位数字', 'error');
            return;
        }
        var btn = document.getElementById('saveBtn');
        btn.disabled = true;
        btn.textContent = '保存中...';

        fetch('/api/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ali_user_id: aliId})
        })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.success) {
                showStatus('保存成功! aliUserId = ' + aliId + '\n现在可以关闭此页面, 回到主程序使用。', 'success');
                btn.textContent = '已保存';
                setTimeout(function() {
                    fetch('/api/shutdown', {method: 'POST'}).catch(function(){});
                }, 2000);
            } else {
                showStatus('保存失败: ' + (d.message || '未知错误'), 'error');
                btn.disabled = false;
                btn.textContent = '保存凭证';
            }
        })
        .catch(function(e) {
            showStatus('请求失败: ' + e, 'error');
            btn.disabled = false;
            btn.textContent = '保存凭证';
        });
    }

    function testConnection() {
        var aliId = document.getElementById('manualInput').value.trim();
        if (!aliId) {
            showStatus('请先输入 aliUserId', 'error');
            return;
        }
        showStatus('正在测试连接...', 'info');
        fetch('/api/test', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ali_user_id: aliId})
        })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.success) {
                var msg = '连接成功! ';
                if (d.balance !== undefined) msg += '剩余购电: ' + d.balance + '度';
                if (d.subsidy) msg += ', 补助: ' + d.subsidy + '度';
                if (d.room) msg += ', 房间: ' + d.room;
                showStatus(msg, 'success');
            } else {
                showStatus('连接失败: ' + (d.error || '未知错误'), 'error');
            }
        })
        .catch(function(e) {
            showStatus('请求失败: ' + e, 'error');
        });
    }

    function showStatus(msg, type) {
        var box = document.getElementById('statusBox');
        box.textContent = msg;
        box.className = 'status ' + type;
    }
</script>
</body>
</html>
"""


# ------------------------------------------------------------------
#  Flask 应用
# ------------------------------------------------------------------
app = Flask(__name__, template_folder=TEMPLATE_DIR)
app.secret_key = 'ali-capture-tool-temp-key'


@app.route('/')
def index():
    cfg = read_config()
    current_id = str(
        (cfg.get('changgong') or {}).get('ali_user_id', '')
    ).strip()

    return render_template_string(
        HTML_TEMPLATE,
        current_id=current_id or None,
    )


@app.route('/api/save', methods=['POST'])
def api_save():
    data = request.get_json(silent=True) or {}
    ali_id = (data.get('ali_user_id') or '').strip()

    if not re.match(r'^2088\d{8,24}$', ali_id):
        return jsonify({'success': False,
                        'message': 'aliUserId 格式不正确, 应为 2088 开头'})

    try:
        write_ali_user_id(ali_id)
        return jsonify({'success': True, 'ali_user_id': ali_id})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/test', methods=['POST'])
def api_test():
    """测试 aliUserId 是否能正常查询常工电控"""
    data = request.get_json(silent=True) or {}
    ali_id = (data.get('ali_user_id') or '').strip()

    if not re.match(r'^2088\d{8,24}$', ali_id):
        return jsonify({'success': False, 'error': 'aliUserId 格式不正确'})

    try:
        sys.path.insert(0, ROOT)
        from app.fetcher import ChanggongFetcher
        fetcher = ChanggongFetcher()
        result = fetcher.query(ali_id)

        if result['success']:
            return jsonify({
                'success': True,
                'balance': result['balance'],
                'subsidy': result.get('subsidy', 0),
                'room': result.get('room'),
            })
        else:
            return jsonify({
                'success': False,
                'error': result.get('raw', '查询失败'),
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/shutdown', methods=['POST'])
def api_shutdown():
    """保存成功后关闭 Flask 服务器"""
    def _shutdown():
        try:
            os._exit(0)
        except Exception:
            pass
    # 延迟关闭, 先返回响应给浏览器
    threading.Timer(0.5, _shutdown).start()
    return jsonify({'success': True})


# ------------------------------------------------------------------
#  主入口
# ------------------------------------------------------------------
def main():
    print('=' * 55)
    print('  支付宝 aliUserId 配置工具')
    print('  (宿舍电费监控 - 常工电控)')
    print('=' * 55)
    print()

    port = 5002
    url = f'http://127.0.0.1:{port}'
    print(f'  正在启动 Web 服务: {url}')
    print(f'  浏览器将自动打开, 按页面提示操作即可')
    print()

    # 延迟打开浏览器 (等 Flask 启动)
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    print(f'  提示: 如浏览器未自动打开, 请手动访问 {url}')
    print()

    try:
        app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)
    except OSError as e:
        if 'address already in use' in str(e).lower() or '10048' in str(e):
            print(f'\n  端口 {port} 被占用, 尝试使用 {port + 1}...')
            app.run(host='127.0.0.1', port=port + 1, debug=False,
                    use_reloader=False)
        else:
            raise


if __name__ == '__main__':
    main()
