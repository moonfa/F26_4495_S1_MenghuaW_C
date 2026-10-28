"""Link between the valuation lab and a company's research page. Pure functions: no database, no network, no model.

The valuation lab keeps its own append-only store. This module turns what is saved there into a short, honest summary for the
company page: what the saved assumptions imply today, what they imply at the price the user's Plan names, whether the saved
valuation is out of date, and which thesis assumptions each valuation input depends on. Nothing here changes a Plan, a thesis
or a saved valuation, and none of it is sent to a model."""
from datetime import datetime, timezone

from .compare import ticker_row
from .period_table import table_of, fy_label

# What a thesis assumption can be tied to. The user chooses; the program never guesses a link.
DRIVERS = {
    'eps_growth': 'Earnings or cash-flow growth',
    'revenue_growth': 'Revenue growth',
    'margin': 'Margins',
    'multiple': 'What the market will pay (exit multiple)',
    'shares': 'Share count or dilution',
    'balance': 'Net debt or balance sheet',
}
# Which drivers each method's saved inputs rest on.
METHOD_DRIVERS = {'pe': ('eps_growth', 'multiple'), 'p_fcf': ('eps_growth', 'multiple', 'shares'),
                  'ev_ebitda': ('revenue_growth', 'margin', 'multiple', 'balance')}
METHOD_LABEL = {'pe': 'P/E', 'p_fcf': 'P/FCF', 'ev_ebitda': 'EV/EBITDA'}
WEAK = ('weakened', 'broken')
PRICE_MOVE = 0.15      # a saved valuation is stale when the price has moved this much since its data was fetched
DATA_DAYS = 100        # about a quarter: new results have probably been reported since
EPS_REVISION = 0.03    # analyst EPS for a saved year has moved this much since the analysis was saved
REVENUE_REVISION = 0.02


def _dt(v):
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _sc(result, name):
    return next((s for s in result.get('scenarios') or [] if s.get('scenario') == name), None)


def at_price(result, entry):
    """What the saved Base path would return if you paid `entry`, and the most you could pay for the required return."""
    base, bear, bull = _sc(result, 'Base'), _sc(result, 'Bear'), _sc(result, 'Bull')
    a = result.get('assumptions') or {}
    years, req = result.get('years'), a.get('required_return')
    if not base or not years or req is None:
        return None
    fp = base['future_price']
    out = dict(max_entry=fp / (1 + req) ** years if fp and fp > 0 else None)
    if entry and entry > 0:
        f = lambda s: None if not s or s['future_price'] <= 0 else (s['future_price'] / entry) ** (1 / years) - 1
        out.update(entry=entry, base=f(base), bear=f(bear), bull=f(bull))
    return out


def analysis_row(rec, price_now, plan, today):
    """One saved analysis, flattened. `rec` carries the stored analysis plus 'data_price' and 'data_fetched' of its data snapshot."""
    res = (rec.get('payload') or {}).get('result') or {}
    a = res.get('assumptions') or {}
    m = a.get('method') or res.get('method') or 'pe'
    base, bear, bull = _sc(res, 'Base'), _sc(res, 'Bear'), _sc(res, 'Bull')
    if not base:
        return None
    anchor = res.get('anchor') or {}
    mult = a.get('exit_pe') if m == 'pe' else a.get('exit_multiple')
    row = dict(method=m, label=METHOD_LABEL.get(m, m), analysis_id=rec.get('id'), saved_at=rec.get('created_at'), years=res.get('years'), exit_fy=res.get('exit_fy'),
               required_return=a.get('required_return'), anchor_id=anchor.get('id'), anchor_kind=anchor.get('category'), estimates_used=res.get('estimates_used'), diag=(res.get('diagnosis') or {}).get('level'),
               anchor_end=anchor.get('period_end'), anchor_value=anchor.get('value'), growth=a.get('growth'), fade_to=a.get('fade_to'),
               exit_multiple=mult, bear=bear and bear['price_cagr'], base=base['price_cagr'], bull=bull and bull['price_cagr'],
               base_price=base['future_price'], exit_date=res.get('exit_date'), warnings=sum(1 for c in res.get('checks') or [] if c.get('level') == 'warn'),
               price_at_save=rec.get('data_price'), data_fetched=rec.get('data_fetched'))
    if price_now and price_now > 0:
        row['now'] = at_price(res, price_now)
    if plan and plan.get('buy_below'):
        row['at_buy_below'] = at_price(res, plan['buy_below'])
    if plan and plan.get('target_price') and base['future_price']:
        row['target_vs_base'] = plan['target_price'] / base['future_price'] - 1
    return row


