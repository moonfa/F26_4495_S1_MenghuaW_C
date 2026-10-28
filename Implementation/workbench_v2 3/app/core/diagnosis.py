"""Read-this-first notes for one calculated valuation: whether the method suits the company, what is unusual in its numbers, what the
answer depends on, and a few suggested settings the user may apply with one click.

Everything here is arithmetic and rules on the same period table and result the page shows. It changes no input by itself, never ranks a
company, and sends nothing anywhere. Numbers in the notes are the numbers on the page.

Three parts:
- flags: facts that make the result harder to trust (few analysts, a rebound growth rate, a share count that jumped, high leverage, a
  high dividend that the price return leaves out, a margin that moved, a multiple far above any reference);
- lenses: the Base case again with only the exit multiple (and, for the cautious lens, growth) changed, so the user sees how much of the
  answer is the multiple;
- suggestions: settings the user may apply; each says what it changes and why."""
from .multiples import CYCLICAL, multiple_context, method_fit, sector_band
from .period_table import table_of, fy_label
from .valuation import calculate
from .valuation_context import num
from .valuation_defaults import ceiling, GROWTH_CAP, DEFAULT_FADE

LABEL = {'pe': 'P/E', 'p_fcf': 'P/FCF', 'ev_ebitda': 'EV/EBITDA'}
FEW_ANALYSTS = 3
WIDE = 0.5               # (high − low) ÷ mean above this: the analysts disagree a lot
SHARE_JUMP = 0.15        # a fiscal-year change in shares above this: split, big issue or a share-class change
LEVERAGE = 4.0           # net debt ÷ EBITDA
DIVIDEND_NOTE = 0.03     # yield from which the price return is said to understate the total return
SPREAD_POINTS = 0.15     # lenses further apart than this (annual return) mean the answer is mostly the multiple
SHARE_CHANGE_WARN = 0.08


def mult_field(a):
    return 'exit_pe' if a.method == 'pe' else 'exit_multiple'


def _row(a):
    return {'pe': 'eps', 'p_fcf': 'fcf_per_share_sbc' if getattr(a, 'basis', 'fcf') == 'fcf_sbc' else 'fcf_per_share', 'ev_ebitda': 'revenue'}[a.method]


def _base(res):
    return next((s for s in res['scenarios'] if s['scenario'] == 'Base'), res['scenarios'][1])


def references(data, method):
    """(reference, low, label_ref, label_low): a middle and a low exit multiple from the data, else from the rule-of-thumb band."""
    ctx = multiple_context(data, method)
    pts = {p['key']: p for p in ctx['points']}
    ref, ref_label = ctx.get('reference'), ctx.get('reference_basis')
    band, why = sector_band(data, method)
    if ref is None and band:
        ref, ref_label = (band[0] + band[1]) / 2, (why or 'sector rule of thumb') + ', middle of the range'
    low, low_label = None, None
    if 'history' in pts:
        low, low_label = pts['history']['low'], 'own history low (trailing)'
    elif band:
        low, low_label = band[0], (why or 'sector rule of thumb') + ', bottom of the range'
    return ref, low, ref_label, low_label


