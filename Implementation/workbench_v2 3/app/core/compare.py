"""Side-by-side comparison: for each ticker, run every applicable method from data-derived status-quo assumptions and report
annualised price returns on a common horizon. Nothing here is a view or a target; it shows what the company's own numbers,
analyst expectations and today's multiples imply, so different tickers can be put on the same scale.

Defaults start from the furthest analyst year when there is one (else trailing twelve months), grow it at the analyst rate fading
to a long-run rate, and keep today's multiple ON THAT SAME STARTING NUMBER (price ÷ starting value). So holding the multiple flat
adds nothing and the result is the growth, not a change of basis.

Methods are never averaged. A ticker is ranked by its most conservative Base result only when every default input passed its
checks; a result that looks implausible stays visible with its numbers but the row is not ranked, because dropping it would
flatter the ones left."""
from .multiples import derate_target
from .valuation import (Assumptions, EbitdaAssumptions, PfcfAssumptions, calculate)
from .period_table import table_of, nearest_exit

METHODS = ('pe', 'p_fcf', 'ev_ebitda')
LABEL = {'pe': 'P/E', 'p_fcf': 'P/FCF', 'ev_ebitda': 'EV/EBITDA'}
GROWTH_SOURCE = {'eps_e1': 'analyst EPS growth, the last analyst year', 'eps_e0': 'analyst EPS growth, this year', 'eps_last': 'last reported EPS growth',
                 'rev_e1': 'analyst revenue growth, the last analyst year', 'rev_e0': 'analyst revenue growth, this year', 'rev_last': 'last reported revenue growth',
                 'fcf_last': 'last annual free cash flow per share growth'}


def _frac(v):
    return None if v is None else v / 100


def _growth_text(g, fade_to, source):
    s = f'growth {g}%/yr in the first year after the analyst years ({GROWTH_SOURCE.get(source, "provider data")})'
    return s + (f' fading to {fade_to * 100:.1f}%' if fade_to is not None else ', held flat')


def build(data, method, years, required_return, shift, fade_to=None):
    """Return (assumptions, note) or (None, reason). The exit is the fiscal year end nearest to `years` from the valuation date."""
    d = data.get('defaults') or {}
    price = data['quote'].get('value')
    ret = required_return if required_return is not None else 0.0
    shift = shift or 0.0
    if not price or price <= 0:
        return None, 'no price'
    opt = nearest_exit(table_of(data), years)
    if not opt:
        return None, 'no fiscal year end to exit at'
    where = f'sold at the end of {opt["fy"]} ({opt["years"]:.1f} years)'
    q = d.get(method) or {}

    def need(*keys):
        for k, why in keys:
            if q.get(k) is None:
                if k.startswith('exit') and q.get('multiple_note'):
                    return 'REVIEW:' + LABEL[method] + ': ' + q['multiple_note']
                return why
        return None
    on = 'this year\'s' if q.get('multiple_on') == 'E0' else 'trailing'
    if method == 'pe':
        bad = need(('growth', 'no analyst EPS growth (needs analyst or reported EPS for two years)'), ('exit_pe', 'no positive EPS to read today\'s multiple on'))
        if bad:
            return None, bad
        m = q['exit_pe'] * (1 + shift)
        return Assumptions(method='pe', exit_fy=opt['period_end'], required_return=ret, growth=_frac(q['growth']), fade_to=fade_to, exit_pe=m,
                           growth_spread=_frac(q['growth_spread']), pe_spread=_frac(q['pe_spread'])), \
            f'{where}; analyst EPS as given, then {_growth_text(q["growth"], fade_to, q.get("growth_source"))}; exit P/E {m:.1f}× = today\'s multiple on {on} EPS' + (f' {shift * 100:+.0f}%' if shift else '')
    if method == 'p_fcf':
        bad = need(('growth', 'no growth estimate for FCF (needs revenue or cash-flow history for two years)'), ('exit_multiple', 'no positive free cash flow per share'))
        if bad:
            return None, bad
        m = q['exit_multiple'] * (1 + shift)
        proxy = (q.get('growth_source') or '').startswith(('rev', 'eps'))
        return PfcfAssumptions(method='p_fcf', basis=q.get('basis', 'fcf'), exit_fy=opt['period_end'], required_return=ret, growth=_frac(q['growth']), fade_to=fade_to,
                               growth_spread=_frac(q['growth_spread']), share_change=0.0, exit_multiple=m, multiple_spread=_frac(q['multiple_spread'])), \
            f'{where}; free cash flow per share ({"after" if q.get("basis") == "fcf_sbc" else "before"} stock compensation) grown with analyst revenue, then {_growth_text(q["growth"], fade_to, q.get("growth_source"))}' + \
            ('; there is no free cash flow consensus, so this is a stand-in and not independent of the P/E result' if proxy else '') + f'; exit P/FCF {m:.1f}× = today\'s multiple on {on} cash flow; no share count change'
    b = data.get('market_baseline') or {}
    bad = need(('growth', 'no revenue growth'), ('margin', 'no EBITDA margin'), ('exit_multiple', 'no current EV/EBITDA'))
    if bad:
        return None, bad
    if b.get('net_debt') is None or not b.get('shares') or b.get('currency') != data['quote'].get('currency'):
        return None, 'current net debt / shares unavailable or in another currency'
    return EbitdaAssumptions(method='ev_ebitda', exit_fy=opt['period_end'], required_return=ret, growth=_frac(q['growth']), fade_to=fade_to,
                             growth_spread=_frac(q['growth_spread']), margin=_frac(q['margin']), margin_spread=_frac(q['margin_spread']),
                             exit_multiple=q['exit_multiple'] * (1 + shift), multiple_spread=_frac(q['multiple_spread']),
                             target_net_debt=b['net_debt'], target_shares=b['shares'], other_claims=0.0, balance_assumption='hold_current_constant'), \
        f'{where}; analyst revenue as given, then {_growth_text(q["growth"], fade_to, q.get("growth_source"))}; margin {q["margin"]}% ({"trailing, EBITDA ÷ revenue" if q.get("margin_source") == "ttm" else "last reported annual"}); current net debt and shares held constant'


