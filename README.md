# xhs-monitor — 小红书竞品账号监测

基于 [Spider_XHS](https://github.com/cv-cat/Spider_XHS) 构建的竞品账号定期采集系统：增量采集 → SQLite 沉淀 + Excel 汇总 → HTML 报告 → 邮件推送。执行方案详见 [EXECUTION_PLAN.md](./EXECUTION_PLAN.md)。

`apis/`、`xhs_utils/` 目录 vendor 自上游 Spider_XHS（仅学习交流用途），采集签名依赖本地 Node.js（20+）与 `node_modules/crypto-js`（已 `npm install`）。

## 快速开始

```bash
uv sync          # Python 依赖
npm install      # 签名算法依赖
cp .env.example .env   # 然后填写 COOKIES 与 SMTP 配置
```

1. **配置 Cookie**：浏览器登录小红书 → F12 → Network → 任意请求 → 复制完整 Cookie → 填入 `.env` 的 `COOKIES`（约 2~4 周失效一次，失效会收到告警邮件）。
2. **配置竞品清单**：编辑 `watchlist.yaml`，填入竞品 `user_id`（主页链接 `https://www.xiaohongshu.com/user/profile/<user_id>` 中的一段）。
3. **配置邮件**：`.env` 中填 SMTP（QQ 邮箱用授权码）。

## 运行

```bash
uv run xhs-monitor            # 采集 + 报告 + 邮件
uv run xhs-monitor --no-mail  # 只采集出报告，不发邮件（调试用）
uv run xhs-monitor --collect-only  # 只采集入库
```

## 定时（cron）

```bash
crontab -e
# 每天 08:00 运行：
0 8 * * * cd /home/yefu/xhs-monitor && /home/yefu/.local/bin/uv run xhs-monitor >> logs/cron.log 2>&1
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
│   ├── collect.py       # 增量采集主流程
│   ├── report.py        # Excel + HTML 报告生成
│   ├── mailer.py        # 邮件发送（报告/告警）
│   ├── run.py           # 一键入口
│   └── templates/       # Jinja2 模板
├── apis/ xhs_utils/     # vendor 自 Spider_XHS
├── data/ logs/          # 输出（gitignore）
├── watchlist.yaml       # 竞品清单
└── .env                 # Cookie / SMTP（gitignore）
```
