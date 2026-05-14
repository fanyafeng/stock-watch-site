# A股技术形态观察池

这是一个按日期聚合、按博主/来源人组织的轻量级股票复盘工作台。站点使用 Astro 构建，通过 GitHub Actions 生成每日综合复盘、加密页面并部署到 GitHub Pages。

网站首页展示公开的每日大盘看板、来源人概要、综合筛选摘要和评论概览；具体复盘详情页才需要输入密码。每天默认只生成一个 `daily_YYYY-MM-DD` 综合复盘工作台页面。详情正文在构建流程中临时生成到 `build/tmp/`，随后加密写入 `encrypted/articles/`，Astro 页面只内嵌密文 payload，用户在浏览器中输入文章密码后本地解密查看。

## 当前来源

- 野哥：`yege`
- 李红娟：`lihongjuan`
- 王多于：`wangduoyu`
- 龙哥：`longge`

来源配置在 `data/source_config.json`，默认会读取 `default_sources` 中所有 `enabled=true` 的来源并生成同一天的综合复盘工作台。

## 项目结构

- `data/source_config.json`：来源配置。
- `data/reports.json`：每日工作台索引，不包含正文和密码。
- `data/dashboard.json`：公开首页看板数据，不包含文章密码。
- `data/dashboards/YYYY-MM-DD.json`：公开看板的按日期快照，供评论聚合历史日期页使用。
- `data/sources/{source}/picks/YYYY-MM-DD.csv`：来源当日选股数据。
- `data/sources/{source}/holdings/YYYY-MM-DD.csv`：来源当日持仓数据。
- `data/sources/{source}/posts/YYYY-MM-DD.csv`：可选，来源当日帖子、图文、视频摘要。
- `data/daily/YYYY-MM-DD/market.csv`：可选，大盘信息与今日总览。
- `data/daily/YYYY-MM-DD/timeline.csv`：可选，盘中时间线。
- `data/daily/YYYY-MM-DD/comments.csv`：可选，有价值评论聚合。
- `data/my/positions/YYYY-MM-DD.csv`：我的个人持仓数据，独立于四个来源人。
- `data/my/operations/YYYY-MM-DD.csv`：我的个人操作记录，独立于四个来源人。
- `data/templates/`：可选 CSV 模板。
- `build/tmp/`：临时明文报告目录，已在 `.gitignore` 中忽略。
- `encrypted/articles/`：加密后的文章 payload，可提交。
- `encrypted/my/`：我的持仓 / 操作记录密文 payload，可提交。
- `src/data/reports.json`：同步给 Astro 使用的文章索引。
- `src/data/dashboard.json`：同步给 Astro 使用的公开看板数据。
- `src/data/dashboards/YYYY-MM-DD.json`：同步给 Astro 使用的按日期公开看板快照。
- `src/data/my_positions_index.json`：同步给 Astro 使用的我的持仓密文索引。
- `src/pages/`：Astro 页面。
- `scripts/generate_report.py`：读取 CSV 并生成临时明文 HTML 报告。
- `scripts/encrypt_article.py`：按文章日期生成密码并加密报告。
- `scripts/sync_reports_to_astro.py`：校验密文 payload 并同步索引。
- `scripts/import_yeren_backup.py`：从本机 `yeren_signal_monitor` 真实备份导入历史帖子、评论、截图、市场和信号 CSV。

## picks CSV 字段

文件路径：`data/sources/{source}/picks/YYYY-MM-DD.csv`

字段：

```csv
source,date,code,name,type,pattern,logic,entry_low,entry_high,stop_loss,take_profit_1,take_profit_2,trend_score,breakout_score,pullback_score,volume_score,risk_reward_score,risk_score,status,risk,raw_text,note
```

说明：

- `source`：来源 id，例如 `yege`、`lihongjuan`、`wangduoyu`、`longge`。
- `date`：日期，格式 `YYYY-MM-DD`。
- `type`：`short` 或 `mid`。
- `pattern`：技术形态标签，例如 `底部突破`、`右侧转强`、`中继回踩`、`缩量整理`。
- `entry_low`、`entry_high`：入场区间。
- `stop_loss`、`take_profit_1`、`take_profit_2`：止损位与止盈位。
- `trend_score`、`breakout_score`、`pullback_score`、`volume_score`、`risk_reward_score`、`risk_score`：评分字段。
- `status`：`等待买点`、`已触发`、`观察取消`。
- `risk`：`低`、`中`、`高`。
- `raw_text`、`note`：原始描述与补充备注。

