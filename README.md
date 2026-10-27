# 宿舍电费监控系统 · Dorm Electricity Monitor

> 实时查询宿舍剩余电量，快用完时自动提醒——不用再摸黑洗澡。

一个跑在本机的小系统：定时从学校缴费平台（上海建桥学院 · 常工电控）拉取宿舍剩余电量，
低于阈值时通过微信 / 邮件 / 企业微信机器人推送告警；同时提供深色主题的 Web 仪表盘和可打包成
exe 的桌面客户端。

## 功能特性

- **定时监控**：默认每 30 分钟查询一次，失败计数保护，避免因接口抖动误报
- **三级告警**：剩余 ≤ 20 / 10 / 5 度分三档提醒，同档位不重复推送，电量恢复后发送解除通知
- **多渠道推送**：Server酱（微信）、SMTP 邮件、企业微信群机器人，可任选组合
- **数据可视化**：ECharts 趋势图（含阈值参考线）、剩余电量与预估可用天数
- **多用户**：管理员 / 普通成员两种角色，每人可绑定自己的宿舍号与查询凭证
- **手动兜底**：自动查询失效时，可在仪表盘直接手填"当前剩余"，告警与趋势逻辑保持一致
- **桌面模式**：`desktop.py` 用 pywebview 套壳，可用 PyInstaller 打包为单文件 exe
- **深色 UI**：Bootstrap 5 + 自定义深色主题，7 个页面（登录 / 仪表盘 / 设置 / 用户 / 配置 / 日志 / 基类）

## 技术栈

| 层次 | 选型 |
| --- | --- |
| Web 框架 | Flask 3.0 + Flask-Login + Flask-SQLAlchemy |
| 数据库 | SQLite（默认）/ MySQL（可切换） |
| 定时任务 | APScheduler |
| 数据采集 | requests 直连接口；Playwright 无头浏览器（备用模式） |
| 前端 | Jinja2 模板 + Bootstrap 5 + ECharts 5 |
| 桌面端 | pywebview + PyInstaller |

## 目录结构

```
dorm-electricity-monitor/
├── app/
│   ├── __init__.py      # 应用工厂：读配置、建库连接、注册蓝图、日志
│   ├── models.py        # users / electricity_records / alert_records / system_config / fetch_logs
│   ├── routes.py        # 页面路由与接口
│   ├── auth.py          # 登录、会话、权限装饰器
│   ├── monitor.py       # 调度器：抓取 → 入库 → 分级告警
│   ├── fetcher.py       # 缴费平台抓取（api / browser 双模式）
│   ├── notifier.py      # Server酱 / 邮件 / 企业微信推送
│   └── db_init.py       # 建表 + 默认管理员
├── tools/               # 抓包与授权辅助脚本（gench_login / capture / probe_login 等）
├── templates/           # 7 个页面模板
├── static/              # 静态资源目录（样式与脚本内联在模板中）
├── config/config.yaml   # 全部配置项
├── run.py               # Web 启动入口
├── desktop.py           # 桌面客户端入口
├── 宿舍电费监控.spec     # PyInstaller 打包配置
└── requirements.txt
```

## 快速开始

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 1) 改配置：config/config.yaml 里的 server.secret_key（必须改）
#    数据库默认 SQLite，文件会在首次启动时自动创建于 data/

# 2) 建表并创建默认管理员 admin / admin123
python -m app.db_init

# 3) 启动
python run.py            # http://127.0.0.1:5000
```

桌面模式：

```powershell
python desktop.py                     # 打开原生窗口
pyinstaller 宿舍电费监控.spec          # 打包 exe（输出到 dist/）
```

## 运行前必须自己准备

这个项目**不包含任何账号、密码、接口凭证**，全部要你自己准备。缺哪一项，对应功能就用不了：

| 要准备什么 | 填在哪 | 怎么拿到 |
| --- | --- | --- |
| **Flask 会话密钥**（必需） | `config/config.yaml` → `server.secret_key` | 随便一串长随机字符，如 `openssl rand -hex 32` 的输出 |
| **支付宝用户 ID**（aliUserId，自动查询必需） | `config/config.yaml` → `changgong.ali_user_id`，或登录后网页「个人设置」 | **必须用抓包 / 授权工具获取**，见下一节。这是 2088 开头的数字串，不是账号密码 |
| **缴费接口地址与 Token**（可选，`api` 模式用） | `config/config.yaml` → `alipay.api_base` / `query_path` / `auth_token` | 同样来自抓包结果；用 `gench_login.py` 方案可留空 |
| **推送渠道**（告警必需，任选其一） | `config/config.yaml` → `notification.*` | Server酱：`sct.ftqq.com` 取 SendKey；邮件：QQ 邮箱「授权码」；企业微信：群机器人 webhook |
| **数据库**（可选） | `config/config.yaml` → `database.type` | 默认 SQLite 免配置；要用 MySQL 得自己建库并填账号密码 |

> 也就是说：**光 clone 下来是跑不出数据的**，必须完成下面「数据怎么来」这一步，否则只能用手动记录模式。

## 数据怎么来（抓取 aliUserId）

系统数据源是学校缴费平台背后的常工电控系统，查询需要一个 **aliUserId**（2088 开头的支付宝用户标识）。

```powershell
python tools/gench_login.py     # 按提示完成"统一身份认证 + 支付宝扫码"两步授权，自动抓到 aliUserId
```

拿到后填入 `config/config.yaml` 的 `changgong.ali_user_id`，或在网页「个人设置」里按用户填写。
若 `gench_login.py` 失效，也可以用 `tools/capture.py`（Playwright）或手机抓包（Reqable / Charles / Fiddler），
手动把接口地址、Token/Cookie、余额字段路径填进 `alipay` 段。

> `tools/` 里的 `reqable-root.crt`、`install_cert.bat`、`fix_cert.sh` 是抓包用的证书与安装脚本，
> 只在抓包时需要，日常运行用不到；不放心可以删掉。

> 具体字段说明和抓包步骤见 `config/config.yaml` 注释与下方配置表。

## 配置项说明

| 配置 | 说明 |
| --- | --- |
| `server.secret_key` | Flask 会话密钥，**必须换成自己的随机串** |
| `database.type` | `sqlite`（默认，零配置）或 `mysql` |
| `changgong.ali_user_id` | 全局默认的支付宝用户 ID，留空则只使用各用户在页面上填的值 |
| `alipay.mode` | `api` 直连接口 / `browser` 无头浏览器兜底 |
| `monitor.interval_minutes` | 查询间隔，默认 30 分钟 |
| `monitor.alert_levels` | 三档阈值与颜色 |
| `notification.*` | Server酱 SendKey、SMTP 账号授权码、企业微信 webhook |

## 关于本副本

本目录是用于公开发布的副本，已做如下处理：

- 移除了 `build/`、`dist/`、`logs/`、`data/` 等运行产物与本地数据库；
- `config/config.yaml` 中的 `secret_key` 与 `ali_user_id` 已清空为占位符，**运行时请重新填写**。

源项目目录与历史数据未被改动。

## 已知限制

- 依赖学校侧接口，接口或授权策略变动后需要重新抓包；
- 默认管理员密码 `admin123` 仅用于首次登录，请立即修改；
- 单机部署，未做多实例并发控制（SQLite 模式下也不适合多进程写入）。

## License

仅供学习交流使用。与学校官方无关，请勿用于商业用途。
