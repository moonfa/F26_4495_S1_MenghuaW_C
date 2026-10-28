"""A turnaround case (trailing EPS at a trough, analysts expecting it to roughly double), run through the real enrichment offline."""
import unittest
from datetime import datetime, timezone
from app.adapters.valuation_references import enrich
from app.core.compare import compare, build
from app.core.valuation import Assumptions, calculate
from app.core.valuation_context import earnings_dislocation, fcf_anchors
from app.core.multiples import multiple_context, method_fit


def ts(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())


def raw(ttm_eps=3.12, c0=6.72, c1=7.19, pe_t=27.8, pe_f=12.07, price=86.73):
    hist = [('2026-06-30', 3.12), ('2025-06-30', 4.23), ('2024-06-30', 6.91), ('2023-06-30', 8.29)]
    d = dict(ticker='DEO', retrieved_at='2026-10-11T00:00:00+00:00', quote=dict(value=price, currency='USD'), warnings=[], raw={}, methods={},
             anchors=[dict(id=f'annual:{e}', value=v, category='historical_reported', currency='USD', period_end=e) for e, v in hist],
             historical=[dict(period_end=e, diluted_eps=v, currency='USD', revenue=20e9, net_income=v * 5e8, ebitda=6e9, ebitda_margin=.3, source='x') for e, v in hist],
             estimates=[dict(metric='eps', period='0y', avg=c0, currency='USD', source='x'), dict(metric='eps', period='+1y', avg=c1, currency='USD', source='x'),
                        dict(metric='revenue', period='0y', avg=19.15e9, currency='USD', source='x'), dict(metric='revenue', period='+1y', avg=19.38e9, currency='USD', source='x')],
             cashflow=[], cashflow_ttm=None)
    info = dict(trailingPE=pe_t, forwardPE=pe_f, trailingEps=ttm_eps, forwardEps=c1, enterpriseToEbitda=15, financialCurrency='USD', currency='USD',
                nextFiscalYearEnd=ts(2027, 6, 30), mostRecentQuarter=ts(2026, 6, 30), marketCap=price * 5e8, sharesOutstanding=5e8,
                totalDebt=2e10, totalCash=2e9, ebitda=6e9, enterpriseValue=price * 5e8 + 1.8e10, totalRevenue=19.6e9, sector='Consumer Defensive', industry='Beverages - Wineries & Distilleries')
    return enrich(d, None, info, ())


def pe(**kw):
    base = dict(exit_fy='2029-06-30', required_return=.1, growth=.069, fade_to=.05, exit_pe=12.07, growth_spread=.03, pe_spread=.1)
    return Assumptions(**{**base, **kw})


