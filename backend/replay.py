"""Point-in-time, long-only educational replay. No LLM or live account access."""
import csv
import hashlib
import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from replay_analysis import analyze_at

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'replay'
PACK = ROOT / 'data' / 'evidence' / '601318' / '2025-08-31'
router = APIRouter()
STOCKS = {
    '601318': {'name': '中国平安', 'industry': '保险'},
    '000876': {'name': '新希望', 'industry': '农牧'},
    '600010': {'name': '包钢股份', 'industry': '钢铁'},
}
if (ROOT / 'data' / 'stock_pool.json').exists():
    STOCKS = json.loads((ROOT / 'data' / 'stock_pool.json').read_text(encoding='utf-8'))
PINGAN_DIVIDENDS = [{'record_date': '2025-06-27', 'ex_date': '2025-06-30',
                     'pay_date': '2025-06-30', 'gross_per_share': 1.62, 'reference_adjustment': 1.6046}]


class Action(BaseModel):
    # None explicitly means keep existing shares, not rebalance to their old value.
    target_value: float | None = Field(default=None, ge=0, le=10000000, allow_inf_nan=False)


class ReplayRequest(BaseModel):
    stock_code: str = Field(default='601318', pattern=r'^\d{6}$')
    decision_mode: Literal['monthly', 'weekly'] = 'monthly'
    capital: float = Field(default=100000, ge=1000, le=10000000, allow_inf_nan=False)
    max_loss: float = Field(default=2000, gt=0, le=10000000, allow_inf_nan=False)
    actions: list[Action] = Field(default_factory=list, max_length=60)
    preview_target: float | None = Field(default=None, ge=0, le=10000000, allow_inf_nan=False)
    faction: str | None = Field(default=None, description='五行阵营：jin/mu/shui/huo/tu')

    @model_validator(mode='after')
    def validate_monthly_limit(self):
        if self.decision_mode == 'monthly' and len(self.actions) > 4:
            raise ValueError('快速体验最多四次选择')
        return self


# 阵营天赋配置
FACTION_TRAITS = {
    'jin': {'name': '金', 'icon': '🪙', 'trait': '亏损预算放宽10%', 'max_loss_multiplier': 1.1, 'fee_multiplier': 1.0, 'position_limit': 0.30},
    'mu': {'name': '木', 'icon': '🌳', 'trait': '持有超2关盈利+5%', 'max_loss_multiplier': 1.0, 'fee_multiplier': 1.0, 'position_limit': 0.30, 'holding_bonus': 0.05},
    'shui': {'name': '水', 'icon': '💧', 'trait': '交易手续费减半', 'max_loss_multiplier': 1.0, 'fee_multiplier': 0.5, 'position_limit': 0.30},
    'huo': {'name': '火', 'icon': '🔥', 'trait': '仓位上限提升至40%', 'max_loss_multiplier': 1.0, 'fee_multiplier': 1.0, 'position_limit': 0.40},
    'tu': {'name': '土', 'icon': '🛡️', 'trait': '强制清仓延后1关', 'max_loss_multiplier': 1.0, 'fee_multiplier': 1.0, 'position_limit': 0.30, 'stop_delay': 1},
}


def decision_nodes(rows, mode='monthly'):
    monthly = [max(r['date'] for r in rows if r['date'].startswith(f'2025-{m:02d}')) for m in range(4, 9)]
    if mode == 'monthly':
        return monthly
    if mode != 'weekly':
        raise ValueError('不支持的决策模式')
    # The first decision and final valuation are identical across modes.
    # The April starting week ends on Apr 30 because May 1-2 are holidays.
    weeks = {}
    for row in rows:
        if monthly[0] <= row['date'] <= monthly[-1]:
            key = date.fromisoformat(row['date']).isocalendar()[:2]
            weeks[key] = row['date']
    return sorted(set([monthly[0], *weeks.values(), monthly[-1]]))


def stock_folder(code):
    if code not in STOCKS:
        raise ValueError('该股票尚未纳入已核对的历史样本池')
    return DATA if code == '601318' else DATA / code


def verify_file_hash(path, expected):
    """Verify evidence files without treating Git line-ending conversion as corruption."""
    data = path.read_bytes()
    candidates = [data]
    if path.suffix.lower() in {'.csv', '.json'}:
        # Git commonly checks text out as CRLF on Windows and LF on Linux/Render.
        # The evidence is unchanged semantically, so accept either representation.
        lf = data.replace(b'\r\n', b'\n')
        candidates.extend((lf, lf.replace(b'\n', b'\r\n')))
    return any(hashlib.sha256(item).hexdigest() == expected for item in candidates)


