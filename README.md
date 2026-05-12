# A股技术形态观察池

这是一个按博主/来源人组织的轻量级静态股票观察报告网站。站点使用 Astro 构建，通过 GitHub Actions 生成报告、加密文章并部署到 GitHub Pages。

网站只展示加密后的报告索引和文章页面。报告正文在构建流程中临时生成到 `build/tmp/`，随后加密写入 `encrypted/articles/`，Astro 页面只内嵌密文 payload，用户在浏览器中输入文章密码后本地解密查看。

## 当前来源

- 野哥：`yege`
- 李红娟：`lihongjuan`
- 王多于：`wangduoyu`
- 龙哥：`longge`

来源配置在 `data/source_config.json`，默认会生成 `default_sources` 中所有 `enabled=true` 的来源。

## 项目结构

- `data/source_config.json`：来源配置。
- `data/reports.json`：文章索引，不包含正文和密码。
- `data/sources/{source}/picks/YYYY-MM-DD.csv`：来源当日选股数据。
- `data/sources/{source}/holdings/YYYY-MM-DD.csv`：来源当日持仓数据。
- `build/tmp/`：临时明文报告目录，已在 `.gitignore` 中忽略。
- `encrypted/articles/`：加密后的文章 payload，可提交。
- `src/data/reports.json`：同步给 Astro 使用的文章索引。
- `src/pages/`：Astro 页面。
- `scripts/generate_report.py`：读取 CSV 并生成临时明文 HTML 报告。
- `scripts/encrypt_article.py`：按文章日期生成密码并加密报告。
- `scripts/sync_reports_to_astro.py`：校验密文 payload 并同步索引。

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

## 本地运行

生成单个来源：

```bash
python scripts/generate_report.py --source lihongjuan --date 2026-05-12
python scripts/encrypt_article.py --source lihongjuan --date 2026-05-12
python scripts/sync_reports_to_astro.py
npm run build
npm run preview
```

生成所有来源：

```bash
python scripts/generate_report.py --all --date 2026-05-12
python scripts/encrypt_article.py --all --date 2026-05-12
python scripts/sync_reports_to_astro.py
npm run build
```

日常默认命令会读取当天日期：

```bash
python scripts/generate_report.py --all
python scripts/encrypt_article.py --all
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

推荐结果分为短线观察 TOP 3 和中线观察 TOP 3，被过滤标的进入“剔除观察”并展示原因。

## GitHub Pages

推荐使用 GitHub Actions 部署 Pages：

`Settings → Pages → Build and deployment → Source` 选择 `GitHub Actions`。

工作流文件是 `.github/workflows/daily.yml`，支持手动触发 `workflow_dispatch`，也会在工作日北京时间 16:30 自动运行。GitHub Actions cron 使用 UTC，因此配置为 `30 8 * * 1-5`。

手动运行方式：

1. 打开 GitHub 仓库的 `Actions` 页面。
2. 选择 `Daily encrypted stock watch site`。
3. 点击 `Run workflow`。

## 后续真实数据接入

当前 MVP 只读取 CSV。后续可以替换或扩展：

- 替换 `data/sources/{source}/picks/{date}.csv`。
- 替换 `data/sources/{source}/holdings/{date}.csv`。
- 替换 `generate_report.py` 的数据来源，接入 AkShare、TuShare、邮件解析或自定义策略输出。
- 邮件通知只发送站点文章链接，不发送明文正文。
- 增加历史收益跟踪、文章搜索、个股详情页、多来源聚合筛选、博主持仓历史追踪。

## 安全说明

- `encrypted/articles/` 中只有密文 payload。
- `dist/` 中不能包含明文报告。
- 不要提交 `build/tmp/` 明文报告。
- `data/reports.json` 和 `src/data/reports.json` 不包含正文和密码。
- 文章页只提示输入文章密码，不展示密码规则。
- 这是静态加密，不是账号权限系统。
- 如果需要真正的访问控制，后续可接 Cloudflare Access。
