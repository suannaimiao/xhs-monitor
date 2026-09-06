# 竞品账号定期采集与推送系统 — 执行计划

> 基于 Spider_XHS 构建，目标：**定期、稳定**采集竞品账号发布内容 → 整理为表格/文件 → 生成 HTML 报告 → 定期邮件发送。

---

## 一、现状分析（项目能力盘点）

### 1.1 本项目已有的能力（可直接复用）

| 能力 | 对应代码 | 说明 |
|------|---------|------|
| 登录态管理 | `xhs_utils/xhs_pc/auth.py`（`XHSPcAuth`） | 支持 `cookie` / `qrcode` / `phone` 三种方式，无需浏览器 |
| 获取用户全部笔记 | `apis/xhs_pc_apis.py::get_user_all_notes(user_url)` | 翻页拉取指定用户所有笔记，含 xsec_token |
| 获取笔记详情 | `apis/xhs_pc_apis.py::get_note_info(url)` | 标题、正文、话题、点赞/收藏/评论数、无水印图片/视频 |
| 数据结构化 | `xhs_utils/data_util.py::handle_note_info` | 统一笔记字段：`note_id, title, desc, type, liked_count, collected_count, comment_count, share_count, time, ip, nickname, ...` |
| 保存 Excel | `xhs_utils/data_util.py::save_to_xlsx` | openpyxl 生成 xlsx |
| 下载媒体 | `xhs_utils/data_util.py::download_note` | 无水印图片/视频落盘 |
| 签名算法 | `xhs_utils/xhs_core/js/`（Node.js 本地纯算） | 请求自动携带 x-s / x-t / x-s-common，无需人工干预 |
| 代理支持 | 所有 API 的 `proxies` 参数 | 降低风控风险 |

### 1.2 项目缺失、需要新建的部分

| 缺失能力 | 建议方案 |
|---------|---------|
| 竞品账号清单配置 | YAML/JSON 配置文件（watchlist） |
| 增量采集与去重 | SQLite 存储已见笔记（note_id 为主键），每次只拉新 |
| 历史数据沉淀 | SQLite（便于统计互动增长趋势）+ 原始 JSON 归档 |
| HTML 报告生成 | Jinja2 模板渲染（表格 + 摘要 + 趋势） |
| 邮件发送 | smtplib（QQ/163 邮箱 SMTP + 授权码），Excel 为附件、HTML 内嵌正文 |
| 定时调度 | cron / systemd timer / Windows 计划任务（Linux 推荐 cron，最稳） |
| Cookie 健康巡检 | 每次运行前调 `get_user_me` 校验登录态，失效立即邮件告警 |
| 限速与重试 | 请求间随机 sleep（5~15s）+ 失败指数退避重试 |

---

## 二、总体架构

```
┌────────────┐    ┌─────────────────────────────────────────────┐
│ cron 定时   │───►│  collect.py  采集调度入口（每日 08:00 触发）   │
└────────────┘    └──────────────────┬──────────────────────────┘
                                     │
                    1. Cookie 健康检查（get_user_me，失效→告警邮件并终止）
                    2. 读取 watchlist.yaml 竞品清单
                    3. 逐账号 get_user_all_notes（增量比对 SQLite）
                    4. 新笔记 → get_note_info 拉详情 → 下载媒体（可选）
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼
              SQLite 持久化     JSON 详情归档      Excel 汇总表
                    │                │                │
                    └────────┬───────┴────────────────┘
                             ▼
                   report.py 生成 HTML 报告（Jinja2）
                             │
                             ▼
                   mailer.py 发送邮件（HTML 正文 + xlsx 附件）
                             │
                             ▼
              logs/ 运行日志（loguru），异常自动邮件告警
```

**目录规划（在项目内新增）：**

```
Spider_XHS/
├── monitor/                      # 新增：竞品监控模块
│   ├── __init__.py
│   ├── config.py                 # 读取配置
│   ├── collect.py                # 采集主流程（增量）
│   ├── report.py                 # HTML/Excel 报告生成
│   ├── mailer.py                 # 邮件发送
│   ├── templates/
│   │   ├── report.html.j2        # 报告模板
│   │   └── alert.html.j2         # Cookie失效/异常告警模板
│   └── run.py                    # 一键入口：python -m monitor.run
├── data/                         # 输出（gitignore）
│   ├── monitor.db                # SQLite
│   ├── excel/YYYY-MM-DD.xlsx
│   ├── notes/<note_id>/          # JSON 详情 + 媒体
│   └── reports/YYYY-MM-DD.html
├── logs/
├── watchlist.yaml                # 竞品清单
├── .env                          # COOKIES + SMTP 配置
└── ...
```

