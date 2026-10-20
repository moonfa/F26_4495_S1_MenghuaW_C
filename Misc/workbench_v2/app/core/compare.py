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
from .valuation_context import pick_pe_anchor, pfcf_defaults

METHODS = ('pe', 'p_fcf', 'ev_ebitda')
LABEL = {'pe': 'P/E', 'p_fcf': 'P/FCF', 'ev_ebitda': 'EV/EBITDA'}
GROWTH_SOURCE = {'eps_cons': 'analyst EPS growth (next year over this year)', 'rev_cons': 'analyst revenue growth (next year over this year)',
                 'fcf_last': 'last annual free cash flow per share growth', 'rev_last': 'last reported annual revenue growth'}


def _frac(v):
    return None if v is None else v / 100


def _what(anchor):
    kind = {'market_consensus': 'analyst EPS for the year to', 'ttm_reported': 'trailing-twelve-month figure to',
            'historical_reported': 'reported annual figure for the year to'}.get(anchor.get('category'), 'figure to')
    return f'{kind} {anchor.get("period_end")}'


def _growth_text(g, fade_to, source):
    s = f'growth {g}%/yr ({GROWTH_SOURCE.get(source, "provider data")})'
    return s + (f' fading to {fade_to * 100:.1f}%' if fade_to is not None else ', held flat')