def lenses(data, a, res):
    """Base case under four readings of the exit multiple. Only the multiple (and growth, in the cautious lens) changes."""
    mf = mult_field(a)
    mine = getattr(a, mf)
    td = ((res.get('start_multiple') if False else None))
    ref, low, ref_label, low_label = references(data, a.method)
    price = (data.get('quote') or {}).get('value')
    tbl = table_of(data)
    first = next((c for c in tbl['columns'] if c['kind'] == 'analyst'), None)
    cell = (tbl['rows'].get(_row(a)) or {}).get(first['key']) if first else None
    today = price / cell['value'] if (cell and cell['value'] > 0 and price and a.method != 'ev_ebitda') else None
    out = []

    def run(id_, label, what, mult, growth_factor=1.0):
        if mult is None or mult <= 0:
            return
        upd = {mf: mult}
        if growth_factor != 1.0 and a.growth > 0:
            upd['growth'] = a.growth * growth_factor
        try:
            r = calculate(data, a.model_copy(update=upd))
        except (ValueError, OverflowError):
            return
        b, bear, bull = _base(r), r['scenarios'][0], r['scenarios'][2]
        out.append(dict(id=id_, label=label, what=what, exit_multiple=mult, growth=upd.get('growth', a.growth), base=b['price_cagr'], bear=bear['price_cagr'],
                        bull=bull['price_cagr'], price=b['future_price'], meets=b['price_cagr'] >= a.required_return))
    run('yours', 'Your inputs', 'The settings in the form.', mine)
    if today and abs(today / mine - 1) > .05:
        run('today', "Today's multiple held", f"Exit at {today:.1f}x, what the market pays today on {fy_label(first['period_end'])}'s figure.", today)
    if ref and abs(ref / mine - 1) > .05:
        run('reference', 'Reference multiple', f'Exit at {ref:.1f}x: {ref_label}.', ref)
    if low and abs(low / mine - 1) > .05 and low < mine:
        run('cautious', 'Cautious', f'Exit at {low:.1f}x ({low_label}) and growth after the analyst years cut to 60% of yours.', low, .6)
    return out


def flags_for(data, a, res):
    tbl, out = table_of(data), []
    add = lambda id_, level, text: out.append(dict(id=id_, level=level, text=text))
    row = _row(a)
    cells = [(c, (tbl['rows'].get(row) or {}).get(c['key'])) for c in tbl['columns'] if c['kind'] == 'analyst']
    for c, x in cells:
        if not x or x.get('kind') != 'analyst':
            continue
        n = x.get('n')
        if n is not None and n < FEW_ANALYSTS:
            add('few_analysts', 'warn', f'Only {n:.0f} analyst{"s" if n != 1 else ""} cover {fy_label(c["period_end"])}: a mean of so few numbers is not a consensus.')
            break
        if x.get('low') is not None and x.get('high') is not None and x['value'] > 0 and (x['high'] - x['low']) / x['value'] > WIDE:
            add('wide_range', 'note', f'Analysts disagree a lot on {fy_label(c["period_end"])}: the lowest estimate is {x["low"]:,.2f} and the highest {x["high"]:,.2f} (mean {x["value"]:,.2f}).')
            break
    if res['user_years'] > 0 and a.growth > GROWTH_CAP / 100:
        add('high_growth', 'warn', f'Growth of {a.growth * 100:.0f}% in the first year after the analyst years is high. After a rebound year or from a small base it rarely repeats; check what supports it.')
    elif res['user_years'] > 0 and a.fade_to is None and a.growth > .08 and res['user_years'] > 1:
        add('no_fade', 'note', f'Growth stays at {a.growth * 100:.0f}% every year to the exit year. Growth usually fades; "Growth fades to" lets it.')
    sh = tbl['rows'].get('shares') or {}
    for k, x in sh.items():
        if x.get('growth') is not None and abs(x['growth']) > SHARE_JUMP:
            add('share_jump', 'warn', f'The share count changed by {x["growth"] * 100:+.0f}% in {fy_label(x["period_end"])}: a split, a large issue or a share-class change. Per-share history before it may not be comparable.')
            break
    b = data.get('market_baseline') or {}
    if b.get('net_debt') and b.get('ebitda') and b['ebitda'] > 0 and b['net_debt'] / b['ebitda'] > LEVERAGE:
        add('leverage', 'note', f'Net debt is {b["net_debt"] / b["ebitda"]:.1f}x EBITDA. With that much debt a small change in the enterprise value moves the share price a lot, and P/E and EV/EBITDA can disagree.')
    dy = (data.get('current_multiples') or {}).get('dividend_yield')
    if dy and dy >= DIVIDEND_NOTE:
        add('dividend', 'note', f'The dividend yield is about {dy * 100:.1f}%. Returns here are price returns: add roughly {dy * 100:.1f} points a year if the dividend is kept and you spend it, to compare with your {a.required_return * 100:.0f}% requirement.')
    sc = getattr(a, 'share_change', 0) or 0
    if abs(sc) >= SHARE_CHANGE_WARN:
        last = (sh.get('A0') or {}).get('growth')
        add('share_change', 'warn', f'A share-count change of {sc * 100:+.0f}% a year is very large' + (f' (the last reported year was {last * 100:+.1f}%)' if last is not None else '') + '. Check the sign and the size.')
    fb = tbl.get('fcf_base') or {}
    m = tbl['rows'].get('fcf_margin') or {}
    if a.method == 'p_fcf' and m.get('A0') and m.get('TTM') and m['A0']['value'] > 0 and abs(m['TTM']['value'] / m['A0']['value'] - 1) > .15:
        add('margin_moved', 'note', f'The cash-flow margin moved from {m["A0"]["value"] * 100:.1f}% of revenue in {fy_label(m["A0"]["period_end"])} to {m["TTM"]["value"] * 100:.1f}% over the last twelve months. The analyst years use the '
            + ('newer one' if fb.get('which') == 'TTM' else 'reported-year one (the trailing figure is not positive)') + '.')
    if data.get('industry') in CYCLICAL and a.method != 'ev_ebitda':
        mm = [x['value'] for k, x in (tbl['rows'].get('ebitda_margin') or {}).items() if k.startswith('A')]
        if len(mm) >= 3:
            add('cyclical', 'note', f'Cyclical business: the EBITDA margin has ranged from {min(mm) * 100:.0f}% to {max(mm) * 100:.0f}% in the reported years. A multiple on a peak year looks low and on a trough year looks high; compare at a mid-cycle level.')
    cap = ceiling(data, a.method)
    mine = getattr(a, mult_field(a))
    if cap and mine > 1.5 * cap:
        add('multiple_far_above', 'warn', f'Your exit {LABEL[a.method]} of {mine:.1f}x is more than 1.5x the top of the reference range ({cap:.0f}x). Holding it means the market pays a growth premium after your growth has faded.')
    return out


