# 冠捷科技(000727)历史行情数据

数据用途：后续只围绕冠捷科技做入场判断、回测、量价观察和交易纪律验证。

## 文件说明

- `daily_qfq_1y.csv`：近一年日线，前复权，含 OHLC、成交量、成交额、换手率、涨跌幅、振幅、均线、20/60 日高低点。
- `daily_bfq_1y.csv`：近一年日线，不复权，字段同上。
- `weekly_qfq_1y.csv`：近一年周线，前复权。
- `monthly_qfq_1y.csv`：近一年月线，前复权。
- `daily_qfq_1y.json`：前复权日线 JSON，方便前端或脚本直接读取。
- `latest_quote.json`：腾讯实时行情快照，盘中会变化。
- `metadata.json`：数据范围、来源、抓取时间和校验信息。
- `active_strategy.json`：当前生效的冠捷科技量化策略配置，供后续信号生成和回测复用。
- `active_strategy.md`：当前生效策略的人读版说明，记录入场、卖出、节前风控和后续修改原则。

## 更新命令

```bash
python3 scripts/fetch_guanjie_history.py --end 2026-05-19
```

不传 `--end` 时默认使用当天日期。

## 注意

如果最后一行日期等于实时行情日期，`bar_status` 会标记为 `intraday`，表示这是盘中快照，不应直接当作完整收盘 K 线用于回测。