def build(data, method, years, required_return, shift, fade_to=None):
    """Return (assumptions, note) or (None, reason)."""
    d = data.get('defaults') or {}
    price = data['quote'].get('value')
    ret = required_return if required_return is not None else 0.0
    shift = shift or 0.0
    if method == 'pe':
        q = d.get('pe') or {}
        anchor = pick_pe_anchor(data)
        if not anchor:
            return None, 'no positive EPS anchor'
        if q.get('growth') is None:
            return None, 'no analyst EPS growth (needs 0y and +1y consensus)'
        if not price or price <= 0:
            return None, 'no price'
        m0 = price / anchor['value']
        if m0 * (1 + shift) > 500:
            return None, f'REVIEW:P/E: today\'s multiple is {m0:.0f}× on the starting EPS, so the base is too small for a meaningful projection.'
        return Assumptions(method='pe', anchor_id=anchor['id'], years=years, required_return=ret, growth=_frac(q['growth']), fade_to=fade_to,
                           exit_pe=m0 * (1 + shift), growth_spread=_frac(q['growth_spread']), pe_spread=_frac(q['pe_spread']),
                           acknowledge_basis=True), \
            f'starts from {_what(anchor)} ({anchor["value"]:.2f}); {_growth_text(q["growth"], fade_to, q.get("growth_source"))}; exit P/E {m0 * (1 + shift):.1f}× = price ÷ that starting EPS' + (f' {shift * 100:+.0f}%' if shift else '')
    if method == 'p_fcf':
        q = d.get('p_fcf') or {}
        after = ((data.get('method_fit') or {}).get('p_fcf') or {}).get('use_after_sbc')
        anchor, _ = pfcf_defaults(data, after)
        if not anchor:
            return None, 'no positive free cash flow per share'
        g, src = q.get('growth'), q.get('growth_source')
        if g is None:
            g, src = (d.get('pe') or {}).get('growth'), 'eps_cons'
        if g is None:
            return None, 'no growth estimate for FCF'
        if not price or price <= 0:
            return None, 'no price'
        m0 = price / anchor['value']
        if m0 * (1 + shift) > 300:
            return None, f'REVIEW:P/FCF: today\'s multiple is {m0:.0f}× on the starting value, so the base is too small for a meaningful projection.'
        proxy = src in ('eps_cons', 'rev_cons')
        return PfcfAssumptions(method='p_fcf', anchor_id=anchor['id'], years=years, required_return=ret, growth=_frac(g), fade_to=fade_to,
                               growth_spread=_frac(q['growth_spread']), share_change=0.0, exit_multiple=m0 * (1 + shift),
                               multiple_spread=_frac(q['multiple_spread']), acknowledge_basis=True), \
            f'starts from {anchor["id"]} {anchor["value"]:.2f}/share ({"after" if anchor["id"].startswith("fcfsbc") else "before"} stock compensation); {_growth_text(g, fade_to, src)}' + \
            ('; there is no free cash flow consensus, so this is a stand-in and not independent of the P/E result' if proxy else '') + f'; exit P/FCF {m0 * (1 + shift):.1f}× = price ÷ that starting value; no share count change'
    q = d.get('ev_ebitda') or {}
    b = data.get('market_baseline') or {}
    anchor = next((a for a in data.get('revenue_anchors') or [] if a['id'] == 'revenue:ttm' and (a.get('value') or 0) > 0), None)
    if not anchor:
        return None, 'no trailing-twelve-month revenue'
    for key, why in (('growth', 'no revenue growth'), ('margin', 'no EBITDA margin'), ('exit_multiple', 'no current EV/EBITDA')):
        if q.get(key) is None:
            return None, why
    if b.get('net_debt') is None or not b.get('shares') or b.get('currency') != data['quote'].get('currency'):
        return None, 'current net debt / shares unavailable or in another currency'
    return EbitdaAssumptions(method='ev_ebitda', anchor_id=anchor['id'], years=years, required_return=ret, growth=_frac(q['growth']), fade_to=fade_to,
                             growth_spread=_frac(q['growth_spread']), margin=_frac(q['margin']), margin_spread=_frac(q['margin_spread']),
                             exit_multiple=q['exit_multiple'] * (1 + shift), multiple_spread=_frac(q['multiple_spread']),
                             target_net_debt=b['net_debt'], target_shares=b['shares'], other_claims=0.0,
                             balance_assumption='hold_current_constant', acknowledge_basis=True), \
        f'starts from trailing revenue; {_growth_text(q["growth"], fade_to, q.get("growth_source"))}; margin {q["margin"]}% ({"trailing, EBITDA ÷ revenue" if q.get("margin_source") == "ttm" else "last reported annual"}); current net debt and shares held constant'


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
        if m in ('pe', 'p_fcf') and m0 > 100:
            out['review'].append(f'{LABEL[m]}: today\'s multiple is {m0:.0f}× on the starting value, so the base is too small for a meaningful projection.')
        if m == 'p_fcf' and (data.get('share_check') or {}).get('differs'):
            out['review'].append('P/FCF: the provider share count and market cap ÷ price differ by more than 25% (ADR ratio or several share classes), so per-share cash flow is unverified.')
        out['methods'].append(dict(method=m, label=LABEL[m], anchor=r['anchor']['id'], note=note, growth_years=r['growth_years'],
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
        out.update(primary=pref[0]['method'], conservative=min(base), dispersion=max(base) - min(base),
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
                notes=['Default scenarios: start from the furthest analyst year where there is one (else trailing twelve months), grow it at the analyst rate ' + ('fading linearly to %.1f%% by the exit date' % (fade_to * 100) if fade_to is not None else 'held flat for the whole period') + ', and keep today\'s multiple on that same starting number (price ÷ starting value) ± the shift. '
                       'They show what current numbers imply; they are not forecasts of your own.',
                       'Ranked by the lowest Base annual price return among the applicable methods, with that multiple held. "If the multiple de-rates" repeats the calculation with the exit multiple lowered to a reference when today\'s is above it; the reference is the median of at least 3 peers, else the company\'s own annual P/E history, and a hand-set sector range is never used. Methods are not averaged; a gap above 10 points is flagged.',
                       'A row with an implausible default result, or a share-count mismatch, keeps its numbers but is not ranked: dropping the odd method would make the others look better. Open the company to check.',
                       'Annual price return excludes dividends. Analyst numbers are provider consensus with an unverified reported/adjusted basis; where a turnaround is flagged, part of the gap may be accounting basis. Not a forecast, a rating or a prediction track record.'])