def estimate_changes(used, table):
    """What the analysts' numbers did since an analysis was saved. `used` = the estimates stored with it (by fiscal year end);
    `table` = the period table of the newest import. Facts only: nothing here changes a saved analysis."""
    out = []
    if not used or not table:
        return out
    cols = [(c, to_day(c['period_end'])) for c in table['columns'] if c['kind'] in ('analyst', 'actual')]
    for metric, thr in (('eps', EPS_REVISION), ('revenue', REVENUE_REVISION)):
        for end, old in (used.get(metric) or {}).items():
            d0 = to_day(end)
            hit = next(((c, d) for c, d in cols if d0 and d and abs((d - d0).days) <= 20 and (table['rows'].get(metric) or {}).get(c['key'])), None)
            if not hit or not old or old <= 0:
                continue
            cell = table['rows'][metric][hit[0]['key']]
            ch = cell['value'] / old - 1
            out.append(dict(metric=metric, fy=fy_label(end), period_end=end, old=old, new=cell['value'], change=ch,
                            reported=hit[0]['kind'] == 'actual', material=abs(ch) >= thr or hit[0]['kind'] == 'actual'))
    return out


def to_day(v):
    d = _dt(v)
    return d.date() if d else None


def estimate_text(changes):
    """One factual line about the changes above, or None when nothing crossed a threshold."""
    parts = []
    for c in changes:
        if not c['material']:
            continue
        name = 'EPS' if c['metric'] == 'eps' else 'revenue'
        f = (lambda v: f'{v:,.2f}') if c['metric'] == 'eps' else (lambda v: f'{v / 1e9:,.2f}bn' if abs(v) >= 1e9 else f'{v / 1e6:,.0f}m')
        if c['reported']:
            parts.append(f'{c["fy"]} {name} is now reported at {f(c["new"])} (the saved analysis used an estimate of {f(c["old"])}, {c["change"] * 100:+.1f}%)')
        else:
            parts.append(f'analyst {name} for {c["fy"]} moved from {f(c["old"])} to {f(c["new"])} ({c["change"] * 100:+.1f}%)')
    return ('Since this was saved: ' + '; '.join(parts) + '. The saved analysis was not changed.') if parts else None


def stale_reasons(row, price_now, reviews, assumptions, drivers, today, table=None):
    """Plain reasons a saved valuation may no longer describe the company. Facts only; it never changes the saved numbers."""
    out = []
    saved = _dt(row.get('saved_at'))
    if saved:
        for r in reviews or []:
            at = _dt(r.get('created_at'))
            if at and at > saved and r.get('kind') != 'check' and (r.get('level') == 'material' or r.get('kind') == 'rebaseline'):
                out.append(dict(kind='thesis', text=f'The thesis was materially updated on {at.date().isoformat()}, after this valuation was saved. Check that its assumptions still hold.'))
                break
    p0 = row.get('price_at_save')
    if p0 and price_now and p0 > 0 and abs(price_now / p0 - 1) >= PRICE_MOVE:
        out.append(dict(kind='price', text=f'The price has moved {(price_now / p0 - 1) * 100:+.0f}% since the data behind this valuation was fetched ({p0:,.2f} to {price_now:,.2f}).'))
    fetched = _dt(row.get('data_fetched'))
    if fetched and (today - fetched).days > DATA_DAYS:
        out.append(dict(kind='data', text=f'The data is {(today - fetched).days} days old; a new quarter has probably been reported. Import again.'))
    used = row.get('estimates_used')
    if used and table:
        txt = estimate_text(estimate_changes(used, table))
        if txt:
            out.append(dict(kind='estimates', text=txt))
        newest = (table['rows'].get('eps', {}).get('A0') or table['rows'].get('revenue', {}).get('A0') or {}).get('period_end')
        if used.get('last_actual_end') and newest and newest > used['last_actual_end']:
            out.append(dict(kind='fy', text=f'{fy_label(newest)} has been reported since this was saved, so the starting year and the analyst years have moved. Run the analysis again.'))
    mine = METHOD_DRIVERS.get(row.get('method'), ())
    stat = {a['id']: a for a in assumptions or []}
    weak = [stat[i] for i, d in (drivers or {}).items() if d in mine and i in stat and stat[i].get('status') in WEAK]
    for a in weak:
        out.append(dict(kind='assumption', text=f'Assumption {a["id"]} is {a["status"]} and is tied to "{DRIVERS.get(drivers[a["id"]])}" in this method: {a.get("statement", "")}'))
    return out