---

## 三、关键设计决策

### 3.1 采集策略：增量 + 全量兜底

- **增量**：以 `note_id` 为主键存 SQLite，每次只处理新笔记。首次运行全量，之后每次只拉各竞品第一页~若干页即可判断有无新内容，**大幅降低请求量和风控风险**（这是"稳定"的核心）。
- 翻页终止条件：当前页全部 note_id 已存在 → 停止翻页。
- 每次运行后记录各账号笔记总数/最新发布时间，用于监控账号是否被风控拉黑（连续多次无新内容且总笔记数变化异常 → 告警）。

### 3.2 稳定性保障（重点）

| 措施 | 具体做法 |
|------|---------|
| 限速 | 账号间 sleep 60~120s；笔记详情间 sleep 5~15s 随机；单次运行每账号详情上限（如 30 条） |
| 重试 | `retry` 库 + 指数退避；单条失败跳过不中断整体流程，失败清单进报告 |
| Cookie 管理 | ① 运行前健康检查；② Cookie 预计 30 天左右失效，失效时告警邮件提醒人工换新；③ 建议定期（如每 2 周）在浏览器重新登录小红书复制新 Cookie，写入 `.env` |
| 日志 | loguru 落盘 `logs/`，按天滚动；每次运行生成运行摘要（新增 N 条 / 失败 M 条 / 耗时） |
| 失败兜底 | 采集失败不影响上次数据；报告标注数据截止时间 |
| 单账号 Cookie | 只用**一个**账号的登录态做采集（不要多账号轮换高频请求，反而更稳） |

### 3.3 登录方式选择

- **首选 `cookie` 模式**：日常浏览器登录小红书后 F12 复制完整 Cookie 到 `.env`。最简单、与项目 `COOKIES` 配置天然契合。
- 备选 `qrcode` 模式：`XHSPcAuth.from_qrcode_login()` 可无浏览器扫码，但项目当前入口在 `spider/spider.py`，监控模块需在首次运行时单独调用一次以生成 Cookie 并保存。

### 3.4 数据组织（表格 + 文件）

| 输出 | 内容 | 用途 |
|------|------|------|
| SQLite `monitor.db` | `notes` 表（全量历史，含各期互动数快照表 `note_metrics`） | 去重 + 增长趋势分析 |
| Excel（每次运行） | 本期所有竞品新笔记 + 各账号汇总 sheet | 附件 |
| JSON 详情归档 | 每条新笔记完整原始数据 `data/notes/<note_id>/note.json` | 可追溯、可二次加工 |
| 媒体文件（可选开关） | 无水印图片下载到 `data/notes/<note_id>/images/` | 需要分析封面时开启 |
| HTML 报告 | 账号对比摘要 + 新笔记明细表 + 封面缩略图 + 数据趋势 | 邮件正文 |

### 3.5 邮件方案

- `smtplib` + `email.mime`，QQ 邮箱 / 163 / 企业邮箱均可（SMTP + 授权码，写入 `.env`，不进 git）。
- 正文：内嵌 HTML 报告（精简版，图片用 CID 附件或直接外链笔记封面 URL）；附件：xlsx 汇总表 + 完整 HTML 报告。
- 两类邮件：**日报/周报**（正常推送）与 **告警**（Cookie 失效、运行异常、疑似风控）。

### 3.6 定时方案（推荐顺序）

1. **cron（Linux/WSL，推荐）**：`0 8 * * * cd /home/yefu/Spider_XHS && /usr/bin/python3 -m monitor.run >> logs/cron.log 2>&1`
   - 建议每天 1 次（如早 8 点）。竞品发布频率不高，日更足够；低频可选每周一、四。
2. systemd timer：日志与失败重跑策略更完善，服务器部署推荐。
3. APScheduler 常驻进程：适合后续扩展实时监控（关键词监控、评论监控）时再上。

---

## 四、分阶段实施计划

### Phase 0：环境就绪（0.5 天）
- [ ] `pip install -r requirements.txt && npm install`（Node 20+ / Python 3.10+）
- [ ] 手动验证项目可用：配置 Cookie → `python -m spider.spider` 拉一个测试用户的笔记，确认 Excel 正常产出
- [ ] 确认竞品账号主页 URL 清单（`https://www.xiaohongshu.com/user/profile/<user_id>`）

