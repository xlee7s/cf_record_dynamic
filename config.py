# Cloudflare 登录邮箱与 Global API Key。
# 此文件只保留在本机，已被 .gitignore 排除；不要上传到 GitHub 或发送给他人。
CF_EMAIL = "xxxxxxx@gmail.com"
CF_GLOBAL_API_KEY = "xxxxxxxxxxxxxxxxxxx"

# 解析所在的主域名，以及每天要创建的记录列表。
ZONE_NAME = "xxxx.de5.net"
# 支持 A 与 CNAME；每条记录可单独设置中国时间 start_time / end_time。
# 相同时间的记录填写相同的时间即可。每条记录独立保存 record_id，结束时只删除本脚本创建的 ID。
RECORDS = [
    {"type": "A", "name": "promo", "content": "203.0.113.10", "ttl": 1, "proxied": False, "start_time": "16:33", "end_time": "16:34"},
    {"type": "A", "name": "promo", "content": "203.0.113.11", "ttl": 1, "proxied": False, "start_time": "16:34", "end_time": "16:38"},
    {"type": "CNAME", "name": "www", "content": "target.example.net", "ttl": 1, "proxied": False, "start_time": "16:36", "end_time": "16:37"},
]

# 首次建议保持 False，仅检查配置而不修改 Cloudflare。
# 确认无误后改成 True，再运行脚本。脚本会一直运行直到手动停止。
CONFIRM_CHANGES = True
STATE_FILE = ".cf_timed_dns_state.json"