def assumes(data, a, res):
    """What the price already asks for: the figure needed at exit for the required return, at a few multiples, against the last known figure."""
    if a.method == 'ev_ebitda':
        r = res['reverse']
        return dict(lines=[f'To earn {a.required_return * 100:.0f}% a year the exit EBITDA must reach {r["required_ebitda"]:,.0f}, a margin of {r["required_margin"] * 100:.1f}% on your Base revenue (or an exit EV/EBITDA of {r["required_exit_multiple"]:.1f}x on your Base EBITDA).'])
    last = res['anchor']['value']
    noun = 'EPS' if a.method == 'pe' else 'free cash flow per share'
    need_price = res['required_exit_price']
    ref, low, _, _ = references(data, a.method)
    ms = sorted({round(m, 1) for m in (low, ref, getattr(a, mult_field(a))) if m})
    rows = [dict(multiple=m, needed=need_price / m, vs_last=need_price / m / last if last > 0 else None) for m in ms]
    lines = [f'To earn {a.required_return * 100:.0f}% a year until {res["exit_date"]} the price must reach {need_price:,.2f} (from {data["quote"]["value"]:,.2f}).',
             f'The last figure the analysts or reports give is {noun} {last:,.2f} ({res["anchor"]["label"]}). At an exit multiple of ' +
             '; '.join(f'{r["multiple"]:g}x it needs {noun} {r["needed"]:,.2f}' + (f' ({r["vs_last"]:.1f}x that figure)' if r['vs_last'] else '') for r in rows) + '.']
    return dict(lines=lines, rows=rows, price=need_price, last=last, noun=noun)