def _run(data, m, years, required_return, shift, fade_to=None):
    a, note = build(data, m, years, required_return, shift, fade_to)
    if a is None:
        return None, note, None
    return a, note, calculate(data, a)


def ticker_row(data, years, required_return=None, shift=0.0, fade_to=None):
    dis = data.get('earnings_dislocation')
    out = dict(ticker=data['ticker'], name=data.get('name'), sector=data.get('sector'), industry=data.get('industry'), price=data['quote'].get('value'), currency=data['quote'].get('currency'),
               methods=[], skipped=[], review=[], flags=list(data.get('earnings_quality_flags') or []),
               dislocation=None if not dis else {k: dis.get(k) for k in ('kind', 'ttm_eps', 'cons_0y', 'cons_1y', 'jump')})
    fit = data.get('method_fit') or {}
    for m in METHODS:
        f = fit.get(m) or {}
        if f.get('level') == 'avoid':
            out['skipped'].append(dict(method=m, reason='not suitable: ' + ' '.join(f.get('reasons') or []))); continue
        try:
            a, note, r = _run(data, m, years, required_return, shift, fade_to)
        except (ValueError, OverflowError, KeyError, TypeError) as e:
            a, note, r = None, str(e)[:160], None
        if r is None:
            if note.startswith('REVIEW:'):
                note = note[7:]; out['review'].append(note)
            out['skipped'].append(dict(method=m, reason=note)); continue
        derate, ref_basis, ref_value = None, None, None
        held = a.exit_pe if m == 'pe' else a.exit_multiple
        m0 = held / (1 + (shift or 0))                     # today's multiple on the starting point, before any shift
        target, ref_basis = derate_target(data, m, held)
        if ref_basis and target < held - 1e-9:
            try:
                _, _, rd = _run(data, m, years, required_return, target / m0 - 1, fade_to)
                derate, ref_value = rd, target
            except (ValueError, OverflowError):
                pass
        sc = {x['scenario']: x for x in r['scenarios']}
        implausible = not -.5 <= sc['Base']['price_cagr'] <= .6
        if implausible:
            out['review'].append(f'{LABEL[m]}: Base {sc["Base"]["price_cagr"] * 100:.0f}%/yr from default inputs looks implausible, usually a data mismatch (ADR ratio, share class) or a very small base. Open the company to inspect.')
        if m == 'p_fcf' and (data.get('share_check') or {}).get('differs'):
            out['review'].append('P/FCF: the provider share count and market cap ÷ price differ by more than 25% (ADR ratio or several share classes), so per-share cash flow is unverified.')
        out['methods'].append(dict(method=m, label=LABEL[m], anchor=r['anchor']['id'], note=note, growth_years=r['growth_years'], exit_fy=r['exit_fy'], exit_date=r['exit_date'], years=r['years'],
            bear=sc['Bear']['price_cagr'], base=sc['Base']['price_cagr'], bull=sc['Bull']['price_cagr'],
            base_price=sc['Base']['future_price'], bear_price=sc['Bear']['future_price'], bull_price=sc['Bull']['future_price'],
            warnings=[c['text'] for c in r['checks'] if c['level'] == 'warn'], notes=[c['text'] for c in r['checks'] if c['level'] != 'warn'],
            assumptions=r['assumptions'], implausible=implausible,
            earnings_effect=sc['Base'].get('earnings_effect'), multiple_effect=sc['Base'].get('multiple_effect'),
            exit_multiple=sc['Base'].get('exit_pe', sc['Base'].get('exit_multiple')),
            derate_base=None if derate is None else next(x['price_cagr'] for x in derate['scenarios'] if x['scenario'] == 'Base'),
            derate_multiple=ref_value, reference_basis=ref_basis if derate else None,
            fit=f.get('level', 'fit'), fit_reasons=f.get('reasons', [])))
    ms = out['methods']
    if ms:
        base = [m['base'] for m in ms]
        rec = fit.get('recommended')
        pref = [m for m in ms if m['method'] == rec] or [m for m in ms if m['method'] == 'pe' and not out['flags']] or [m for m in ms if m['method'] != 'pe'] or ms
        out.update(exit_fy=ms[0]['exit_fy'], exit_date=ms[0]['exit_date'], years=ms[0]['years'], primary=pref[0]['method'], conservative=min(base), dispersion=max(base) - min(base),
                   worst_bear=min(m['bear'] for m in ms),
                   conservative_derate=min([m['derate_base'] if m['derate_base'] is not None else m['base'] for m in ms]), warn_count=sum(len(m['warnings']) for m in ms),
                   disagree=(max(base) - min(base)) > .10)
    return out