def load_data(code='601318'):
    folder = stock_folder(code)
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['adjust'] != '':
        raise ValueError('连续账户模拟必须使用不复权行情')
    for name, expected in manifest['sha256'].items():
        if not verify_file_hash(folder / name, expected):
            raise ValueError('连续模拟证据校验失败，请检查数据文件')
    price_file = manifest.get('price_file', '601318_unadjusted.csv')
    with (folder / price_file).open(encoding='utf-8-sig', newline='') as f:
        rows = [dict(date=r['日期'], open=float(r['开盘']), close=float(r['收盘']),
                     high=float(r['最高']), low=float(r['最低']), volume=float(r['成交量'])) for r in csv.DictReader(f)]
    dates = [r['date'] for r in rows]
    if dates != sorted(set(dates)) or any(not (0 < r['low'] <= min(r['open'], r['close']) <= max(r['open'], r['close']) <= r['high']) for r in rows):
        raise ValueError('行情日期或价格校验失败')
    nodes = decision_nodes(rows)
    manifest['price_file'] = price_file
    manifest['dividends'] = manifest.get('dividends', PINGAN_DIVIDENDS if code == '601318' else [])
    return rows, nodes, manifest


def stock_options():
    options = []
    for code, meta in STOCKS.items():
        try:
            load_data(code)
            options.append({'code': code, **meta})
        except (ValueError, OSError, KeyError):
            # Never offer a broken/missing pack or silently use synthetic prices.
            continue
    return options


class DrawRequest(BaseModel):
    drawn: list[str] = Field(default_factory=list, max_length=200)
    industry: str | None = Field(default=None, max_length=20)


@router.get('/api/replay/stocks')
def replay_stocks():
    return {'stocks': stock_options(), 'note': '仅从已核对的真实历史样本池抽取；不代表荐股或全市场随机样本。'}


@router.post('/api/replay/draw')
def draw_stock(request: DrawRequest):
    options = stock_options()
    if request.industry:
        options = [stock for stock in options if stock['industry'] == request.industry]
    if not options:
        raise HTTPException(400, '暂无通过证据校验的样本，请检查数据文件')
    codes = {s['code'] for s in options}
    drawn = list(dict.fromkeys(c for c in request.drawn if c in codes))
    candidates = [s for s in options if s['code'] not in drawn]
    new_cycle = not candidates
    if new_cycle:
        candidates = [s for s in options if not drawn or s['code'] != drawn[-1]] or options
        drawn = []
    selected = secrets.choice(candidates)
    drawn.append(selected['code'])
    return {'stock': selected, 'drawn': drawn, 'remaining': len(options) - len(drawn), 'new_cycle': new_cycle}


def fees(qty, price, sell=False):
    if not qty:
        return 0.0
    value = qty * price
    return round(max(5, value * .00025) + value * .00001 + (value * .0005 if sell else 0), 2)


@dataclass
class Account:
    cash: float
    shares: int = 0
    basis: float = 0
    realized: float = 0
    dividends: float = 0
    total_fees: float = 0
    history: list = field(default_factory=list)
    ledger: list = field(default_factory=list)
    stop: dict | None = None
    fee_multiplier: float = 1.0

    def mark(self, date, price):
        self.history.append({'date': date, 'equity': round(self.cash + self.shares * price, 2)})

    def order(self, desired, price, date, blocked=False):
        delta = desired - self.shares
        if not delta:
            return {'date': date, 'kind': '保持', 'shares': 0, 'fee': 0, 'note': '保持原有股数'}
        if blocked:
            return {'date': date, 'kind': '未成交', 'shares': 0, 'fee': 0, 'note': '停牌/开盘触及交易限制或滑点价格超出日内区间；本轮不追单'}
        sell = delta < 0
        fill = round(price * (0.999 if sell else 1.001), 2)
        qty = abs(delta)
        if not sell:
            while qty > 0 and qty * fill + fees(qty, fill) * self.fee_multiplier > self.cash:
                qty -= 100
        if qty <= 0:
            return {'date': date, 'kind': '未成交', 'shares': 0, 'fee': 0, 'note': '现金不足以买入一手及支付费用'}
        charge = round(fees(qty, fill, sell) * self.fee_multiplier, 2)
        if sell:
            removed_basis = self.basis * qty / self.shares
            self.cash += qty * fill - charge
            self.realized += qty * fill - charge - removed_basis
            self.basis -= removed_basis
            self.shares -= qty
        else:
            self.cash -= qty * fill + charge
            self.basis += qty * fill + charge
            self.shares += qty
        self.cash = round(self.cash, 2)
        self.total_fees = round(self.total_fees + charge, 2)
        return {'date': date, 'kind': '减少持仓' if sell else '增加持仓', 'shares': qty,
                'price': fill, 'fee': charge, 'note': '按下一交易日开盘价加减0.1%假定滑点；现金不足时缩减数量'}


