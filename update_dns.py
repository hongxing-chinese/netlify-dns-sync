import os
import time
import urllib.request
import urllib.error
import json
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkdns.v2.region.dns_region import DnsRegion
from huaweicloudsdkdns.v2 import DnsClient, UpdateRecordSetRequest, UpdateRecordSetReq

# 加载 .env 环境变量
load_dotenv()

# ================= 配置区域 =================

# 1. 从环境变量读取华为云 API 密钥
AK = os.environ.get("HUAWEI_AK", "")
SK = os.environ.get("HUAWEI_SK", "")

# 2. 飞书机器人 Webhook
FEISHU_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL", "")

# 3. DNS 区域
HUAWEI_REGION = os.environ.get("HUAWEI_REGION", "ap-southeast-1")

# 4. JSON 数据源 URL
JSON_URL = "https://raw.githubusercontent.com/xingpingcn/enhanced-FaaS-in-China/refs/heads/main/Netlify.json"

# 5. 域名与记录配置字典
DOMAINS_CONFIG = [
    {
        "domain_name": "hxch.top",
        "zone_id": "ff8080829db652b9019df3a1c6cb6e10",
        "records": {
            "dianxin": "ff8080829dbb43ac019e56565af640cc",
            "liantong": "ff8080829e17ffac019e56580a8a554c",
            "yidong": "ff8080829dbb43ac019e56591b864124"
        }
    },
    {
        "domain_name": "hxch.eu.org",
        "zone_id": "ff8080829dbb3f00019df3c573153bb1",
        "records": {
            "dianxin": "ff8080829a923d9f019df48e333328dc",
            "liantong": "ff8080829dbb31fd019df48e95bf03cb",
            "yidong": "ff8080829a924b9b019df48ed06963a6"
        }
    }
]

LINE_NAME_MAP = {
    "dianxin": "电信",
    "liantong": "联通",
    "yidong": "移动"
}

# 6. run.log 路径（与脚本同目录）
RUN_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.log")

# 7. UTC+8 时区
TZ_CN = timezone(timedelta(hours=8))

# ================= 核心代码 =================

def fetch_ips():
    """从 GitHub 获取 JSON 并解析 IP 列表"""
    print(f"正在从 {JSON_URL} 获取最新 IP 数据...")
    try:
        req = urllib.request.Request(JSON_URL, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req, timeout=15)
        data = json.loads(response.read().decode('utf-8'))

        result = data.get("Netlify", {}).get("result", {})
        update_time = data.get("Netlify", {}).get("update_time", 0)

        # 提取三大运营商的 IP 数组
        ips = {
            "dianxin": result.get("dianxin", []),
            "liantong": result.get("liantong", []),
            "yidong": result.get("yidong", [])
        }
        default_ips = result.get("default", [])

        print(f"获取成功: 电信 {len(ips['dianxin'])}个, 联通 {len(ips['liantong'])}个, 移动 {len(ips['yidong'])}个, 默认 {len(default_ips)}个\n")
        return ips, default_ips, update_time

    except Exception as e:
        print(f"获取或解析 JSON 失败: {e}")
        return None, 0


def update_huawei_dns(client, domain_config, line_key, ip_list, default_ips):
    """更新单条解析记录，返回结果字典"""
    domain_name = domain_config["domain_name"]
    zone_id = domain_config["zone_id"]
    recordset_id = domain_config["records"].get(line_key)
    line_name = LINE_NAME_MAP.get(line_key, line_key)

    result = {
        "domain": domain_name,
        "line": line_name,
        "status": "跳过",
        "ips": ip_list,
        "error": ""
    }

    # 如果没填 ID 或 IP 列表为空，则跳过
    if not recordset_id or "HERE" in recordset_id:
        msg = f"  ⏭️  [{domain_name}] 的 [{line_name}] 未配置 recordset_id，跳过。"
        print(msg)
        result["error"] = "未配置 recordset_id"
        return result

    # 如果运营商 IP 列表为空，则使用 default IP 作为回退
    if not ip_list:
        if default_ips:
            ip_list = default_ips
            result["ips"] = ip_list
            print(f"  ⚠️  [{domain_name}] 的 [{line_name}] IP 列表为空，使用默认 IP: {ip_list}")
        else:
            msg = f"  ⏭️  [{domain_name}] 的 [{line_name}] IP 列表为空且无默认 IP，跳过更新以免清空记录。"
            print(msg)
            result["error"] = "IP 列表为空且无默认 IP"
            return result

    try:
        request = UpdateRecordSetRequest()
        request.zone_id = zone_id
        request.recordset_id = recordset_id
        request.body = UpdateRecordSetReq(
            records=ip_list,
            ttl=300
        )
        client.update_record_set(request)
        result["status"] = "成功"
        print(f"  ✅ [{domain_name}] - [{line_name}] 更新成功! IP: {ip_list}")
    except Exception as e:
        result["status"] = "失败"
        result["error"] = str(e)
        print(f"  ❌ [{domain_name}] - [{line_name}] 更新失败! 错误: {e}")

    return result


