"""Expand the existing pool to 100 cached historical stocks. No live quotes.

New dividend data is secondary-source data, not manually reviewed PDFs.
The prototype assumes cash is credited on ex-date (not verified payment date).
Split/rights/uncorroborated adjustment samples are rejected rather than fabricated.
"""
import csv
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import akshare as ak
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
CANDIDATES = '''600000 浦发银行 银行
600036 招商银行 银行
600016 民生银行 银行
600015 华夏银行 银行
600019 宝钢股份 钢铁
600028 中国石化 能源
600030 中信证券 证券
600031 三一重工 机械
600048 保利发展 地产
600050 中国联通 通信
600089 特变电工 电气设备
600104 上汽集团 汽车
600111 北方稀土 有色金属
600150 中国船舶 船舶
600161 天坛生物 医药
600176 中国巨石 建材
600183 生益科技 电子
600188 兖矿能源 能源
600196 复星医药 医药
600219 南山铝业 有色金属
600276 恒瑞医药 医药
600309 万华化学 化工
600346 恒力石化 化工
600406 国电南瑞 电气设备
600436 片仔癀 医药
600438 通威股份 光伏
600519 贵州茅台 食品饮料
600585 海螺水泥 建材
600588 用友网络 软件
600690 海尔智家 家电
600741 华域汽车 汽车
600795 国电电力 电力
600809 山西汾酒 食品饮料
600887 伊利股份 食品饮料
600900 长江电力 电力
601006 大秦铁路 交通运输
601088 中国神华 能源
601166 兴业银行 银行
601169 北京银行 银行
601288 农业银行 银行
601328 交通银行 银行
601398 工商银行 银行
601668 中国建筑 建筑
601766 中国中车 轨道交通
601800 中国交建 建筑
601818 光大银行 银行
601857 中国石油 能源
601888 中国中免 商贸
601988 中国银行 银行
000001 平安银行 银行
000333 美的集团 家电
000651 格力电器 家电
000725 京东方A 电子
000858 五粮液 食品饮料
600009 上海机场 交通运输
600011 华能国际 电力
600027 华电国际 电力
600066 宇通客车 汽车
600132 重庆啤酒 食品饮料
600660 福耀玻璃 汽车
000063 中兴通讯 通信
000100 TCL科技 电子
000157 中联重科 机械
000338 潍柴动力 机械
000425 徐工机械 机械
000538 云南白药 医药
000568 泸州老窖 食品饮料
000625 长安汽车 汽车
000630 铜陵有色 有色金属
000709 河钢股份 钢铁
000768 中航西飞 航空
000783 长江证券 证券
000792 盐湖股份 化工
000895 双汇发展 食品饮料
000938 紫光股份 电子
000963 华东医药 医药
000977 浪潮信息 计算机
002001 新和成 医药
002007 华兰生物 医药
002027 分众传媒 传媒
002049 紫光国微 电子
002050 三花智控 机械
002064 华峰化学 化工
002142 宁波银行 银行
002179 中航光电 电子
002180 纳思达 计算机
002202 金风科技 风电
002230 科大讯飞 软件
002236 大华股份 电子
002241 歌尔股份 电子
002271 东方雨虹 建材
002304 洋河股份 食品饮料
002311 海大集团 农牧
002352 顺丰控股 物流
002371 北方华创 电子
002415 海康威视 电子
002460 赣锋锂业 有色金属
002475 立讯精密 电子
002493 荣盛石化 化工
002601 龙佰集团 化工
002648 卫星化学 化工
002714 牧原股份 农牧
002736 国信证券 证券
600004 白云机场 交通运输
600018 上港集团 港口
600023 浙能电力 电力
600039 四川路桥 建筑
600061 国投资本 金融
600085 同仁堂 医药
600109 国金证券 证券
600118 中国卫星 航天
600153 建发股份 商贸
600170 上海建工 建筑
600177 雅戈尔 服装
600233 圆通速递 物流
600256 广汇能源 能源
600332 白云山 医药
600362 江西铜业 有色金属
600398 海澜之家 服装
600489 中金黄金 有色金属
600547 山东黄金 有色金属
600600 青岛啤酒 食品饮料
600674 川投能源 电力
600760 中航沈飞 航空
600886 国投电力 电力
601009 南京银行 银行
601021 春秋航空 航空运输
601100 恒立液压 机械
601111 中国国航 航空运输
601117 中国化学 建筑
601155 新城控股 地产
601225 陕西煤业 能源
601229 上海银行 银行
601360 三六零 软件
601377 兴业证券 证券
601600 中国铝业 有色金属
601607 上海医药 医药
601618 中国中冶 建筑
601628 中国人寿 保险
601688 华泰证券 证券
601699 潞安环能 能源
601728 中国电信 通信
601898 中煤能源 能源
601899 紫金矿业 有色金属'''


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cached_csv(path, fetch):
    if not path.exists():
        frame = fetch()
        if frame.empty:
            raise ValueError('empty dataset')
        frame.to_csv(path, index=False, encoding='utf-8-sig')
    return pd.read_csv(path)