def compare(datas, years, required_return=None, shift=0.0, fade_to=None):
    rows = [ticker_row(d, years, required_return, shift, fade_to) for d in datas]
    ranked = sorted([r for r in rows if r['methods'] and not r['review']], key=lambda r: r['conservative'], reverse=True)
    for i, r in enumerate(ranked, 1):
        r['rank'] = i
    rest = [r for r in rows if r['methods'] and r['review']] + [r for r in rows if not r['methods']]
    return dict(years=years, required_return=required_return, multiple_shift=shift, fade_to=fade_to, rows=ranked + rest,
                notes=['Default scenarios: each company is sold at the fiscal year end nearest to your holding period (the exit year and the exact years are shown per company). The analysts\' years are used as given; your growth starts at the rate they end on ' + ('and fades linearly to %.1f%% by the exit year' % (fade_to * 100) if fade_to is not None else 'and is held flat') + ', and the exit multiple is what the market pays today on this year\'s figure (trailing basis) ± the shift. '
                       'They show what current numbers imply; they are not forecasts of your own.',
                       'Ranked by the lowest Base annual price return among the applicable methods, with that multiple held. "If the multiple de-rates" repeats the calculation with the exit multiple lowered to a reference when today\'s is above it; the reference is the median of at least 3 peers, else the company\'s own annual P/E history, and a hand-set sector range is never used. Methods are not averaged; a gap above 10 points is flagged.',
                       'A row with an implausible default result, or a share-count mismatch, keeps its numbers but is not ranked: dropping the odd method would make the others look better. Open the company to check.',
                       'Annual price return excludes dividends. Analyst numbers are provider consensus with an unverified reported/adjusted basis; where a turnaround is flagged, part of the gap may be accounting basis. Not a forecast, a rating or a prediction track record.'])