def should_send_daily_notification():
    """
    检查当前 UTC+8 时间是否为下午 16 点整点时段
    返回: (should_send: bool, current_hour: int)
    """
    now_cn = datetime.now(TZ_CN)
    current_hour = now_cn.hour

    # 判断是否在 16:00-16:59 之间
    if current_hour == 16:
        return True, current_hour
    return False, current_hour


def send_daily_log_notification():
    """发送过去一天的日志汇总通知，发送成功后清空日志"""
    if not FEISHU_WEBHOOK_URL:
        print("\n未配置 FEISHU_WEBHOOK_URL，跳飞书通知。")
        return False

    # 读取 run.log 内容
    log_content = ""
    try:
        if os.path.exists(RUN_LOG_PATH):
            with open(RUN_LOG_PATH, 'r', encoding='utf-8') as f:
                log_content = f.read().strip()
    except Exception as e:
        print(f"\n⚠️ 读取 run.log 失败: {e}")
        return False

    if not log_content:
        print("\nrun.log 为空，跳过飞书通知。")
        return False

    # 获取当前 UTC+8 时间
    now_cn = datetime.now(TZ_CN)
    date_str = now_cn.strftime("%Y-%m-%d")

    # 飞书 post 消息体
    payload = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": f"Netlify DNS 更新日志汇总 ({date_str})",
                    "content": [
                        [
                            {"tag": "text", "text": f"以下是过去一天的运行日志：\n"}
                        ],
                        [
                            {"tag": "text", "text": log_content[:30000]}  # 飞书消息长度限制
                        ]
                    ]
                }
            }
        }
    }

    max_retries = 3
    retry_delay = 60  # 1分钟

    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(
                FEISHU_WEBHOOK_URL,
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            response = urllib.request.urlopen(req, timeout=10)
            resp_data = json.loads(response.read().decode('utf-8'))

            if resp_data.get("code") == 0:
                print("\n📨 飞书日志汇总通知发送成功")
                # 发送成功后清空日志文件
                try:
                    with open(RUN_LOG_PATH, 'w', encoding='utf-8') as f:
                        f.truncate(0)
                    print("🗑️ run.log 已清空")
                except Exception as e:
                    print(f"⚠️ 清空 run.log 失败: {e}")
                return True
            elif resp_data.get("code") == 11232:
                print(f"\n⚠️ 飞书通知触发频率限制 (11232)，第 {attempt}/{max_retries} 次尝试")
                if attempt < max_retries:
                    print(f"   等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
                else:
                    print(f"   已达最大重试次数，放弃发送。")
                    return False
            else:
                print(f"\n⚠️ 飞书通知发送失败: {resp_data}")
                return False

        except Exception as e:
            print(f"\n⚠️ 飞书通知发送异常 (第 {attempt}/{max_retries} 次): {e}")
            if attempt < max_retries:
                print(f"   等待 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
            else:
                print(f"   已达最大重试次数，放弃发送。")
                return False

    return False


def send_feishu_notification(update_time, all_results):
    """发送飞书机器人通知"""
    if not FEISHU_WEBHOOK_URL:
        print("\n未配置 FEISHU_WEBHOOK_URL，跳过飞书通知。")
        return

    # 统计结果
    success_count = sum(1 for r in all_results if r["status"] == "成功")
    skip_count = sum(1 for r in all_results if r["status"] == "跳过")
    fail_count = sum(1 for r in all_results if r["status"] == "失败")

    # 格式化更新时间
    if update_time:
        update_dt = datetime.fromtimestamp(update_time).strftime("%Y-%m-%d %H:%M:%S")
    else:
        update_dt = "未知"

    # 构建详情文本
    detail_lines = []
    for r in all_results:
        if r["status"] == "成功":
            detail_lines.append(f"✅ {r['domain']} [{r['line']}] -> {', '.join(r['ips'])}")
        elif r["status"] == "失败":
            detail_lines.append(f"❌ {r['domain']} [{r['line']}] - {r['error']}")
        else:
            detail_lines.append(f"⏭️ {r['domain']} [{r['line']}] - {r['error']}")

    detail_text = "\n".join(detail_lines) if detail_lines else "无记录"

    # 飞书 post 消息体
    payload = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": "Netlify 优选IP更新",
                    "content": [
                        [
                            {"tag": "text", "text": f"数据源更新时间：{update_dt}\n"}
                        ],
                        [
                            {"tag": "text", "text": f"执行结果：成功 {success_count} 条，跳过 {skip_count} 条，失败 {fail_count} 条\n"}
                        ],
                        [
                            {"tag": "text", "text": "域名更新详情：\n"}
                        ],
                        [
                            {"tag": "text", "text": detail_text}
                        ]
                    ]
                }
            }
        }
    }

    max_retries = 5
    retry_delay = 120  # 2分钟

    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(
                FEISHU_WEBHOOK_URL,
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            response = urllib.request.urlopen(req, timeout=10)
            resp_data = json.loads(response.read().decode('utf-8'))

            if resp_data.get("code") == 0:
                print("\n📨 飞书通知发送成功")
                return
            elif resp_data.get("code") == 11232:
                print(f"\n⚠️ 飞书通知触发频率限制 (11232)，第 {attempt}/{max_retries} 次尝试")
                if attempt < max_retries:
                    print(f"   等待 {retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
                else:
                    print(f"   已达最大重试次数，放弃发送。")
                    return
            else:
                print(f"\n⚠️ 飞书通知发送失败: {resp_data}")
                return

        except Exception as e:
            print(f"\n⚠️ 飞书通知发送异常 (第 {attempt}/{max_retries} 次): {e}")
            if attempt < max_retries:
                print(f"   等待 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
            else:
                print(f"   已达最大重试次数，放弃发送。")
                return


def main():
    # 检查必要配置
    if not AK or not SK:
        print("错误：未配置 HUAWEI_AK 或 HUAWEI_SK，请检查 .env 文件")
        return

    # 0. 检查是否需要发送日志汇总通知（UTC+8 下午16点整点时段）
    should_send, current_hour = should_send_daily_notification()
    if should_send:
        print("=" * 50)
        print("⏰ 当前 UTC+8 时间为 16 点时段，准备发送日志汇总通知...")
        print("=" * 50)
        send_daily_log_notification()
    else:
        print(f"当前 UTC+8 时间为 {current_hour} 点，跳过飞书通知，继续执行 DNS 更新...")

    # 1. 获取最新 IP
    target_ips, default_ips, update_time = fetch_ips()
    if not target_ips:
        return

    # 2. 初始化华为云 SDK 客户端
    credentials = BasicCredentials(AK, SK)
    client = DnsClient.new_builder() \
        .with_credentials(credentials) \
        .with_region(DnsRegion.value_of(HUAWEI_REGION)) \
        .build()

    # 3. 循环遍历所有配置的域名进行更新，收集结果
    all_results = []
    for domain in DOMAINS_CONFIG:
        print(f"开始处理域名: {domain['domain_name']}")

        for line_key in ["dianxin", "liantong", "yidong"]:
            ip_list = target_ips.get(line_key, [])
            result = update_huawei_dns(client, domain, line_key, ip_list, default_ips)
            all_results.append(result)

        print("-" * 40)

if __name__ == "__main__":
    main()