### Phase 1：配置与采集模块 `monitor/`（1 天）
- [ ] `watchlist.yaml`：竞品账号列表（name / user_id / 备注）、采集参数（每账号最大详情数、是否下载图片）
- [ ] `.env` 扩展：`COOKIES`、`SMTP_HOST/PORT/USER/PASS`、`MAIL_TO`
- [ ] `collect.py`：
  - 初始化 SQLite（notes / note_metrics / run_history 三张表）
  - Cookie 健康检查（`get_user_me`）
  - 逐账号 `get_user_all_notes` → 增量比对 → 新笔记 `get_note_info` → `handle_note_info` 入库
  - 随机限速 + 重试 + 失败收集
- [ ] 单账号冒烟测试

### Phase 2：报告与邮件（1 天）
- [ ] `report.py`：Jinja2 渲染 HTML（摘要卡片区：各竞品本期新发数量、总互动；明细表：标题/类型/发布时间/点赞/收藏/评论/链接；趋势区：与上期对比）；Excel 生成（复用/扩展 `save_to_xlsx`）
- [ ] `mailer.py`：HTML 正文 + xlsx 附件 + 告警邮件模板
- [ ] 本地打开 HTML 报告验收

### Phase 3：调度与运维（0.5 天）
- [ ] `run.py` 一键入口，统一异常捕获 → 任何未捕获异常发告警邮件
- [ ] 配置 crontab，连续观察 3~7 天运行日志
- [ ] `.gitignore` 补充 data/、logs/、.env
- [ ] 编写 README_monitor.md（换 Cookie 操作手册 —— 这是最常见的日常维护动作）

### Phase 4（可选增强，后续迭代）
- [ ] 互动数趋势：每期快照各笔记点赞/收藏，画出竞品爆款曲线，识别其高互动选题规律
- [ ] 关键词监控：复用 `search_some_note` 监控品类关键词最新笔记（与账号监控互补）
- [ ] 推送渠道扩展：Server酱 / 企业微信机器人 / ntfy（比邮件更即时，配合告警很合适）
- [ ] 多渠道报告存档：数据同步到飞书表格 / Notion 等

---

## 五、风险与对策

| 风险 | 等级 | 对策 |
|------|------|------|
| Cookie 失效导致采集中断 | 高 | 运行前健康检查 + 失效即时告警 + 书面化换 Cookie 手册；预估 2~4 周更换一次 |
| 账号被风控/封禁 | 中高 | 增量采集降低请求量、随机限速、可配代理（`proxies`）、单账号低频使用；**不要用主力账号**，准备专用小号 |
| 接口/签名变动导致项目失效 | 中 | 本项目更新较活跃，定期 `git pull` 上游；采集模块与 API 层解耦，便于适配 |
| 邮件被判垃圾 | 低 | 固定主题格式、控制附件大小、发送频率与定时一致 |
| 合规 | — | 项目声明"仅供学习交流，禁止商业化"；采集数据仅内部竞品分析使用，不对外分发、不用于转载发布 |

## 六、里程碑

| 阶段 | 交付物 | 预计耗时 |
|------|--------|---------|
| Phase 0 | 环境跑通 + Cookie 就绪 | 0.5 天 |
| Phase 1 | monitor/collect.py 增量采集可用 | 1 天 |
| Phase 2 | HTML 报告 + 邮件发送可用 | 1 天 |
| Phase 3 | cron 上线 + 7 天稳定观察 | 0.5 天 + 1 周 |
| 合计 | 可交付的自动监控体系 | 约 3 天开发 |

## 七、更优方案建议（供选择）

1. **增量报告优于全量**：每次只报"新笔记 + 互动变化"，比全量堆砌实用得多（本计划已采用）。
2. **加一层互动趋势跟踪**：竞品价值不只在"发了什么"，更在"什么内容火了"。对每条笔记做互动数快照，能自动发现竞品爆款并分析选题规律 —— 这是纯采集做不到的核心增量价值。
3. **告警渠道用 IM（企业微信/Server酱）+ 日报用邮件**：紧急的事（Cookie 失效）走 IM 秒达，例行的报告走邮件，体验更好。
4. **若竞品数量 > 20 或需要分钟级时效**：再考虑常驻进程 + APScheduler + 代理池；当前规模下 cron + 增量是最稳、维护成本最低的形态，不建议过度设计。
