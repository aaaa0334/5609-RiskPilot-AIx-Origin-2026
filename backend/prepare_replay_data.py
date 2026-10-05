"""Fetch isolated, unadjusted replay evidence; never overwrite the original pack."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import urllib.request
import akshare as ak

ROOT = Path(__file__).resolve().parents[1] / 'data' / 'replay'
URL = 'https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0619/2025061901148_c.pdf'

def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    csv_path = ROOT / '601318_unadjusted.csv'
    pdf_path = ROOT / '2024_dividend_implementation.pdf'
    if not csv_path.exists():
        frame = ak.stock_zh_a_hist(symbol='601318', period='daily', start_date='20250101', end_date='20250831', adjust='')
        if frame.empty:
            raise RuntimeError('No unadjusted prices returned')
        frame.to_csv(csv_path, index=False, encoding='utf-8-sig')
    if not pdf_path.exists():
        with urllib.request.urlopen(URL, timeout=45) as response:
            content = response.read()
        if not content.startswith(b'%PDF'):
            raise RuntimeError('Dividend source is not a PDF')
        pdf_path.write_bytes(content)
    manifest = {
        'code': '601318', 'adjust': '', 'upstream': '东方财富 / AKShare stock_zh_a_hist',
        'start': '2025-01-01', 'end': '2025-08-31',
        'retrieved_at': datetime.now(timezone.utc).isoformat(),
        'dividend_source': URL,
        'dividend': {'published_date': '2025-06-20', 'record_date': '2025-06-27', 'pay_date': '2025-06-30', 'gross_per_share': 1.62},
        'scope': '历史教育模拟。税前现金分红口径；未模拟个人持股期限差别化红利税。不是券商账单或策略有效性证明。',
        'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (csv_path, pdf_path)},
    }
    (ROOT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Replay evidence ready:', ROOT)

if __name__ == '__main__':
    main()