def history(folder, code, adjust):
    symbol = ('sh' if code.startswith('6') else 'sz') + code
    path = folder / ('tencent_qfq_raw.json' if adjust else 'tencent_daily_raw.json')
    if not path.exists():
        response = requests.get('https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get',
                                params={'param': f'{symbol},day,2025-01-01,2025-08-31,640,{adjust}'}, timeout=40)
        response.raise_for_status()
        write(path, response.json())
    data = json.loads(path.read_text(encoding='utf-8'))['data'][symbol]
    rows = data.get(adjust + 'day', data.get('day', []))
    frame = pd.DataFrame([r[:6] for r in rows], columns=['日期','开盘','收盘','最高','最低','成交量'])
    for column in frame.columns[1:]:
        frame[column] = pd.to_numeric(frame[column])
    return frame[(frame['日期'] >= '2025-01-01') & (frame['日期'] <= '2025-08-31')]


def prepare(code, name, industry):
    folder = DATA / 'replay' / code
    folder.mkdir(parents=True, exist_ok=True)
    stamp = folder / 'retrieval.json'
    if not stamp.exists():
        write(stamp, {'retrieved_at': datetime.now(timezone.utc).isoformat(), 'akshare_version': ak.__version__})
    retrieval = json.loads(stamp.read_text(encoding='utf-8'))
    prices = cached_csv(folder / 'price_daily.csv', lambda: history(folder, code, ''))
    qfq = cached_csv(folder / 'price_qfq_check.csv', lambda: history(folder, code, 'qfq'))
    raw = folder / 'dividends_raw.json'
    if not raw.exists():
        response = requests.get('https://datacenter-web.eastmoney.com/api/data/v1/get', params={
            'reportName': 'RPT_SHAREBONUS_DET', 'columns': 'ALL',
            'filter': f'(SECURITY_CODE="{code}")', 'pageSize': 500, 'pageNumber': 1}, timeout=40)
        response.raise_for_status()
        write(raw, response.json())
    result = json.loads(raw.read_text(encoding='utf-8')).get('result')
    if not result or result.get('pages', 1) > 1:
        raise ValueError('missing/incomplete corporate-action response')
    events = []
    for item in result['data']:
        ex = str(item.get('EX_DIVIDEND_DATE', ''))[:10]
        if not '2025-01-01' <= ex <= '2025-08-31':
            continue
        if float(item.get('BONUS_IT_RATIO') or 0) != 0:
            raise ValueError('unsupported bonus/split event')
        amount = float(item.get('PRETAX_BONUS_RMB') or 0) / 10
        record = str(item.get('EQUITY_RECORD_DATE', ''))[:10]
        if not amount > 0 or not record < ex or len(record) != 10:
            raise ValueError('invalid dividend event')
        events.append(dict(record_date=record, ex_date=ex, pay_date=ex,
                           gross_per_share=amount, reference_adjustment=amount,
                           payment_date_assumption='测试模型假设除息日到账，未核验实际派息日'))
    events.sort(key=lambda d: d['ex_date'])
    dates = prices['日期'].tolist()
    if len(dates) != 161 or dates[0] != '2025-01-02' or dates[-1] != '2025-08-29' or dates != sorted(set(dates)):
        raise ValueError('requires complete 161-day historical sample')
    if qfq['日期'].tolist() != dates:
        raise ValueError('adjustment check dates mismatch')
    # qfq is used only to screen for corporate actions, never as execution prices.
    factors = qfq['收盘'] - prices['收盘']
    event_dates = {e['ex_date'] for e in events}
    for i in range(1, len(prices)):
        tolerance = .035
        if abs(float(factors.iloc[i] - factors.iloc[i-1])) > tolerance and dates[i] not in event_dates:
            raise ValueError(f'unexplained adjustment on {dates[i]}')
    for e in events:
        if e['record_date'] not in dates or e['ex_date'] not in dates:
            raise ValueError('dividend date not in sample')
    for row in prices.to_dict('records'):
        if not 0 < row['最低'] <= min(row['开盘'], row['收盘']) <= max(row['开盘'], row['收盘']) <= row['最高']:
            raise ValueError('invalid OHLC')
    manifest = dict(code=code, name=name, industry=industry, **retrieval, adjust='',
                    upstream='腾讯证券历史日线 / 东方财富分红送配数据中心',
                    price_file='price_daily.csv', documents=[], dividends=events,
                    price_parameters={'symbol': code, 'start_date': '20250101', 'end_date': '20250831', 'adjust': ''},
                    source_urls=[f'https://gu.qq.com/{"sh" if code.startswith("6") else "sz"}{code}',
                                 f'https://data.eastmoney.com/yjfp/detail/{code}.html'],
                    review_note='测试扩容样本：二级数据源；未逐份核验官方公告。税前分红假设除息日到账，除权参考价按每股现金分红简化。无真实交易。',
                    sha256={p.name: digest(p) for p in folder.iterdir() if p.suffix in {'.csv', '.json'} and p.name != 'manifest.json'})
    write(folder / 'manifest.json', manifest)


