# xhs-monitor — 小红书竞品账号监测

基于 [Spider_XHS](https://github.com/cv-cat/Spider_XHS) 构建的竞品账号定期采集系统：增量采集 → SQLite 沉淀 + Excel 汇总 → HTML 报告 → 邮件推送。执行方案详见 [EXECUTION_PLAN.md](./EXECUTION_PLAN.md)。

`apis/`、`xhs_utils/` 目录 vendor 自上游 Spider_XHS（仅学习交流用途），采集签名依赖本地 Node.js（20+）与 `node_modules/crypto-js`（已 `npm install`）。

## 获取登录 Cookie

**方式一（推荐）：脚本登录，全自动**

```bash
uv run python -m monitor.login           # 手机号 + 短信验证码
# 或
uv run python -m monitor.login --qrcode  # 终端显示二维码，小红书 App 扫码
```

按提示输入手机号和收到的验证码，成功后 Cookie 自动写入 `.env`。

**方式二：手动抓取**

1. 电脑浏览器打开并登录 `xiaohongshu.com`
2. 按 `F12` 打开开发者工具 → 切到 `Network`（网络）标签
3. 刷新页面，点列表中任意一个请求 → 右侧 `Headers`（标头）
4. 找到 `Request Headers` 下的 `Cookie:`，**右键 → 复制值**（完整一长串）
5. 粘贴到 `.env` 的 `COOKIES=''` 单引号内，保存

Cookie 约 2~4 周失效，失效会收到 `[告警] Cookie 失效` 邮件，重新执行方式一即可。

## 添加竞品账号

竞品 `user_id` 就在其主页链接中：

```
https://www.xiaohongshu.com/user/profile/6030f6b4000000000100a821?xsec_token=...
                                      ^^^^^^^^^^^^^^^^^^^^^^^^ 这一段就是 user_id
```

编辑 `watchlist.yaml`：

```yaml
users:
  - name: 竞品A
    user_id: 6030f6b4000000000100a821
```

一般只填 `user_id` 即可；若采集返回为空（链接 token 过期），在浏览器打开其主页，复制**带 `xsec_token` 参数的完整链接**填到 `homepage` 字段（token 会过期，过期后重新复制一次）。

## 运行

```bash
uv run python -m monitor.run              # 采集 + 报告 + 看板 + 邮件
uv run python -m monitor.run --no-mail    # 只采集出报告，不发邮件（调试用）
uv run python -m monitor.run --collect-only    # 只采集入库
uv run python -m monitor.backfill [轮数]  # 历史详情回填（多轮循环补详情）
```

## 数据看板

每次运行后生成 `data/dashboard.html`（单文件，双击浏览器打开即可）：

- **统计卡**：监测账号数 / 笔记总数 / 今日新增 / 联名内容数 / 总点赞
- **筛选器**：账号、图文/视频、今日新增/近7天/近30天、只看联名、关键词搜索、多种排序
- **联名内容专区**：独立模块展示识别出的联名笔记（品牌A × 品牌B）
- **笔记瀑布流**：封面 + 标题 + 互动数据，今日新增带 NEW 标记，点击卡片弹出详情（正文全文、话题、数据、原文链接）
- 深浅色主题切换（记住偏好）、键盘操作（Tab 聚焦 + Enter 打开 + Esc 关闭）

## 联名识别

对标题 + 正文 + 话题做启发式识别：

1. **配对规则**（主要）：`品牌A x 品牌B`，分隔符支持 `x / X / × / ✖ / ✕`，自动修剪"联名/礼盒/开箱"等修饰词，过滤 `vs / iphone` 等常见误匹配
2. **关键词兜底**：无配对但包含 `联名 / 合作款 / 联乘` 时，摘录上下文并标注"（关键词）"

识别结果存于 `notes.cobrand` 字段。启发式规则无法覆盖所有形式（如口播视频、图片内联名信息），可在看板中人工复核。

采集范围：`watchlist.yaml` 中 `min_publish_date: '2026-01-01'`，仅采集该日期之后发布的笔记，翻页从最新往旧自动截止。

## 定时（cron）

```bash
crontab -e
# 每天 08:00 运行：
0 8 * * * cd /home/yefu/xhs-monitor && /home/yefu/.local/bin/uv run python -m monitor.run >> logs/cron.log 2>&1
```

## 输出

| 位置 | 内容 |
|------|------|
| `data/monitor.db` | SQLite：全部笔记历史 + 每期互动数快照（爆款趋势数据源） |
| `data/excel/` | 每期 Excel 汇总（账号汇总 + 新增笔记两个 sheet） |
| `data/reports/` | 每期 HTML 报告（账号概况 / 互动增长 Top / 新增明细） |
| `data/notes/` | 笔记详情归档（开启 `download_media` 后含无水印图片） |
| `logs/` | 按天滚动的运行日志 |

## 稳定性设计

- **增量采集**：以 note_id 去重，每账号只翻到已见笔记为止，日常每账号仅 1~2 次列表请求；新笔记才拉详情。
- **互动快照**：每期对可见笔记记录点赞/收藏/评论数，报告自动给出"互动增长 Top"（爆款发现）。
- **限速**：详情间 5~15s、账号间 30~60s 随机间隔；单次每账号详情上限可配。
- **告警**：Cookie 失效、采集异常、疑似风控 → 立即告警邮件（可扩展企业微信/Server酱）。
- **建议**：使用专用小号采集；如遇频繁风控，可在 `XHS_Apis.bootstrap(proxies=...)` 处接入代理。

## 项目结构

```
xhs-monitor/
├── monitor/
│   ├── config.py        # 配置加载（.env + watchlist.yaml）
│   ├── db.py            # SQLite（notes / note_metrics / run_history）
│   ├── collect.py       # 增量采集主流程 + 联名识别
│   ├── report.py        # Excel + HTML 日报生成
│   ├── dashboard.py     # 数据看板（单文件 HTML）
│   ├── backfill.py      # 历史详情回填
│   ├── mailer.py        # 邮件发送（报告/告警）
│   ├── login.py         # 登录并自动保存 Cookie
│   ├── run.py           # 一键入口
│   └── templates/       # Jinja2 模板（日报/告警/看板）
├── apis/ xhs_utils/     # vendor 自 Spider_XHS
├── data/ logs/          # 输出（gitignore）
├── watchlist.yaml       # 竞品清单
└── .env                 # Cookie / SMTP（gitignore）
```