如果 picks 文件不存在，或只有表头没有数据，脚本会报错，不会生成随机 mock 推荐。

## holdings CSV 字段

文件路径：`data/sources/{source}/holdings/YYYY-MM-DD.csv`

字段：

```csv
source,date,code,name,position_type,cost_price,current_price,position_ratio,holding_days,profit_loss_pct,status,plan,stop_loss,take_profit_1,take_profit_2,risk,raw_text,note
```

说明：

- `position_type`：`短线`、`中线`、`长线`、`观察仓`。
- `current_price`、`holding_days`、`profit_loss_pct` 可以为空。
- `status`：`持有`、`减仓`、`加仓观察`、`止盈观察`、`止损观察`、`已清仓`。
- holdings 文件必须存在；可以只有表头。为空时报告展示“今日未记录公开持仓或持仓数据为空”。

## 可选复盘 CSV

每日综合工作台还支持以下可选 CSV。默认 loose 模式下缺失不会报错，页面会显示“暂无数据”；如果希望缺失即失败，可以运行 `python scripts/generate_report.py --all --strict-extra --date YYYY-MM-DD`。

大盘信息：`data/daily/YYYY-MM-DD/market.csv`

```csv
section,value,note
```

`section` 建议使用：`market_status`、`main_sectors`、`risk_level`、`operation_tone`、`index_status`、`volume_change`、`index_money_flow_series`、`sector_rotation`、`accumulation_direction`、`sector_first_limit_up`、`capital_preference`、`sentiment_cycle`、`risk_signal`、`tomorrow_watch`。

`sector_first_limit_up` 用于“局部抢筹线索”的首封股/最先涨停股，格式为 `板块=股票(代码);板块=股票(代码)`。如果没有首封时间或最先涨停数据，请留空，页面会显示“首封股待补充”，不要用普通领涨股或评论提到的股票代替。

`index_money_flow_series` 用于“指数主力净流(合计)”右侧曲线，格式为 `09:31=-2.34;09:32=1.18`，单位为亿元，含义是核心三指数逐分钟主力净流合计。可以用脚本自动补充：

```bash
python scripts/fetch_market_flow.py --date 2026-05-14 --mode loose
```

脚本会优先保留同花顺主力净流扩展点；如果没有稳定公开接口，则使用东方财富逐分钟主力资金流公开数据补充。拉取失败时 loose 模式不会阻塞构建，页面会显示“资金分时待补充”。

时间线：`data/daily/YYYY-MM-DD/timeline.csv`

```csv
time,category,source,title,content,related_stocks,related_sectors,note
```

`category` 建议使用：`market_node`、`sector_rotation`、`accumulation`、`yege_post`、`lihongjuan_post`、`wangduoyu_video`、`longge_video`、`valuable_comment`、`after_close`。

来源帖子/视频：`data/sources/{source}/posts/YYYY-MM-DD.csv`

```csv
source,date,channel,title,url,image,summary,mentioned_stocks,mentioned_sectors,raw_text,note
```

有价值评论：`data/daily/YYYY-MM-DD/comments.csv`

```csv
date,source,comment_source,content,mentioned_stocks,mentioned_sectors,value_reason,include_in_logic,note
```

模板文件在 `data/templates/`，可以复制后改成真实数据。

## 我的持仓 / 操作记录

`/my-positions/` 是个人私密 Tab，和四个博主来源数据分开管理。进入页面后默认只显示密码输入框，密码正确后才在浏览器本地解密展示我的持仓和操作记录；刷新页面后需要重新输入。

个人持仓路径：`data/my/positions/YYYY-MM-DD.csv`

```csv
date,code,name,position_type,cost_price,current_price,position_ratio,holding_days,profit_loss_pct,status,plan,stop_loss,take_profit_1,take_profit_2,risk,note
```

个人操作记录路径：`data/my/operations/YYYY-MM-DD.csv`

```csv
date,time,action,code,name,price,volume_ratio,reason,plan,stop_loss,take_profit,result,note
```

加密输出路径：`encrypted/my/YYYY-MM-DD.json`

我的持仓 Tab 使用独立固定密码：`xiaofan666888`。这个密码独立于每日复盘文章密码；每日复盘文章仍然使用 `xiaofan + (12 - 当前月份，两位数字) + 日期日号两位数字`。

本地生成命令：

```bash
python scripts/encrypt_my_positions.py --date 2026-05-12 --mode strict
```

`strict` 模式下缺少 `positions` 或 `operations` 文件会报错；GitHub Actions 默认使用 `loose` 模式：