def suggestions(data, a, res, lens, fit):
    out = []
    mf = mult_field(a)
    mine = getattr(a, mf)
    ref, _, ref_label, _ = references(data, a.method)
    if ref and mine > 1.25 * ref:
        out.append(dict(id='ref_multiple', label=f'Exit {LABEL[a.method]} {ref:.1f}x', set={'multiple': round(ref, 1)},
                        why=f'Your {mine:.1f}x is more than 25% above {ref_label} ({ref:.1f}x). A growth premium rarely lasts once growth fades.'))
    if res['user_years'] > 0 and a.growth > GROWTH_CAP / 100:
        out.append(dict(id='cap_growth', label=f'First-year growth {GROWTH_CAP:.0f}%', set={'growth': GROWTH_CAP}, why='A first year above 25% after the analyst years rarely repeats.'))
    if res['user_years'] > 1 and a.fade_to is None and a.growth > .08:
        out.append(dict(id='fade', label=f'Fade growth to {DEFAULT_FADE:.0f}%', set={'fade': DEFAULT_FADE}, why='Growth that stays at the same rate for years is rare.'))
    if abs(getattr(a, 'share_change', 0) or 0) >= SHARE_CHANGE_WARN:
        out.append(dict(id='share_change', label='Share count change 0%', set={'sharechg': 0.0}, why='A change this large each year is usually a typing or sign error.'))
    if a.method == 'p_fcf' and getattr(a, 'basis', 'fcf') == 'fcf' and (fit.get('p_fcf') or {}).get('use_after_sbc'):
        out.append(dict(id='after_sbc', label='Cash flow after stock compensation', set={'fcfbasis': 'fcf_sbc'}, why='Stock compensation is a large part of free cash flow, so before-compensation cash flow overstates what belongs to shareholders.'))
    if res['years'] < 1.5:
        opts = [o for o in table_of(data).get('exit_options') or [] if o['years'] >= 2.5]
        if opts:
            o = opts[0]
            out.append(dict(id='longer', label=f'Sell at the end of {o["fy"]}', set={'exit_fy': o['period_end']}, why=f'Annualising a return over {res["years"]:.1f} years exaggerates small differences; about three years is steadier.'))
    return out


def diagnose(data, a, res):
    """The whole block for one result. Returns a plain dict (stored with a saved analysis)."""
    fit = data.get('method_fit') or method_fit(data)
    mf = fit.get(a.method) or dict(level='fit', reasons=[])
    fl = flags_for(data, a, res)
    ls = lenses(data, a, res)
    if len(ls) > 1:
        vals = [x['base'] for x in ls]
        if max(vals) - min(vals) > SPREAD_POINTS:
            fl.append(dict(id='multiple_driven', level='warn', text=f'The Base return ranges from {min(vals) * 100:.1f}% to {max(vals) * 100:.1f}% a year depending only on the exit multiple (and, in one case, growth). Most of the answer is the multiple you choose, not the company.'))
    warns = sum(1 for f in fl if f['level'] == 'warn')
    level = 'weak' if mf['level'] == 'avoid' else ('care' if mf['level'] == 'caution' or warns else 'ok')
    head = {'weak': f'{LABEL[a.method]} does not suit this company.', 'care': f'Use {LABEL[a.method]} with care here.', 'ok': 'No rule flags this result.'}[level]
    grid = res.get('grid')
    cells = [c for r in (grid or {}).get('rows', []) for c in r['cells'] if c.get('cagr') is not None]
    return dict(level=level, headline=head, fit_reasons=mf['reasons'], flags=fl, lenses=ls, assumes=assumes(data, a, res),
                suggestions=suggestions(data, a, res, ls, fit), grid_meets=dict(meets=sum(1 for c in cells if c['meets']), total=len(cells)) if cells else None,
                dividend=(lambda dy: dict(yield_=dy, approx_total=_base(res)['price_cagr'] + dy) if dy else None)((data.get('current_multiples') or {}).get('dividend_yield')))