class Turnaround(unittest.TestCase):
    def setUp(self):
        self.d = raw()

    def test_dislocation_is_detected_with_facts(self):
        x = self.d['earnings_dislocation']
        self.assertEqual(x['kind'], 'recovery'); self.assertGreater(x['jump'], 1.0)
        text = ' '.join(x['lines'])
        self.assertIn('3.12', text); self.assertIn('6.72', text); self.assertIn('27.8', text); self.assertIn('Highest annual EPS', text); self.assertIn('adjusted', text)

    def test_ordinary_growth_is_not_flagged(self):
        d = raw(ttm_eps=5.0, c0=5.5, c1=6.0, pe_t=20, pe_f=16.7)
        self.assertIsNone(d['earnings_dislocation'])
        self.assertIsNotNone(earnings_dislocation(dict(anchors=[dict(id='ttm', value=-1), dict(id='consensus:0y', value=2)], current_multiples={})))   # loss to profit

    def test_defaults_start_from_the_analyst_years_with_matching_multiple(self):
        q = self.d['defaults']['pe']
        self.assertEqual(q['multiple_on'], 'E0'); self.assertEqual(q['growth_source'], 'eps_e1')
        self.assertAlmostEqual(q['exit_pe'], 86.73 / 6.72, 1)            # price ÷ this year's analyst EPS, not the trough's 27.8×
        self.assertAlmostEqual(q['growth'], (7.19 / 6.72 - 1) * 100, 1)
        self.assertEqual(self.d['method_fit']['pe']['level'], 'caution')

    def test_default_result_is_growth_not_a_35_percent_artefact(self):
        a, _ = build(self.d, 'pe', 3, .1, 0, .05)
        r = calculate(self.d, a)
        base = r['scenarios'][1]
        self.assertLess(base['price_cagr'], .25); self.assertGreater(base['price_cagr'], .0)
        self.assertAlmostEqual(r['reference']['value'], 6.72)          # a priced-in recovery is split from this year's analyst figure, not the trough
        self.assertIn('recovery', r['reference']['why'])
        self.assertLess(abs(r['scenarios'][1]['multiple_effect']), .15)    # no +40% earnings / -25% multiple artefact

    def test_old_mistake_is_warned(self):
        """The trough's trailing multiple (27.8×) applied to the recovered analyst earnings: the screenshot case."""
        r = calculate(self.d, pe(exit_pe=27.8))
        self.assertGreater(r['scenarios'][1]['price_cagr'], .25)
        self.assertTrue(any(c['level'] == 'warn' and 'multiple expansion' in c['text'] for c in r['checks']))

    def test_recovery_is_explained_next_to_the_result(self):
        r = calculate(self.d, pe())
        self.assertTrue(any('far below analyst EPS' in c['text'] for c in r['checks']))

    def test_grid(self):
        a, _ = build(self.d, 'pe', 3, .1, 0, .05)
        r = calculate(self.d, a)
        g = r['grid']
        self.assertEqual(len(g['rows']), 4); self.assertIn('No recovery', g['rows'][3]['label'])
        vals = [c['value'] for c in g['columns']]; self.assertEqual(vals, sorted(vals))
        for row in g['rows']:
            cg = [c['cagr'] for c in row['cells']]; self.assertEqual(cg, sorted(cg))               # higher multiple, higher return
        for ci in range(len(g['columns'])):
            col = [row['cells'][ci]['cagr'] for row in g['rows']]; self.assertEqual(col, sorted(col, reverse=True))   # bigger shortfall, lower return
        mine = next(i for i, c in enumerate(g['columns']) if c['label'] == 'Your exit multiple')
        self.assertAlmostEqual(g['rows'][0]['cells'][mine]['price'], r['scenarios'][1]['future_price'], places=4)

    def test_compare_does_not_flag_or_inflate(self):
        other = raw(ttm_eps=5.0, c0=5.5, c1=6.0, pe_t=20, pe_f=16.7); other['ticker'] = 'ABC'
        row = compare([self.d, other], 3, .1, 0, .05)['rows']
        deo = next(x for x in row if x['ticker'] == 'DEO')
        pem = next(m for m in deo['methods'] if m['method'] == 'pe')
        self.assertLess(pem['base'], .12); self.assertFalse(pem['implausible'])
        self.assertEqual(deo['dislocation']['kind'], 'recovery')

    def test_sector_rule_of_thumb_is_display_only(self):
        ctx = multiple_context(self.d, 'pe')
        self.assertTrue(any(p['key'] == 'sector' for p in ctx['points']))
        self.assertEqual(ctx['reference_basis'], 'own historical median (annual, trailing basis)' if (self.d.get('historical_pe') or {}).get('count', 0) >= 3 else None)
        d = dict(self.d); d['historical_pe'] = {}
        self.assertIsNone(multiple_context(d, 'pe')['reference'])                      # a hand-set band never becomes the reference
        d['peers'] = [dict(forward_pe=v) for v in (10, 12, 14)]
        self.assertEqual(multiple_context(d, 'pe')['reference'], 12)
        d['peers'] = [dict(forward_pe=v) for v in (10, 12)]
        self.assertIsNone(multiple_context(d, 'pe')['reference'])                      # two peers: shown, not used


class FcfBasis(unittest.TestCase):
    def test_after_sbc_gets_its_own_multiple(self):
        from tests.fixtures_val import company
        d = company(price=60.0, sbc=(40e6,) * 4, ttm_cash=(170e6, -50e6, 40e6))
        by = d['defaults']['p_fcf']['by_basis']
        self.assertGreater(by['fcf_sbc']['exit_multiple'], by['fcf']['exit_multiple'])        # less cash flow, so a higher price multiple

    def test_cash_flow_own_period_end_wins(self):
        anchors, _ = fcf_anchors([], dict(period_end='2026-09-30', ocf=170, capex=-50), [], 100, 'USD', 'X', 'now', 'src', ttm_end='2026-06-30')
        self.assertEqual(anchors[0]['period_end'], '2026-09-30')
        anchors, _ = fcf_anchors([dict(period_end='2025-12-31', ocf=150, capex=-40, sbc=40)], dict(period_end='TTM', ocf=170, capex=-50, sbc=40),
                                 [dict(period_end='2025-12-31', net_income=100, diluted_shares=100)], 100, 'USD', 'X', 'now', 'src', ttm_end='2026-06-30')
        self.assertEqual(next(a for a in anchors if a['id'] == 'fcf:ttm')['period_end'], '2026-06-30')          # 'TTM' is not a date: fall back, and say so
        self.assertIn('latest reported quarter', next(a for a in anchors if a['id'] == 'fcf:ttm')['basis'])


if __name__ == '__main__':
    unittest.main()