```bash
python scripts/encrypt_my_positions.py --mode loose
```

因此你不一定每天都上传个人持仓，缺少个人数据时不会影响整站构建，页面解锁后会显示“今日未上传个人持仓 / 今日未上传操作记录”。

## 页面结构

公开工作台入口：

- `/`：每日复盘首页，展示今日总览、时间线、来源人概要、综合筛选和评论概览。
- `/market/`：大盘分析页，展示指数表现、市场资金、板块轮动、量能、情绪和明日关注方向。
- `/sources/`：来源人详情页，展示野哥、李红娟、王多于、龙哥的公开摘要、推荐、持仓和历史概览。
- `/comments/`：评论聚合页，默认展示最新公开看板。
- `/comments/YYYY-MM-DD/`：按日期查看评论聚合，例如 `/comments/2026-05-11/`、`/comments/2026-05-13/`。
- `/my-positions/`：我的持仓 / 操作记录私密页，使用独立密码解锁。
- `/articles/daily_YYYY-MM-DD/`：加密复盘详情页，只有这里需要输入文章密码。

解密后的 `daily_YYYY-MM-DD` 页面是一个“按日期聚合的股票复盘工作台”，包含：

- 今日总览：日期、更新时间、今日市场状态、今日主线板块、今日风险等级、今日操作基调。
- 今日时间线：大盘关键节点、板块轮动变化、抢筹方向、四个来源人的发帖/视频、有价值评论、盘后总结。
- 大盘信息：指数状态、成交量变化、板块轮动、抢筹方向、资金偏好、情绪周期、风险信号、明日观察方向。
- 来源人板块：野哥、李红娟、王多于、龙哥的帖子/视频、图片/截图、原文摘要、今日推荐、个人持仓、有价值评论。
- 综合筛选结果：短期观察 3 只、中长期观察 3 只，并展示来源人列表、入场区间、止损位、止盈位、盈亏比、风险等级与入选理由。
- 有价值评论聚合：评论来源、评论内容、提到的股票/板块、价值原因、是否纳入推荐逻辑。
- 操作纪律与风险提示。

## 本地运行

生成每日综合复盘工作台：

```bash
python scripts/generate_report.py --all --date 2026-05-12
python scripts/encrypt_article.py --all --date 2026-05-12
python scripts/sync_reports_to_astro.py
npm run build
npm run preview
```

日常默认命令会读取当天日期并生成一个 `daily_YYYY-MM-DD` 页面：

```bash
python scripts/generate_report.py --all
python scripts/encrypt_article.py --all
python scripts/sync_reports_to_astro.py
npm run build
```

如果需要兼容旧的单来源文章，可以显式指定来源：

```bash
python scripts/generate_report.py --source lihongjuan --date 2026-05-12
python scripts/encrypt_article.py --source lihongjuan --date 2026-05-12
python scripts/sync_reports_to_astro.py
```

## 导入历史备份

如果本机存在同级目录 `../yeren_signal_monitor`，可以从真实备份导入历史数据：

```bash
python scripts/import_yeren_backup.py --date 2026-05-11 --date 2026-05-12 --date 2026-05-13
```

该脚本会导入：

- 野哥同花顺帖子、评论备份和本地截图到 `data/sources/yege/posts/`、`data/daily/YYYY-MM-DD/comments.csv`、`public/media/YYYY-MM-DD/yege/`。
- 李红娟群聊报告到 `data/sources/lihongjuan/posts/` 和评论聚合。
- 王多于、龙哥抖音视频和评论聚合到对应来源目录。
- 大盘复盘 JSON 到 `data/daily/YYYY-MM-DD/market.csv`。
- 当日可解析信号到 `data/sources/{source}/picks/YYYY-MM-DD.csv`。

导入脚本不会生成随机推荐。某来源当天没有可解析真实选股时，只会写入空表头 CSV；生成历史页面时可使用：

```bash
python scripts/generate_report.py --all --date 2026-05-13 --loose-source-data
```

`--loose-source-data` 只建议用于历史导入或补档场景。日常生成不加这个参数，缺少 picks/holdings 仍会明确报错，避免漏数据时悄悄生成空页面。

导入后生成 5 月 11 日到 13 日的完整流程：

```bash
for d in 2026-05-11 2026-05-12 2026-05-13; do
  python scripts/generate_report.py --all --date "$d" --loose-source-data
  python scripts/encrypt_article.py --date "$d"
done
python scripts/sync_reports_to_astro.py
npm run build
```

## 每日文章密码规则

