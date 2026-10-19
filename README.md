# Cloudflare 每日定时 DNS 记录脚本

这是一个按**中国标准时间（Asia/Shanghai，UTC+8）**常驻运行的 Cloudflare DNS 脚本。每条记录都有自己的每日开始和结束时间：到各自的 `start_time` 创建，到各自的 `end_time` 删除。

同一时间的多条记录只需填相同时间；不同时间的记录可以混合在同一个 `RECORDS` 列表中。

## 安装条件

- Python 3.9 或以上
- 目标域名已在 Cloudflare 账号中处于 Active 状态
- Cloudflare 登录邮箱与 Global API Key
- 运行设备在计划期间不能休眠、关机或停止脚本

项目无第三方依赖，但可以执行：

```powershell
pip install -r requirements.txt
```

## 配置

所有配置都在 [config.py](config.py)：

```python
CF_EMAIL = "your-cloudflare-email@example.com"
CF_GLOBAL_API_KEY = "paste-your-new-global-api-key-here"
ZONE_NAME = "example.com"
```

### 独立时间的记录列表

在 `RECORDS` 中配置一条或多条 A / CNAME 记录。每条都必须包含自己的 `start_time` 与 `end_time`：

```python
RECORDS = [
    # 每天 08:00 创建，10:00 删除
    {"type": "A", "name": "morning", "content": "203.0.113.10", "ttl": 1, "proxied": False,
     "start_time": "08:00", "end_time": "10:00"},

    # 每天 12:30 创建，16:00 删除
    {"type": "A", "name": "promo", "content": "203.0.113.11", "ttl": 300, "proxied": False,
     "start_time": "12:30", "end_time": "16:00"},

    # 与第一条使用相同时间，会在同一时段执行
    {"type": "CNAME", "name": "www", "content": "target.example.net", "ttl": 1, "proxied": False,
     "start_time": "08:00", "end_time": "10:00"},
]
```

| 字段 | 说明 |
| --- | --- |
| `type` | `A` 或 `CNAME` |
| `name` | 二级域名，如 `promo`；`@` 表示根域名；也可填写完整域名 |
| `content` | A 填 IPv4；CNAME 填目标域名 |
| `ttl` | `1` 为自动，其他值至少 60 秒 |
| `proxied` | `True` 开启橙云，`False` 为仅 DNS |
| `start_time` | 每天的中国时间，格式 `HH:MM` 或 `HH:MM:SS`，到点创建 |
| `end_time` | 每天的中国时间，格式同上，到点删除 |

当 `end_time` 小于或等于 `start_time` 时，自动跨午夜。例如 `23:00` 到 `01:00`，表示当天 23:00 创建、次日 01:00 删除。

多个 A 记录可使用同一个名称。CNAME 不能与同名 A、AAAA、TXT 等冲突记录共存；这是 Cloudflare DNS 的规则，冲突时 API 会返回错误。

## 预演与启动

首次保持：

```python
CONFIRM_CHANGES = False
```

运行：

```powershell
python .\cf_timed_a_record.py
```

预演只验证本地配置并打印每条记录的计划，**不会连接 Cloudflare，也不会修改 DNS**。

确认无误后，将 `CONFIRM_CHANGES` 改为 `True`，用相同命令启动。脚本每 15 秒检查一次中国时间，并持续执行直到按 `Ctrl+C` 停止。建议长期部署在不休眠的 VPS 或使用 Windows 任务计划程序开机自动启动。

## 精确删除与恢复机制

每条记录创建成功后，脚本会立刻在 `.cf_timed_dns_state.json` 中保存：

- Cloudflare 返回的精确 `record_id`
- 该记录的结束时间
- 该记录对应的配置指纹

到结束时间时，脚本只会对这个 `record_id` 发送删除请求：

- 不会按名称、类型或 IP 搜索并删除其他记录；
- 不会删除用户原本已有的同名记录；
- 多条记录的创建、删除互不影响；
- 某条记录创建失败时，已成功创建的记录 ID 仍会保存，脚本重启后可继续处理；
- 中断后重启，脚本会先删除状态文件中已到期的 ID，再继续等待或创建未到期记录；
- 状态文件不是新版格式时，脚本会停止，避免对旧记录作猜测性删除。

`config.py` 与状态文件都在 `.gitignore` 中。不要上传、提交或分享它们；如果 Global API Key 泄露，应立即在 Cloudflare 撤销并更换。
