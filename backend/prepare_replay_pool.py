"""Download raw evidence for the declared sample pool, without selecting on returns."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import akshare as ak
import urllib.request

ROOT = Path(__file__).resolve().parents[1] / 'data' / 'replay'
POOL = {'000876': '新希望', '600010': '包钢股份'}
EVIDENCE = {
    '000876': {
        'industry': '农牧',
        'documents': [
            {'title': '新希望2024年年度报告摘要', 'published_date': '2025-04-26', 'id': '1223314073'},
            {'title': '新希望2024年年度分红派息实施公告', 'published_date': '2025-07-18', 'id': '1224203220'},
        ],
        'dividends': [{'record_date': '2025-07-24', 'ex_date': '2025-07-25', 'pay_date': '2025-07-25',
                       'gross_per_share': 0.0241245, 'reference_adjustment': 0.0241245}],
    },
    '600010': {
        'industry': '钢铁',
        'documents': [
            {'title': '包钢股份2024年年度报告摘要', 'published_date': '2025-04-19', 'id': '1223154528'},
            {'title': '包钢股份2024年年度权益分派实施公告', 'published_date': '2025-06-21', 'id': '1223952145'},
        ],
        'dividends': [{'record_date': '2025-06-26', 'ex_date': '2025-06-27', 'pay_date': '2025-06-27',
                       'gross_per_share': 0.002, 'reference_adjustment': 0.002}],
    },
}

def main():
    for code, name in POOL.items():
        folder = ROOT / code
        folder.mkdir(exist_ok=True)
        for adjust, filename in [('', 'price_daily.csv'), ('qfq', 'price_qfq_check.csv')]:
            path = folder / filename
            if not path.exists():
                frame = ak.stock_zh_a_hist(symbol=code, period='daily', start_date='20250101', end_date='20250831', adjust=adjust)
                if frame.empty:
                    raise ValueError('Empty prices: ' + code)
                frame.to_csv(path, index=False, encoding='utf-8-sig')
        notices_path = folder / 'announcement_index.csv'
        if not notices_path.exists():
            notices = ak.stock_zh_a_disclosure_report_cninfo(symbol=code, market='沪深京', category='', start_date='20250101', end_date='20250831')
            notices.to_csv(notices_path, index=False, encoding='utf-8-sig')
        else:
            import pandas as pd
            notices = pd.read_csv(notices_path)
        print(code, name, 'columns:', list(notices.columns), flush=True)
        print(notices[notices.astype(str).apply(lambda c: c.str.contains('权益分派实施|分红派息实施|年度报告摘要')).any(axis=1)].to_string(index=False), flush=True)
        meta = {'code': code, 'name': name, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                'sources': ['AKShare stock_zh_a_hist / 东方财富', 'AKShare stock_zh_a_disclosure_report_cninfo / 巨潮资讯'],
                'price_parameters': {'symbol': code, 'period': 'daily', 'start_date': '20250101', 'end_date': '20250831', 'adjust': ''},
                'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob('*.csv')}}
        (folder / 'download_manifest.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        documents = []
        for item in EVIDENCE[code]['documents']:
            url = f"https://static.cninfo.com.cn/finalpage/{item['published_date']}/{item['id']}.PDF"
            filename = item['id'] + '.pdf'
            if not (folder / filename).exists():
                with urllib.request.urlopen(url, timeout=40) as response:
                    content = response.read()
                if not content.startswith(b'%PDF'):
                    raise ValueError('Invalid PDF: ' + url)
                (folder / filename).write_bytes(content)
            documents.append({**item, 'file': filename, 'source_url': url})
        manifest = {
            **meta, 'adjust': '', 'industry': EVIDENCE[code]['industry'],
            'upstream': '东方财富 / AKShare stock_zh_a_hist', 'price_file': 'price_daily.csv',
            'documents': documents, 'dividends': EVIDENCE[code]['dividends'],
            'review_note': '按2025年1至8月公告索引核对现金分红实施；本股池不支持送转股或配股。摘要不替代完整年报。',
            'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.suffix in {'.csv', '.pdf'}},
        }
        (folder / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Verified-source replay pack prepared:', code, flush=True)

if __name__ == '__main__':
    main()