密码 = `xiaofan` + `(12 - 当前月份，两位数字)` + `日期日号两位数字`

示例：

- 1月5日：`xiaofan1105`
- 5月12日：`xiaofan0712`
- 12月31日：`xiaofan0031`

这个规则是为了个人查看方便，不是真正的强访问控制。密码规则泄露后，需要重新设计规则并重新生成历史文章。

## 选股逻辑

第一版只读取 CSV 数据源，不接真实行情接口。`generate_report.py` 使用可维护的评分模型：

```text
total_score = trend_score + breakout_score + pullback_score + volume_score + risk_reward_score - risk_score
```

过滤规则：

- 不追高，只等买点。
- 偏好右侧转强。
- 重视底部突破。
- 重视中继回踩。
- 必须有明确止损位。
- 注重盈亏比。
- `entry_low` 或 `entry_high` 缺失会剔除。
- `stop_loss` 缺失会剔除。
- `take_profit_1` 缺失会剔除。
- `risk_reward_score < 6` 会剔除。
- `risk_score >= 7` 会剔除。
- `status == 观察取消` 会剔除。

量价纪律会作为交易逻辑提示写入报告和股票池。可以在 picks CSV 的 `pattern`、`logic`、`raw_text`、`note` 字段中写入下列关键词，生成报告时会自动映射为对应动作：

- `低位无量`：低位无量要等，等错也要等。
- `高位无量`：高位无量要拿，拿错了也要拿。
- `低位放量`：低位放量要跟，跟错了也要跟。
- `高位放量`：高位放量要跑，跑错了也要跑。
- `量增价升`：量增价升要买入。
- `量增价减`：量增价减要卖出。
- `量增价平`：量增价平要转阴。
- `量平价升`：量平价升要加仓。
- `量平价跌`：量平价跌出局。
- `量减价升`：量减价升持有。

每日综合复盘会先对四个来源的候选项分别过滤，再按股票代码聚合同名标的；多来源共同提到会提高观察优先级，但仍必须满足入场区间、止损位、止盈位和盈亏比要求。推荐结果分为短期观察 TOP 3 和中长期观察 TOP 3，被过滤标的进入“剔除观察”并展示原因。

## GitHub Pages

推荐使用 GitHub Actions 部署 Pages：

`Settings → Pages → Build and deployment → Source` 选择 `GitHub Actions`。

工作流文件是 `.github/workflows/daily.yml`，支持手动触发 `workflow_dispatch`，也会在工作日北京时间 16:30 自动运行。GitHub Actions cron 使用 UTC，因此配置为 `30 8 * * 1-5`。

工作流在生成报告前会运行：

```bash
python scripts/fetch_market_flow.py --mode loose
```

用于补充大盘分析里的指数主力净流分时曲线；失败不影响整站构建。

手动运行方式：

1. 打开 GitHub 仓库的 `Actions` 页面。
2. 选择 `Daily encrypted stock watch site`。
3. 点击 `Run workflow`。

## 后续真实数据接入

当前 MVP 只读取 CSV。后续可以替换或扩展：

- 替换 `data/sources/{source}/picks/{date}.csv`。
- 替换 `data/sources/{source}/holdings/{date}.csv`。
- 补充 `data/sources/{source}/posts/{date}.csv`、`data/daily/{date}/market.csv`、`data/daily/{date}/timeline.csv`、`data/daily/{date}/comments.csv`。
- 补充 `data/my/positions/{date}.csv` 和 `data/my/operations/{date}.csv` 后运行 `encrypt_my_positions.py`。
- 替换 `generate_report.py` 的数据来源，接入 AkShare、TuShare、邮件解析或自定义策略输出。
- 邮件通知只发送站点文章链接，不发送明文正文。
- 增加历史收益跟踪、文章搜索、个股详情页、多来源聚合筛选、博主持仓历史追踪。

## 安全说明

- `encrypted/articles/` 中只有密文 payload。
- `encrypted/my/` 中只有我的持仓密文 payload。
- `dist/` 中不能包含明文报告。
- 不要提交 `build/tmp/` 明文报告。
- `data/reports.json` 和 `src/data/reports.json` 不包含正文和密码。
- 文章页只提示输入文章密码，不展示密码规则。
- 我的持仓页源码不包含个人持仓明文，也不显示独立密码。
- 这是静态加密，不是账号权限系统。
- 如果我的持仓密码泄露，需要更换密码并重新生成 `encrypted/my/` 下的数据。
- 如果需要真正的访问控制，后续可接 Cloudflare Access。
