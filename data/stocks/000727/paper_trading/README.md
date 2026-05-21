# 双票模拟盘：冠捷科技 + 山东玻纤

模拟区间：到 2026-05-29  
初始本金：冠捷科技 60000 元，山东玻纤 60000 元  
策略配置：`data/stocks/000727/active_strategy.json`、`data/stocks/605006/active_strategy.json`

## 当前规则

- 当前模拟冠捷科技(000727)和山东玻纤(605006)，两只股票独立账户、独立本金，不互相挪用现金。
- 每天收盘后用最新日线判断是否产生买入计划。
- 有买入计划时，次一交易日开盘执行。
- A 股 T+1：买入当天不卖出，次一交易日起处理止损、止盈和节前风控。
- 费用按模拟口径：
- 佣金万三，单笔最低 5 元。
- 卖出印花税 0.05%。
- 过户/小额规费按成交额 0.001% 双向估算。

## 更新命令

先同步最新行情：

```bash
python3 scripts/fetch_stock_history.py --code 000727 --name 冠捷科技 --window-years 2 --count 900 --end 2026-05-29
python3 scripts/fetch_stock_history.py --code 605006 --name 山东玻纤 --window-years 2 --count 900 --end 2026-05-29
```

再更新模拟盘：

```bash
python3 scripts/update_guanjie_paper_trade.py --code 000727 --name 冠捷科技 --as-of YYYY-MM-DD
python3 scripts/update_guanjie_paper_trade.py --code 605006 --name 山东玻纤 --as-of YYYY-MM-DD
```

如果是第一次重置账户：

```bash
python3 scripts/update_guanjie_paper_trade.py --code 000727 --name 冠捷科技 --reset --as-of 2026-05-19
python3 scripts/update_guanjie_paper_trade.py --code 605006 --name 山东玻纤 --reset --init-only --start-date 2026-05-21 --end-date 2026-05-29
```

## Python 自动化

不使用 Codex 自动化时，可以用项目内 Python 脚本生成固定时段提示。

手动生成提示。该脚本会同时生成两只股票的 `latest_signal.md`，收盘阶段会更新 `/my-positions/` 私密复盘密文；邮件提醒仍只保留冠捷科技模拟盘：

```bash
python3 scripts/guanjie_paper_automation.py --stage preopen
python3 scripts/guanjie_paper_automation.py --stage intraday
python3 scripts/guanjie_paper_automation.py --stage tail
python3 scripts/guanjie_paper_automation.py --stage close
```

安装 macOS 本地定时任务：

```bash
python3 scripts/install_guanjie_paper_launchd.py install
```

卸载 macOS 本地定时任务：

```bash
python3 scripts/install_guanjie_paper_launchd.py uninstall
```

定时任务时间：

- 09:25 盘前确认。
- 10:00 盘中盯盘。
- 11:25 午前盯盘。
- 14:30 午后盯盘。
- 14:55 尾盘风控。
- 15:45 收盘策略与入账。

## 输出文件

- `account.json`：当前账户状态。
- `journal.csv`：每日动作流水。
- `latest_signal.md`：最新一条交易提示。
- `signals/`：历史提示归档。
- 合并邮件备份：`data/stocks/paper_trading/emails/`。
- 私密复盘密文：`encrypted/my/YYYY-MM-DD.json`。

## 目前还需要补的数据

- 2026-05-20 到 2026-05-29 的每日收盘日线数据。
- 如果要更精确处理盘中止损/止盈先后顺序，需要分钟级数据；当前版本只用日线 OHLC，按保守口径处理。
- 如果真实券商佣金不是万三或最低 5 元，需要更新脚本里的费用模型。