def driver_table(assumptions, drivers):
    """For each driver, the thesis assumptions the user tied to it, with their current status."""
    stat = {a['id']: a for a in assumptions or []}
    out = []
    for key, label in DRIVERS.items():
        ids = [i for i, d in (drivers or {}).items() if d == key and i in stat]
        out.append(dict(key=key, label=label, methods=[METHOD_LABEL[m] for m, ds in METHOD_DRIVERS.items() if key in ds],
                        assumptions=[dict(id=i, statement=stat[i].get('statement', ''), status=stat[i].get('status')) for i in ids]))
    return out


def question_for(summary):
    """A note the user may save: the thing the valuation says has to be true, in one sentence, from numbers on the page."""
    dis = summary.get('dislocation')
    if dis and dis.get('kind') == 'recovery' and dis.get('ttm_eps') and (dis.get('cons_0y') or dis.get('cons_1y')):
        e = dis.get('cons_0y') or dis.get('cons_1y')
        return (f'The price already assumes EPS recovers from {dis["ttm_eps"]:.2f} (trailing) to about {e:.2f} (analysts). '
                'What evidence would show the recovery is real, and what would show it is only an accounting difference?')
    best = next((a for a in summary.get('analyses') or [] if a.get('method') == 'pe'), None) or next(iter(summary.get('analyses') or []), None)
    if best and best.get('required_return') is not None and best.get('base') is not None and best['base'] < best['required_return']:
        return (f'At today\'s price my saved {best["label"]} Base case returns {best["base"] * 100:.1f}% a year against the {best["required_return"] * 100:.0f}% I require. '
                'Which assumption would have to be better than I wrote, and what would show it?')
    return None


def summarize(data_rec, analyses, price_now, reviews, assumptions, drivers, plan, now=None):
    """Everything the company page needs about valuation, from what is already stored."""
    today = now or datetime.now(timezone.utc)
    if not data_rec:
        return dict(available=False, drivers=driver_table(assumptions, drivers), driver_options=DRIVERS)
    d = data_rec['payload']
    dis = d.get('earnings_dislocation')
    rows, seen = [], set()
    for rec in analyses or []:                       # newest first: keep the latest saved analysis per method
        r = analysis_row(rec, price_now, plan, today)
        if r and r['method'] not in seen:
            seen.add(r['method'])
            r['stale'] = stale_reasons(r, price_now, reviews, assumptions, drivers, today, table_of(d))
            rows.append(r)
    try:
        sq = ticker_row(d, 3, 0.10, 0.0, 0.05)
        status_quo = dict(years=sq.get('years') or 3, exit_fy=sq.get('exit_fy'), required_return=0.10, fade_to=0.05, methods=[dict(method=m['method'], label=m['label'], base=m['base'], bear=m['bear'], bull=m['bull'],
                          note=m['note'], implausible=m['implausible']) for m in sq['methods']], review=sq['review'])
    except (ValueError, OverflowError, KeyError, TypeError):
        status_quo = None
    out = dict(available=True, ticker=d.get('ticker'), data_id=data_rec.get('id'), fetched_at=d.get('retrieved_at'), data_price=(d.get('quote') or {}).get('value'),
               currency=(d.get('quote') or {}).get('currency'), price_now=price_now,
               dislocation=None if not dis else {k: dis.get(k) for k in ('kind', 'ttm_eps', 'cons_0y', 'cons_1y', 'jump', 'pe_trailing', 'pe_forward', 'lines')},
               analyses=rows, status_quo=status_quo, plan=plan and dict(buy_below=plan.get('buy_below'), target_price=plan.get('target_price')),
               drivers=driver_table(assumptions, drivers), driver_options=DRIVERS)
    out['question'] = question_for(out)
    out['stale'] = any(r['stale'] for r in rows)
    return out