def snapshot(code, meta):
    folder = DATA / 'replay' if code == '601318' else DATA / 'replay' / code
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    with (folder / manifest.get('price_file', '601318_unadjusted.csv')).open(encoding='utf-8-sig') as f:
        daily = [dict(date=r['日期'], **{k: float(r[v]) for k, v in
                 [('open','开盘'),('close','收盘'),('high','最高'),('low','最低'),('volume','成交量')]}) for r in csv.DictReader(f)]
    target = DATA / 'snapshots' / f'{code}.json'
    original = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
    if original and not (DATA / 'pool_original_snapshots' / target.name).exists():
        write(DATA / 'pool_original_snapshots' / target.name, original)
    value = original if code == '601318' else {'fundamental': {}, 'news': [], 'official_documents': []}
    value.update(stock_code=code, stock_name=meta['name'], industry=meta['industry'], board='main',
                 daily=daily, latest_price=daily[-1]['close'], latest_date=daily[-1]['date'],
                 snapshot_date='2025-08-31', analysis_cutoff='2025-08-31', is_synthetic=False,
                 retrieved_at=manifest.get('retrieved_at', ''), data_source=manifest.get('upstream', '东方财富') + '（不复权，2025年1—8月固定样本）',
                 data_limitations='扩容样本仅行情与分红数据；未补充的基本面、新闻不作事实推断。',
                 historical_pool_manifest=str((folder / 'manifest.json').relative_to(ROOT)).replace('\\', '/'))
    write(target, value)


def main():
    selected = {'601318': {'name': '中国平安', 'industry': '保险', 'board': 'main'},
                '000876': {'name': '新希望', 'industry': '农牧', 'board': 'main'},
                '600010': {'name': '包钢股份', 'industry': '钢铁', 'board': 'main'}}
    active = DATA / 'stock_pool.json'
    if active.exists():
        selected = json.loads(active.read_text(encoding='utf-8'))
        backup = DATA / 'stock_pool_before_100.json'
        if not backup.exists():
            write(backup, selected)
    original_codes = set(selected)
    rejected = []
    for line in CANDIDATES.splitlines():
        if len(selected) == 100:
            break
        code, name, industry = line.split()
        if code in selected:
            continue
        try:
            prepare(code, name, industry)
            selected[code] = dict(name=name, industry=industry, board='main')
            print(f'OK {len(selected)}/100 {code} {name}', flush=True)
        except Exception as exc:
            rejected.append({'code': code, 'reason': str(exc)})
            print(f'SKIP {code}: {exc}', flush=True)
        time.sleep(.4)
    write(DATA / 'pool_import_status.json', {'count': len(selected), 'rejected': rejected})
    if len(selected) != 100:
        raise RuntimeError(f'Only {len(selected)} valid samples; existing active pool unchanged')
    for code, meta in selected.items():
        if code not in original_codes:
            snapshot(code, meta)
    write(DATA / 'stock_pool.json', selected)
    print('Activated 100 real historical snapshots and replay samples.', flush=True)


if __name__ == '__main__':
    main()
