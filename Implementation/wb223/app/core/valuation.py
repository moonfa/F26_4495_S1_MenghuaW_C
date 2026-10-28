"""Deterministic scenario/return tests (formula valuation-v4); market references never become assumptions silently.

The model reads one period table (core/period_table.py). The analyst years in it are fixed: they are the analysts' numbers, the same in
Bear, Base and Bull. The user's growth starts in the first year after them, moves in a straight line to a long-run rate by the exit
year, and the scenarios differ only from there (growth, exit multiple, margin). The exit is a fiscal year end chosen from a list, so
the metric at exit is that fiscal year's figure and the exit multiple is read on the same trailing basis (price at that year end ÷ that
year's figure). Years to exit = days from the valuation date ÷ 365.25, usually not a whole number."""
from datetime import date, timedelta
from typing import Literal
from math import isclose
from pydantic import BaseModel, ConfigDict, Field
from .valuation_context import reference_price, num, to_date, add_years
from .period_table import table_of, series, exit_choice, steps_between, fy_label, estimates_used

FORMULA = 'valuation-v4'


class Assumptions(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    method: Literal['pe'] = 'pe'
    exit_fy: str                                   # period end (ISO date) of the fiscal year the stock is sold at
    required_return: float = Field(gt=-1, le=1)
    growth: float = Field(gt=-1, le=2)             # growth in the first year after the analyst years
    growth_spread: float = Field(ge=0, le=1)
    fade_to: float | None = Field(default=None, gt=-1, le=2)
    exit_pe: float = Field(gt=0, le=500)
    pe_spread: float = Field(ge=0, lt=1)


class EbitdaAssumptions(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    method: Literal['ev_ebitda']
    exit_fy: str
    required_return: float = Field(gt=-1, le=1)
    growth: float = Field(gt=-1, le=2)
    growth_spread: float = Field(ge=0, le=1)
    fade_to: float | None = Field(default=None, gt=-1, le=2)
    margin: float = Field(gt=0, le=1)
    margin_spread: float = Field(ge=0, lt=1)
    exit_multiple: float = Field(gt=0, le=300)
    multiple_spread: float = Field(ge=0, lt=1)
    target_net_debt: float = Field(ge=-1e15, le=1e15)
    target_shares: float = Field(gt=0, le=1e15)
    other_claims: float = Field(ge=0, le=1e15)
    balance_assumption: Literal['user_forecast', 'hold_current_constant']


class PfcfAssumptions(BaseModel):
    """Price / free-cash-flow exit multiple. growth is growth of total FCF; share_change is the yearly change in share count
    (negative = buybacks, positive = dilution), so FCF per share grows at (1+growth)/(1+share_change)-1 in the user's years."""
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    method: Literal['p_fcf']
    basis: Literal['fcf', 'fcf_sbc'] = 'fcf'       # before or after stock-based compensation
    exit_fy: str
    required_return: float = Field(gt=-1, le=1)
    growth: float = Field(gt=-1, le=2)
    growth_spread: float = Field(ge=0, le=1)
    fade_to: float | None = Field(default=None, gt=-1, le=2)
    share_change: float = Field(gt=-.5, lt=.5)
    exit_multiple: float = Field(gt=0, le=300)
    multiple_spread: float = Field(ge=0, lt=1)


def rates(g0, g1, k):
    """Yearly growth rates for the user's k years: g0 in the first, moving in a straight line to g1 in the last (flat when g1 is None)."""
    if k <= 0:
        return []
    if g1 is None or k == 1 or abs(g1 - g0) < 1e-12:
        return [g0] * k
    return [g0 + (g1 - g0) * j / (k - 1) for j in range(k)]


def fade_of(a, shift):
    return None if a.fade_to is None else a.fade_to + shift * a.growth_spread


def setup(data, a):
    """Everything the three methods share: price, exit year, the series to project and how many years are the user's own."""
    price = (data.get('quote') or {}).get('value')
    if not price or price <= 0:
        raise ValueError('A positive observed price is required.')
    currency = data['quote'].get('currency')
    table = table_of(data)
    opt = exit_choice(table, a.exit_fy)
    ser = series(table, a.method, getattr(a, 'basis', 'fcf'))
    cc = ser['last'].get('currency')
    if not currency or currency != cc:
        fx = data.get('fx') or {}
        raise ValueError('The price is in %s but this figure is in %s, and no exchange rate was applied (%s). Import the data again.' % (
            currency or 'an unknown currency', cc or 'an unknown currency', fx.get('reason') or 'none was available'))
    if a.growth - a.growth_spread <= -1:
        raise ValueError('Bear growth must exceed -100%.')
    k = steps_between(ser['last']['period_end'], opt['period_end'])
    known_exit = None
    if not ser['known']:
        k = max(k, 1)
    elif k == 0:
        known_exit = next((x for x in ser['known'] if abs((to_date(x['period_end']) - to_date(opt['period_end'])).days) <= 20), None)
        if known_exit is None:
            raise ValueError('There is no analyst figure for that fiscal year; choose a later one.')
    valuation = to_date(data.get('retrieved_at') or table['valuation_date'])
    dis = data.get('earnings_dislocation') or {}
    return dict(price=price, currency=currency, table=table, opt=opt, ser=ser, recovery=dis.get('kind') in ('recovery', 'loss_to_profit') and a.method == 'pe', k=k, known_exit=known_exit, valuation=valuation,
                exit_end=to_date(opt['period_end']), years=(to_date(opt['period_end']) - valuation).days / 365.25)   # exact, not the rounded figure shown in the dropdown


def project(ctx, g0, g1, drag=1.0):
    """(exit value, [value of each of the user's years]) with yearly growth g0 → g1 and an optional per-year share drag."""
    v, vals = ctx['ser']['last']['value'], []
    for g in rates(g0, g1, ctx['k']):
        v *= (1 + g) / drag
        vals.append(v)
    return (v if ctx['k'] > 0 else ctx['known_exit']['value']), vals


def start_of(ctx):
    last = ctx['ser']['last']
    cat = 'historical_reported' if last['kind'] == 'actual' else 'market_consensus'
    return dict(id=last['key'], value=last['value'], period_end=last['period_end'], category=cat, currency=last.get('currency'), kind=last['kind'],
                label=fy_label(last['period_end']))


def outputs(data, a, ctx, rows, reverse):
    price, years = ctx['price'], ctx['years']
    target = price * (1 + a.required_return) ** years
    for row in rows:
        f = row['future_price']
        row.update(discounted_terminal=f / (1 + a.required_return) ** years, price_cagr=(f / price) ** (1 / years) - 1 if f > 0 else -1.0,
                   price_change=f / price - 1, meets_required=f >= target)
        row['return_gap'] = row['price_cagr'] - a.required_return
    ser = ctx['ser']
    analyst = [dict(fy=fy_label(x['period_end']), period_end=x['period_end'], kind=x['kind']) for x in ser['known']
               if to_date(x['period_end']) <= ctx['exit_end'] + timedelta(days=20)]
    cur = ctx['currency']
    fx_note = []
    if data.get('fx', {}).get('applied'):
        fx_note = ['Reported figures in %s were converted to %s at one spot rate and the rate is held constant to the exit date, so a move in the exchange rate would change the result by about the same percentage.' % (data['fx']['from'], cur)]
    return dict(method=a.method, formula_version=FORMULA, currency=cur, valuation_date=ctx['valuation'].isoformat(), exit_date=ctx['opt']['period_end'],
                exit_fy=ctx['opt']['fy'], growth_years=years, years=years, user_years=ctx['k'], analyst_years=analyst,
                anchor=start_of(ctx), assumptions=a.model_dump(), scenarios=rows, reverse=reverse, required_exit_price=target,
                estimates_used=estimates_used(ctx['table']),
                limitations=fx_note + [
                    'Discounted terminal price is not a complete cash-flow valuation.',
                    'Bear/Base/Bull are user assumptions, not probabilities, bounds or analyst targets.',
                    'The analyst years are the analysts\' mean figures and are the same in all three scenarios; Bear/Base/Bull differ only from the first year after them.',
                    'The exit multiple is trailing: the price at the end of the exit fiscal year divided by that year\'s figure. Years to exit are counted in days ÷ 365.25 from the valuation date.' +
                    (' Growth fades in a straight line to %.1f%% by the exit year.' % (a.fade_to * 100) if a.fade_to is not None else ' Growth stays at the same rate each year.'),
                    'Reverse expectations are conditional on the selected multiple and other assumptions.'])


def decompose(res, ctx, mkey):
    """Split each scenario's annual price return into an earnings (or cash-flow) part and a multiple part against the reference
    (trailing twelve months, else the last reported year). Exact identity: future/price = (X_exit/X_ref) × (M_exit/M_ref), M_ref = price/X_ref."""
    ref = ctx['ser']['ref']
    first = ctx['ser']['known'][0] if ctx['ser']['known'] else None
    if ctx.get('recovery') and first:       # trailing earnings are a trough the price already looks through: split from this year's analyst figure instead
        ref = dict(first, kind='analyst')
    if not ref:
        res['start_multiple'] = None
        return res
    start = ctx['price'] / ref['value']
    res['start_multiple'] = start
    res['reference'] = dict(label=('TTM' if ref['kind'] == 'ttm' else fy_label(ref['period_end']) + (' (analyst)' if ref['kind'] != 'actual' else '')), value=ref['value'], period_end=ref['period_end'],
                            why=('Trailing earnings are far below the analysts\' numbers, so the split starts from this year\'s analyst figure; from the trailing figure the recovery would be counted as earnings growth and the multiple as a fall.' if ctx.get('recovery') and first else None))
    for row in res['scenarios']:
        me = (row[mkey] / start) ** (1 / ctx['years']) - 1
        row['multiple_effect'] = me
        row['earnings_effect'] = (1 + row['price_cagr']) / (1 + me) - 1
    return res


def make_path(ctx, g0, g1, exit_m, drag=1.0, price_of=None):
    """Year-by-year Base path from the first fiscal year to the exit year: analyst years as given, then the user's years. The
    multiple moves in a straight line (by date) from today's multiple on this year's figure to the exit multiple, so the path is an illustration of
    the route, not a forecast of intermediate prices."""
    ser, price, V = ctx['ser'], ctx['price'], ctx['valuation']
    _, uvals = project(ctx, g0, g1, drag)
    entries = [dict(end=x['period_end'], value=x['value'], source=x['kind']) for x in ser['known'] if to_date(x['period_end']) <= ctx['exit_end'] + timedelta(days=20)]
    last_end = to_date(ser['last']['period_end'])
    for j, v in enumerate(uvals, 1):
        entries.append(dict(end=add_years(last_end, j).isoformat(), value=v, source='yours'))
    first = ser['known'][0] if ser['known'] else ser['ref']
    m0 = price / first['value'] if first else None       # today's multiple on this year's figure (else trailing): year 0 reproduces today's price
    prev = (ser.get('actual') or {}).get('value')
    span = max(1, (ctx['exit_end'] - V).days)
    out = []
    for e in entries:
        d = to_date(e['end'])
        frac = min(1.0, max(0.0, (d - V).days / span))
        m = exit_m if m0 is None else m0 + (exit_m - m0) * frac
        yrs = max(1e-9, (d - V).days / 365.25)
        row = dict(fy=fy_label(e['end']), date=e['end'], source=e['source'], value=e['value'], growth=(e['value'] / prev - 1) if prev and prev > 0 else None, multiple=m)
        prev = e['value']
        p = price_of(e['value'], m) if price_of else e['value'] * m
        row.update(price=p, price_change=None if p is None else p / price - 1, annualised=None if not p or p <= 0 else (p / price) ** (1 / yrs) - 1)
        out.append(row)
    return out


def today_multiples(ctx):
    """What the market pays today: on this fiscal year's figure (first analyst year, else none) and on the reference (TTM, else last year)."""
    ser, price = ctx['ser'], ctx['price']
    e0 = ser['known'][0]['value'] if ser['known'] else None
    return dict(e0=price / e0 if e0 else None, ref=price / ser['ref']['value'] if ser['ref'] else None)


def range_checks(data, a, ctx, res):
    """Plausibility notes next to the result. They never change the numbers; level 'warn' means look before trusting."""
    out, price, ser = [], ctx['price'], ctx['ser']
    cm = data.get('current_multiples') or {}
    td = today_multiples(ctx)
    now = td['e0'] or td['ref']
    where = "this year's estimate" if td['e0'] else 'the trailing figure'

    def add(level, text):
        out.append(dict(level=level, text=text))
    m = a.method
    mine = a.exit_pe if m == 'pe' else a.exit_multiple
    label = {'pe': 'P/E', 'p_fcf': 'P/FCF', 'ev_ebitda': 'EV/EBITDA'}[m]
    if m != 'ev_ebitda' and now:
        if mine > 1.5 * now:
            add('warn', f'Exit {label} {mine:.1f}x is more than 1.5x what the market pays today on {where} ({now:.1f}x): the result leans on multiple expansion.')
        elif mine < 0.5 * now:
            add('note', f'Exit {label} {mine:.1f}x is less than half of today\'s {now:.1f}x on {where}: a deep de-rating is assumed.')
        ref = ser['ref']
        if ref and price / ref['value'] > 60:
            add('warn', f'Price is {price / ref["value"]:.0f}x the {"trailing" if ref["kind"] == "ttm" else "last reported year"} figure: a small base makes the projection very sensitive.')
    if ctx['k'] == 0:
        add('note', f'The exit year {ctx["opt"]["fy"]} is an analyst year, so your growth and fade inputs are not used: only the exit multiple (and margin) move the scenarios.')
    else:
        an = ser['known']
        thru = fy_label(an[-1]['period_end']) if an else None
        add('note', (f'Analysts cover up to {thru}. ' if thru else 'There are no analyst figures, so ') + f'{ctx["k"]} of the years to {ctx["opt"]["fy"]} {"rests" if ctx["k"] == 1 else "rest"} on your own growth assumption.')
        if an and an[-1].get('growth') is not None and m != 'p_fcf':
            g = an[-1]['growth']
            if a.growth > max(2 * g, g + .05):
                add('warn', f'Base growth {a.growth * 100:.1f}% is well above the analysts\' last-year growth of {g * 100:.1f}%.')
    age = (ctx['valuation'] - to_date((ser['actual'] or ser['last'])['period_end'])).days / 30.44 if (ser['actual'] or ser['last']) else 0
    if age > 15:
        add('warn', f'The last reported fiscal year ended {age:.0f} months ago; newer results are probably out. Import the data again.')
    dis = data.get('earnings_dislocation')
    if m == 'pe':
        if dis and dis.get('kind') == 'recovery':
            add('note', f'Reported EPS {dis["ttm_eps"]:.2f} is far below analyst EPS {(dis.get("cons_0y") or dis.get("cons_1y")):.2f}: the price already expects a recovery. The projection starts from the analyst years; read the "what you must believe" table.')
    elif m == 'p_fcf':
        fh = [r for r in data.get('fcf_history', []) if r.get('conversion') is not None and not r.get('ttm')]
        if fh and (fh[0]['conversion'] < .5 or fh[0]['conversion'] > 1.5):
            add('warn', f'Free cash flow is {fh[0]["conversion"] * 100:.0f}% of net income in the latest year: cash conversion is unusual, so check capex timing and one-offs.')
        latest = next((r for r in data.get('fcf_history', []) if r.get('ttm')), None) or (data.get('fcf_history') or [None])[0]
        if latest and latest.get('sbc') and latest.get('fcf') and latest['fcf'] > 0 and latest['sbc'] / latest['fcf'] > .25 and a.basis != 'fcf_sbc':
            add('note', f'Stock-based compensation is {latest["sbc"] / latest["fcf"] * 100:.0f}% of FCF. Consider the after-SBC basis.')
        if a.basis == 'fcf_sbc' and a.share_change > 0:
            add('note', 'The after-SBC cash flow already treats stock compensation as a cost; a positive share-count change counts the same dilution a second time.')
        if any(x['kind'] == 'derived' for x in ser['known']):
            fb = ctx['table'].get('fcf_base') or {}
            add('note', 'There is no analyst forecast for free cash flow: the analyst-year values are the ' + ('latest twelve months' if fb.get('which') == 'TTM' else 'latest reported year') + ' grown with analyst revenue, at the same margin' + (f' ({fb["margin"] * 100:.1f}% of revenue)' if fb.get('margin') else '') + ' and share count. P/E and P/FCF agreeing is therefore not independent confirmation.')
    else:
        hist = [r.get('ebitda_margin') for r in data.get('historical', []) if r.get('ebitda_margin') is not None]
        if hist and a.margin > 1.5 * max(hist):
            add('warn', f'Base margin {a.margin * 100:.1f}% is above 1.5x the highest reported EBITDA margin ({max(hist) * 100:.1f}%).')
        cur = cm.get('enterprise_to_ebitda')
        if cur and a.exit_multiple > 1.5 * cur:
            add('warn', f'Exit EV/EBITDA {a.exit_multiple:.1f}x is more than 1.5x today\'s trailing {cur:.1f}x.')
        add('note', 'Analyst years carry revenue only; EBITDA is revenue × the margin you set for the exit year.')
    return out


def belief_grid(data, a, ctx, res):
    """What you must believe: the exit price for different earnings (or cash-flow) outcomes against different exit multiples.
    Rows scale the Base value at exit (shortfalls of 20% and 40%, plus the reported trailing level when earnings are expected to
    recover); columns are today's multiples, your exit multiple and the reference multiples. Cell = annual price return. Pure
    arithmetic on stated inputs; it ranks nothing and picks no cell."""
    if a.method not in ('pe', 'p_fcf'):
        return None
    base, price = res['scenarios'][1], ctx['price']
    key = 'eps' if a.method == 'pe' else 'fcf_per_share'
    mkey = 'exit_pe' if a.method == 'pe' else 'exit_multiple'
    mine, e0 = getattr(a, mkey), base[key]
    rows = [dict(label='Your Base path', factor=1.0), dict(label='Falls 20% short', factor=.8), dict(label='Falls 40% short', factor=.6)]
    ref = ctx['ser']['ref']
    if a.method == 'pe' and ref and ref['kind'] == 'ttm' and ref['value'] / e0 < .75:
        rows.append(dict(label=f'No recovery: reported trailing EPS {ref["value"]:.2f} is the base', factor=ref['value'] / e0))
    td = today_multiples(ctx)
    cols = [dict(label='Your exit multiple', value=mine)]      # first, so a reference within 3% of it never hides it
    if td['e0']:
        cols.append(dict(label="Today on this year's estimate", value=td['e0']))
    if td['ref']:
        cols.append(dict(label='Today on trailing', value=td['ref']))
    mc = (data.get('multiple_context') or {}).get(a.method) or {}
    for pt in mc.get('points') or []:
        k = pt.get('key')
        if k == 'history':
            cols += [dict(label='Own history · low (trailing)', value=pt['low']), dict(label='Own history · high (trailing)', value=pt['high'])]
        elif k == 'peers' and pt.get('median'):
            cols.append(dict(label='Peers · median', value=pt['median']))
    uniq = []
    for c in cols:
        if c['value'] and c['value'] > 0 and not any(abs(c['value'] / u['value'] - 1) < .03 for u in uniq):
            uniq.append(c)
    uniq = sorted(uniq, key=lambda c: c['value'])[:6]
    for r in rows:
        r['value'] = e0 * r['factor']
        r['cells'] = []
        for c in uniq:
            fp = r['value'] * c['value']
            cg = (fp / price) ** (1 / ctx['years']) - 1 if fp > 0 else None
            r['cells'].append(dict(price=fp, cagr=cg, meets=cg is not None and cg >= a.required_return))
    return dict(method=a.method, noun='EPS' if a.method == 'pe' else 'FCF/share', columns=uniq, rows=rows, required_return=a.required_return,
                note='Each cell: the Base value at the exit year (shown in the row) × the multiple in the column, as an annual price return from today\'s price. '
                     'The multiples are trailing, like the exit multiple. Pure arithmetic: it ranks nothing and picks no cell.')


def calculate(data, a):
    if isinstance(a, EbitdaAssumptions):
        return calculate_ebitda(data, a)
    if isinstance(a, PfcfAssumptions):
        return calculate_pfcf(data, a)
    ctx = setup(data, a)
    rows = []
    for label, shift in (('Bear', -1), ('Base', 0), ('Bull', 1)):
        growth, pe, fade = a.growth + shift * a.growth_spread, a.exit_pe * (1 + shift * a.pe_spread), fade_of(a, shift)
        if fade is not None and fade <= -1:
            raise ValueError('Bear fade growth must exceed -100%.')
        eps, _ = project(ctx, growth, fade)
        rows.append(dict(scenario=label, growth=growth, exit_pe=pe, eps=eps, future_price=eps * pe))
    needed = ctx['price'] * (1 + a.required_return) ** ctx['years'] / a.exit_pe
    last = ctx['ser']['last']['value']
    reverse = dict(required_eps=needed, required_eps_growth=(needed / last) ** (1 / ctx['k']) - 1 if ctx['k'] > 0 else None,
                   required_exit_pe=ctx['price'] * (1 + a.required_return) ** ctx['years'] / rows[1]['eps'], exit_pe=a.exit_pe, required_return=a.required_return)
    res = outputs(data, a, ctx, rows, reverse)
    res['path'] = make_path(ctx, a.growth, a.fade_to, a.exit_pe)
    decompose(res, ctx, 'exit_pe')
    res['checks'] = range_checks(data, a, ctx, res)
    res['grid'] = belief_grid(data, a, ctx, res)
    return res


def calculate_pfcf(data, a):
    ctx = setup(data, a)
    drag = 1 + a.share_change
    rows = []
    for label, shift in (('Bear', -1), ('Base', 0), ('Bull', 1)):
        growth, multiple, fade = a.growth + shift * a.growth_spread, a.exit_multiple * (1 + shift * a.multiple_spread), fade_of(a, shift)
        if fade is not None and fade <= -1:
            raise ValueError('Bear fade growth must exceed -100%.')
        ps, _ = project(ctx, growth, fade, drag)
        rows.append(dict(scenario=label, growth=growth, exit_multiple=multiple, fcf_per_share=ps, fcf_yield=1 / multiple, future_price=ps * multiple))
    needed = ctx['price'] * (1 + a.required_return) ** ctx['years'] / a.exit_multiple
    last = ctx['ser']['last']['value']
    reverse = dict(required_fcf_per_share=needed, required_fcf_per_share_growth=(needed / last) ** (1 / ctx['k']) - 1 if ctx['k'] > 0 else None,
                   required_exit_multiple=ctx['price'] * (1 + a.required_return) ** ctx['years'] / rows[1]['fcf_per_share'],
                   exit_multiple=a.exit_multiple, required_return=a.required_return)
    res = outputs(data, a, ctx, rows, reverse)
    res['path'] = make_path(ctx, a.growth, a.fade_to, a.exit_multiple, drag)
    decompose(res, ctx, 'exit_multiple')
    res['checks'] = range_checks(data, a, ctx, res)
    res['grid'] = belief_grid(data, a, ctx, res)
    res['limitations'] += ['Free cash flow = operating cash flow − capital expenditure as supplied by the provider; leases, acquisitions and working-capital swings are not adjusted.',
                           'Per-share FCF uses the share count named in the table; buybacks and dilution are the share_change assumption, applied in the years after the analyst years.']
    return res


def calculate_ebitda(data, a):
    ctx = setup(data, a)
    if a.margin - a.margin_spread <= 0 or a.margin + a.margin_spread > 1:
        raise ValueError('All EBITDA margins must be greater than zero and at most 100%.')
    cur = ctx['currency']
    baseline = data.get('market_baseline') or {}
    if a.balance_assumption == 'hold_current_constant':
        if baseline.get('currency') != cur:
            raise ValueError('Current balance currency does not match the quote.')
        if baseline.get('net_debt') is None or baseline.get('shares') is None:
            raise ValueError('Current net debt and shares are required for this assumption.')
        if not isclose(a.target_net_debt, baseline['net_debt'], rel_tol=1e-12, abs_tol=.001) or not isclose(a.target_shares, baseline['shares'], rel_tol=1e-12, abs_tol=.001):
            raise ValueError('Hold-current assumption must match the saved provider balance and share values.')
    rows = []
    for label, shift in (('Bear', -1), ('Base', 0), ('Bull', 1)):
        growth, margin = a.growth + shift * a.growth_spread, a.margin + shift * a.margin_spread
        multiple, fade = a.exit_multiple * (1 + shift * a.multiple_spread), fade_of(a, shift)
        if fade is not None and fade <= -1:
            raise ValueError('Bear fade growth must exceed -100%.')
        revenue, _ = project(ctx, growth, fade)
        ebitda = revenue * margin
        ev = ebitda * multiple
        equity = ev - a.target_net_debt - a.other_claims
        rows.append(dict(scenario=label, growth=growth, margin=margin, exit_multiple=multiple, revenue=revenue, ebitda=ebitda, enterprise_value=ev,
                         equity_value=equity, future_price=max(0, equity) / a.target_shares, equity_floor_applied=equity < 0))
    claims = ctx['price'] * (1 + a.required_return) ** ctx['years'] * a.target_shares + a.target_net_debt + a.other_claims
    needed = claims / a.exit_multiple
    reverse = dict(required_ebitda=needed, required_margin=needed / rows[1]['revenue'], required_exit_multiple=claims / rows[1]['ebitda'], required_return=a.required_return)
    res = outputs(data, a, ctx, rows, reverse)
    res['path'] = make_path(ctx, a.growth, a.fade_to, a.exit_multiple, price_of=lambda v, m: None)
    res['checks'] = range_checks(data, a, ctx, res)
    res['limitations'] += ['Current net debt/shares, if reused, are explicitly assumed constant to exit; other claims are user-entered.',
                           'EBITDA excludes capex, working capital, tax and financing costs. SBC and lease definitions may differ.',
                           'Negative residual equity is floored at zero for per-share price, not represented as a negative stock price.']
    return res


def consensus_bridge(data,pe,spread):
    if not 0<pe<=500 or not 0<=spread<1: raise ValueError('Invalid P/E or range.')
    rows=[]
    for estimate in data.get('estimates',[]):
        if estimate.get('metric')!='eps' or estimate.get('period') not in ('0y','+1y'): continue
        row=dict(period=estimate['period'],eps=estimate.get('avg'),source=estimate.get('source'),
                 period_end=estimate.get('period_end'),basis=estimate.get('basis'),prices=[])
        try:
            for name,shift in (('Lower P/E',-1),('Selected P/E',0),('Higher P/E',1)):
                m=pe*(1+shift*spread);value=reference_price(estimate,m,data['quote'].get('currency'))
                price=data['quote'].get('value')
                row['prices'].append(dict(label=name,pe=m,price=value,change=value/price-1 if price and price>0 else None))
        except ValueError as exc: row['error']=str(exc)
        rows.append(row)
    return dict(rows=rows,pe=pe,spread=spread,
        explanation='Annual consensus mean EPS × user-selected P/E. A valuation sensitivity, not an analyst target. No annualized return: exact forecast dates and EPS basis remain unverified. Current price / this same EPS × this EPS reproduces the current price by identity.')


