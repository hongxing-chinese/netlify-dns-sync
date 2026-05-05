# Netlify DNS Sync

自动获取 GitHub 上的 Netlify 优化 IP 列表，并更新到华为云国际版 DNS 解析的 Python 脚本。支持三大运营商（电信、联通、移动）分线路解析，并附带飞书机器人执行结果通知。

## 功能

- 定时从 GitHub 获取最新的 Netlify 三网优化 IP
- 自动更新华为云 DNS A 记录（支持分线路解析）
- 执行完成后通过飞书机器人推送结果通知
- 配置通过 `.env` 文件管理，安全便捷

## 项目结构

```
.
├── update_dns.py       # 主脚本
├── .env                # 环境变量配置文件（需自行创建）
├── .env.example        # 环境变量模板
├── requirements.txt    # Python 依赖
└── README.md           # 本文件
```

## 快速开始

### 1. 克隆/下载项目

```bash
cd /home/netlify-dns-sync
```

### 2. 创建虚拟环境并安装依赖

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> Windows 环境下激活命令：`venv\Scripts\activate`

### 3. 配置环境变量

复制模板文件并填写实际信息：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
# 华为云 API 密钥
HUAWEI_AK=你的AccessKey
HUAWEI_SK=你的SecretKey

# 飞书自定义机器人 Webhook 地址
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxxxx

# DNS 区域（默认 ap-southeast-1，华为云国际版）
HUAWEI_REGION=ap-southeast-1
```

#### 获取华为云密钥

1. 登录 [华为云控制台](https://console.huaweicloud.com/)
2. 右上角头像 -> 我的凭证 -> 访问密钥 -> 创建
3. 保存 AK 和 SK

#### 获取飞书 Webhook 地址

1. 打开飞书电脑端，进入目标群聊
2. 群设置 -> 添加机器人 -> 自定义机器人
3. 安全设置：**只勾选「自定义关键词」**，输入关键词：`Netlify 优选IP更新`
4. 复制 Webhook 地址填入 `.env`

> 注意：通知消息标题为 **「Netlify 优选IP更新」**，飞书安全设置中的自定义关键词请填写这个短语。

### 4. 配置域名解析记录

在 `update_dns.py` 的 `DOMAINS_CONFIG` 中配置你的域名信息。每个线路需要提前在华为云 DNS 控制台创建好 A 记录，然后通过浏览器 F12 抓包获取 `zone_id` 和 `recordset_id`。

```python
DOMAINS_CONFIG = [
    {
        "domain_name": "你的域名.com",
        "zone_id": "ff8080xxxxxxxxxxxxxxxx",
        "records": {
            "dianxin": "电信线路 recordset_id",
            "liantong": "联通线路 recordset_id",
            "yidong": "移动线路 recordset_id"
        }
    }
]
```

### 5. 测试运行

```bash
source venv/bin/activate
python update_dns.py
```

看到终端输出各线路更新状态，且飞书收到通知即表示配置成功。

## 部署到云服务器（Linux）

以下以 Ubuntu/Debian 为例。

### 1. 上传项目到服务器

```bash
git clone https://github.com/hongxing-chinese/netlify-dns-sync.git
```

### 2. 在服务器上安装依赖

```bash
cd /home/netlify-dns-sync
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. 创建 `.env` 文件

```bash
cp .env.example .env
nano .env
# 填入你的 AK、SK、Webhook 地址
```

### 4. 添加定时任务（每 30 分钟执行一次）

```bash
crontab -e
```

添加以下行：

```cron
*/30 * * * * cd /home/netlify-dns-sync && /home/netlify-dns-sync/venv/bin/python /home/netlify-dns-sync/update_dns.py >> /home/netlify-dns-sync/run.log 2>&1
```

保存后查看是否生效：

```bash
crontab -l
```

查看执行日志：

```bash
tail -f /home/netlify-dns-sync/run.log
```

## 数据源

- [enhanced-FaaS-in-China/Netlify.json](https://github.com/xingpingcn/enhanced-FaaS-in-China/blob/main/Netlify.json)

## 注意事项

- `.env` 文件包含敏感信息，**切勿提交到 Git**
- 项目已配置 `.gitignore`，默认忽略 `.env` 和 `venv/` 目录
- 若某线路 IP 列表为空（如电信暂无数据），脚本会自动跳过该线路，不会清空现有记录
- 如需停止定时任务，执行 `crontab -e` 删除对应行即可