def summary(account, capital, budget, price):
    equity = round(account.cash + account.shares * price, 2)
    peak = capital
    mdd = 0
    mdd_pct = 0
    breaches = 0
    for point in account.history:
        peak = max(peak, point['equity'])
        mdd = max(mdd, peak - point['equity'])
        mdd_pct = max(mdd_pct, (peak - point['equity']) / peak * 100)
        breaches += int(point['equity'] < capital - budget)
    return dict(cash=account.cash, shares=account.shares, equity=equity,
                position_value=round(account.shares * price, 2),
                average_cost=round(account.basis / account.shares, 4) if account.shares else 0,
                realized=round(account.realized, 2), unrealized=round(account.shares * price - account.basis, 2),
                dividends=round(account.dividends, 2), fees=account.total_fees,
                pnl=round(equity - capital, 2), budget_headroom=round(equity - (capital - budget), 2),
                max_drawdown=round(mdd, 2), max_drawdown_pct=round(mdd_pct, 2), breach_days=breaches)


def simulate(rows, nodes, capital, actions, dividends=None, loss_budget=None, fee_multiplier=1.0,
             position_limit=None):
    dividends = PINGAN_DIVIDENDS if dividends is None else dividends
    account = Account(capital, fee_multiplier=fee_multiplier)
    start = next(i for i, r in enumerate(rows) if r['date'] == nodes[0])
    end = next(i for i, r in enumerate(rows) if r['date'] == nodes[len(actions)])
    account.mark(nodes[0], rows[start]['close'])
    entitled = {}
    schedules = {nodes[i]: a for i, a in enumerate(actions)}
    for i in range(start + 1, len(rows)):
        if i > end and account.stop is None:
            break
        row, prev = rows[i], rows[i - 1]
        for event_id, dividend in enumerate(dividends):
            if row['date'] == dividend['pay_date'] and entitled.get(event_id, 0):
                gross = round(entitled[event_id] * dividend['gross_per_share'], 2)
                account.cash = round(account.cash + gross, 2)
                account.dividends += gross
                account.ledger.append({'date': row['date'], 'kind': '税前现金分红', 'amount': gross,
                                       'note': f"按{dividend['record_date']}收盘持股数，每股{dividend['gross_per_share']}元；未扣个人红利税"})
        forced = account.stop is not None
        if forced or prev['date'] in schedules:
            action = Action(target_value=0) if forced else schedules[prev['date']]
            desired = account.shares if action.target_value is None else int(action.target_value / prev['close'] / 100) * 100
            # Corporate-action reference adjustment, not the per-share cash entitlement.
            reference = prev['close'] - sum(d['reference_adjustment'] for d in dividends if d['ex_date'] == row['date'])
            fill = round(row['open'] * (1.001 if desired > account.shares else .999), 2)
            blocked = row['volume'] <= 0 or not row['low'] <= fill <= row['high']
            blocked |= desired > account.shares and row['open'] >= round(reference * 1.1, 2)
            blocked |= desired < account.shares and row['open'] <= round(reference * .9, 2)
            equity_before = account.cash + account.shares * prev['close']
            suggested_limit_value = equity_before * position_limit if position_limit is not None else None
            position_violation = bool(
                not forced and action.target_value is not None and
                suggested_limit_value is not None and action.target_value > suggested_limit_value + .01
            )
            event = account.order(desired, row['open'], row['date'], blocked)
            event['decision_date'] = prev['date']
            event['target_value'] = action.target_value
            event['requested_shares'] = desired
            event['position_violation'] = position_violation
            if suggested_limit_value is not None:
                event['suggested_position_limit_pct'] = round(position_limit * 100, 1)
                event['suggested_position_limit_value'] = round(suggested_limit_value, 2)
            if position_violation:
                event['note'] += f'；本次主动超过{position_limit*100:.0f}%建议仓位，已记录为纪律越界，但不拦截操作'
            if forced:
                event['kind'] = '强制清仓' if account.shares == 0 else '强制清仓未成交'
                event['note'] = '预算超限后，按下一可成交交易日开盘价减0.1%滑点模拟清仓。' if account.shares == 0 else '当日无法模拟成交，保持待清仓，下一交易日继续尝试。'
            account.ledger.append(event)
        for event_id, dividend in enumerate(dividends):
            if row['date'] == dividend['record_date']:
                entitled[event_id] = account.shares
        account.mark(row['date'], row['close'])
        if account.stop is None and loss_budget is not None and account.history[-1]['equity'] < round(capital - loss_budget, 2):
            account.stop = dict(message='累计亏损超过相对本金的初始预算，谢谢参与',
                                trigger_date=row['date'], trigger_loss=round(capital - account.history[-1]['equity'], 2),
                                status='pending', liquidation_date=None)
        if account.stop is not None and account.shares == 0:
            account.stop.update(status='cash', liquidation_date=row['date'])
            break
    return account


def available_documents(cutoff, code='601318'):
    if code != '601318':
        manifest = json.loads((stock_folder(code) / 'manifest.json').read_text(encoding='utf-8'))
        return [dict(title=d['title'], published_date=d['published_date'], url=f'/api/replay/document/{code}/{i}')
                for i, d in enumerate(manifest['documents']) if d['published_date'] <= cutoff]
    source = json.loads((PACK / 'official_documents.json').read_text(encoding='utf-8'))
    docs = [dict(title=d['title'], published_date=d['published_date'], url=f'/api/replay/document/{i}')
            for i, d in enumerate(source['documents']) if d['published_date'] <= cutoff]
    if cutoff >= '2025-06-20':
        docs.append(dict(title='2024年度权益分派实施公告（PDF第2页起）', published_date='2025-06-20', url='/api/replay/document/dividend'))
    return docs


def replay(request):
    if request.max_loss > request.capital:
        raise ValueError('损失预算不得超过初始本金')
    # 应用阵营天赋
    faction_info = None
    effective_max_loss = request.max_loss
    fee_multiplier = 1.0
    position_limit = 0.30
    if request.faction and request.faction in FACTION_TRAITS:
        trait = FACTION_TRAITS[request.faction]
        faction_info = {'id': request.faction, 'name': trait['name'], 'icon': trait['icon'],
                        'trait': trait['trait'], 'applied': True}
        effective_max_loss = request.max_loss * trait.get('max_loss_multiplier', 1.0)
        fee_multiplier = trait.get('fee_multiplier', 1.0)
        position_limit = trait.get('position_limit', 0.30)
    rows, nodes, manifest = load_data(request.stock_code)
    nodes = decision_nodes(rows, request.decision_mode)
    total_decisions = len(nodes) - 1
    if len(request.actions) > total_decisions:
        raise ValueError(f'本模式最多{total_decisions}次选择，已到最终节点')
    account = simulate(rows, nodes, request.capital, request.actions, manifest['dividends'],
                       effective_max_loss, fee_multiplier, position_limit)
    cutoff = account.history[-1]['date']
    visible = [r for r in rows if r['date'] <= cutoff]
    price = visible[-1]['close']
    stats = summary(account, request.capital, effective_max_loss, price)
    analysis = analyze_at(visible, cutoff, account, request.capital, effective_max_loss, fees)
    # Preview only: current-close hypothetical rebalance, never used as actual replay fill.
    preview = Account(account.cash, account.shares, account.basis, account.realized, account.dividends, account.total_fees)
    desired = account.shares if account.stop or request.preview_target is None else int(request.preview_target / price / 100) * 100
    preview.order(desired, price, cutoff)
    scenarios = []
    for decline in (() if account.stop else (3, 5, 10)):
        exit_price = round(price * (1 - decline / 100) * .999, 2)
        final = preview.cash + preview.shares * exit_price - fees(preview.shares, exit_price, True)
        loss = round(request.capital - final, 2)
        scenarios.append(dict(decline=decline, account_loss=loss, over_budget=round(max(0, loss - effective_max_loss), 2)))
    result = dict(version='replay-4', stop=account.stop, code=request.stock_code, name=STOCKS[request.stock_code]['name'], cutoff=cutoff, nodes=nodes,
                  decision_mode=request.decision_mode, total_decisions=total_decisions,
                  mode_label='每周决策' if request.decision_mode == 'weekly' else '快速体验',
                  step=sum(1 for e in account.ledger if 'decision_date' in e and not e['kind'].startswith('强制')), finished=account.stop is not None or len(request.actions) == total_decisions,
                  capital=request.capital, max_loss=effective_max_loss, original_max_loss=request.max_loss,
                  position_limit=position_limit, position_limit_type='advisory',
                  position_violation_count=sum(1 for event in account.ledger if event.get('position_violation')),
                  faction=faction_info,
                  price=price,
                  account=stats, analysis=analysis, ledger=account.ledger, equity_curve=account.history,
                  prices=[{'date': r['date'], 'close': r['close']} for r in visible],
                  candles=[dict(r) for r in visible],
                  documents=available_documents(cutoff, request.stock_code), preview_shares=preview.shares, scenarios=scenarios,
                  source={'name': manifest['upstream'], 'retrieved_at': manifest['retrieved_at'],
                          'price_basis': '不复权历史价格', 'file_sha256': manifest['sha256'][manifest['price_file']]},
                  evidence_note='仅列出截至节点公开、且本项目已保存的公告；并非完整新闻库。不调用AI，不使用8月财务摘要解释此前节点。',
                  assumptions=[f"账户从现金开始，本轮只模拟{STOCKS[request.stock_code]['name']}（{request.stock_code}）；无融资、利息、入金或取款。",
                               ('每周最后一个交易日' if request.decision_mode == 'weekly' else '月底') + '收盘后选择目标持仓市值，按该收盘价确定100股整数股数；下一交易日开盘加减0.1%滑点执行，现金不足缩量，不追单。',
                               ('每周' if request.decision_mode == 'weekly' else '每月') + '最多一次模拟调整机会，也可保持持仓不操作；不模拟盘中订单簿。停牌、开盘触限或假定成交价超出日内区间时保守拒绝。',
                               f'建议仓位为当前资产的{position_limit*100:.0f}%，不是强制上限；玩家可主动越界，系统会继续模拟并记录纪律违规次数。',
                               '费用假设：佣金万2.5、最低5元；过户费十万分之一；卖出印花税万5。非券商报价。',
                               '税前现金分红口径，未扣个人持股期限相关红利税；期末持仓按收盘市值计价，未强制卖出。',
                               manifest.get('review_note', '原有历史样本，按保存的分红实施资料模拟。'),
                               '预算基准为最初本金，期间不重置。每日收盘总资产相对初始本金的净亏损严格超过预算即终止选择，并在下一可成交交易日开盘模拟全部清仓；无法成交则继续待清仓。不保证损失上限，不检查盘中极值。',
                               '后验下载的历史资料；仅为教育实验，不证明策略有效或当时可按该价格成交。'])
    if result['finished']:
        hold = simulate(visible, [nodes[0], cutoff], request.capital, [Action(target_value=request.capital)], manifest['dividends'])
        result['benchmarks'] = [dict(name='您的模拟路径', **stats),
                                dict(name='首次尽量投入后保持（同期、不强制退出）', **summary(hold, request.capital, effective_max_loss, price)),
                                dict(name='始终持有现金（不计利息）', **summary(Account(request.capital), request.capital, effective_max_loss, price))]
    result['integrity_hash'] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result


@router.post('/api/replay')
def replay_endpoint(request: ReplayRequest):
    try:
        return replay(request)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/replay/document/{doc_id}')
def replay_document(doc_id: str):
    if doc_id == 'dividend':
        path = DATA / '2024_dividend_implementation.pdf'
    elif doc_id in {'0', '1', '2'}:
        docs = json.loads((PACK / 'official_documents.json').read_text(encoding='utf-8'))['documents']
        path = PACK / docs[int(doc_id)]['local_file']
    else:
        raise HTTPException(404, '公告不存在')
    return FileResponse(path, media_type='application/pdf')


@router.get('/api/replay/document/{code}/{doc_id}')
def pool_document(code: str, doc_id: int):
    if code not in STOCKS or code == '601318':
        raise HTTPException(404, '公告不存在')
    manifest = json.loads((stock_folder(code) / 'manifest.json').read_text(encoding='utf-8'))
    if not 0 <= doc_id < len(manifest['documents']):
        raise HTTPException(404, '公告不存在')
    return FileResponse(stock_folder(code) / manifest['documents'][doc_id]['file'], media_type='application/pdf')
