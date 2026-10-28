"""The valuation engine (formula valuation-v4), checked against hand calculations on an offline company."""
import copy
import math
import unittest

from app.core.valuation import (Assumptions, EbitdaAssumptions, PfcfAssumptions, calculate, consensus_bridge, rates, FORMULA)
from app.core.valuation_context import historical_pe
from tests.fixtures_val import company, days_to


def pe(**kw):
    base = dict(exit_fy='2029-12-31', required_return=.1, growth=.10, fade_to=.06, exit_pe=20, growth_spread=.05, pe_spread=.2)
    return Assumptions(**{**base, **kw})


def pfcf(**kw):
    base = dict(method='p_fcf', basis='fcf', exit_fy='2029-12-31', required_return=.1, growth=.10, growth_spread=.03, share_change=-.02, exit_multiple=17, multiple_spread=.1)
    return PfcfAssumptions(**{**base, **kw})


def ev(**kw):
    base = dict(method='ev_ebitda', exit_fy='2028-12-31', required_return=.1, growth=.08, growth_spread=.02, margin=.25, margin_spread=.02, exit_multiple=8,
                multiple_spread=.1, target_net_debt=60e6, target_shares=50e6, other_claims=20e6, balance_assumption='user_forecast')
    return EbitdaAssumptions(**{**base, **kw})


class GrowthPath(unittest.TestCase):
    def test_straight_line_from_first_year_to_fade(self):
        self.assertEqual(rates(.10, .06, 3), [.10, .08, .06]) if False else None
        r = rates(.10, .06, 3)
        self.assertAlmostEqual(r[0], .10); self.assertAlmostEqual(r[1], .08); self.assertAlmostEqual(r[2], .06)
        self.assertEqual(rates(.10, None, 3), [.10] * 3); self.assertEqual(rates(.10, .06, 1), [.10]); self.assertEqual(rates(.1, .05, 0), [])


class PeMath(unittest.TestCase):
    def setUp(self):
        self.d = company()

    def test_base_price_is_analyst_years_then_users_years_times_multiple(self):
        r = calculate(self.d, pe())
        eps = 2.5 * 1.10 * 1.06                                 # FY2027 analyst EPS, then FY2028 at 10%, FY2029 at the faded 6%
        base = r['scenarios'][1]
        self.assertAlmostEqual(base['eps'], eps); self.assertAlmostEqual(base['future_price'], eps * 20)
        y = days_to(self.d, '2029-12-31')
        self.assertAlmostEqual(r['years'], y, places=2); self.assertEqual(r['formula_version'], FORMULA); self.assertEqual(r['user_years'], 2)
        self.assertAlmostEqual(base['price_cagr'], (eps * 20 / 44) ** (1 / r['years']) - 1)
        self.assertAlmostEqual(base['discounted_terminal'], eps * 20 / 1.1 ** r['years'])
        self.assertEqual([a['fy'] for a in r['analyst_years']], ['FY2026', 'FY2027'])

    def test_bear_and_bull_move_only_the_users_years_and_the_multiple(self):
        r = calculate(self.d, pe())
        bear, base, bull = r['scenarios']
        self.assertAlmostEqual(bear['eps'], 2.5 * 1.05 * 1.01); self.assertAlmostEqual(bull['eps'], 2.5 * 1.15 * 1.11)
        self.assertAlmostEqual(bear['exit_pe'], 16); self.assertAlmostEqual(bull['exit_pe'], 24)
        self.assertLess(bear['future_price'], base['future_price']); self.assertLess(base['future_price'], bull['future_price'])
        path = r['path']                                        # the analyst years in the path are the same whatever the scenario
        self.assertEqual([p['source'] for p in path], ['analyst', 'analyst', 'yours', 'yours'])
        self.assertAlmostEqual(path[0]['value'], 2.2); self.assertAlmostEqual(path[1]['value'], 2.5)

    def test_exit_in_an_analyst_year_ignores_growth(self):
        a = calculate(self.d, pe(exit_fy='2027-12-31', growth=.30, fade_to=.01))
        b = calculate(self.d, pe(exit_fy='2027-12-31', growth=-.20, fade_to=None))
        self.assertEqual(a['user_years'], 0)
        for x, y in zip(a['scenarios'], b['scenarios']): self.assertAlmostEqual(x['eps'], 2.5); self.assertAlmostEqual(x['future_price'], y['future_price'])
        self.assertNotEqual(a['scenarios'][0]['future_price'], a['scenarios'][2]['future_price'])       # the multiple still moves
        self.assertTrue(any('not used' in c['text'] for c in a['checks']))

    def test_holding_todays_multiple_on_this_years_figure_leaves_only_growth(self):
        """Exit multiple = price ÷ this year's EPS, read on the exit year's EPS: the return is the EPS growth from this year, nothing else."""
        r = calculate(self.d, pe(exit_pe=44 / 2.2, growth_spread=0, pe_spread=0))
        base = r['scenarios'][1]
        self.assertAlmostEqual(base['price_cagr'], (base['eps'] / 2.2) ** (1 / r['years']) - 1)

    def test_return_split_is_exact_against_trailing(self):
        r = calculate(self.d, pe())
        self.assertAlmostEqual(r['start_multiple'], 44 / 2.1); self.assertEqual(r['reference']['label'], 'TTM')
        for s in r['scenarios']:
            self.assertAlmostEqual((1 + s['earnings_effect']) * (1 + s['multiple_effect']), 1 + s['price_cagr'])
            self.assertAlmostEqual(1 + s['multiple_effect'], (s['exit_pe'] / (44 / 2.1)) ** (1 / r['years']))

    def test_reverse_calculation(self):
        r = calculate(self.d, pe()); y = r['years']; v = r['reverse']
        self.assertAlmostEqual(v['required_eps'] * 20, 44 * 1.1 ** y)
        self.assertAlmostEqual(2.5 * (1 + v['required_eps_growth']) ** 2, v['required_eps'])
        self.assertAlmostEqual(v['required_exit_pe'] * r['scenarios'][1]['eps'], 44 * 1.1 ** y)
        self.assertAlmostEqual(r['required_exit_price'], 44 * 1.1 ** y)
        self.assertIsNone(calculate(self.d, pe(exit_fy='2027-12-31'))['reverse']['required_eps_growth'])      # no user years to solve for

    def test_path_ends_at_the_base_price_and_starts_near_today(self):
        r = calculate(self.d, pe())
        self.assertAlmostEqual(r['path'][-1]['price'], r['scenarios'][1]['future_price'], places=6)
        self.assertAlmostEqual(r['path'][-1]['multiple'], 20)
        self.assertAlmostEqual(r['path'][0]['multiple'], 44 / 2.2, places=0)        # starts from today's multiple on this year's figure

    def test_fade_lowers_the_price(self):
        flat = calculate(self.d, pe(exit_fy='2031-12-31', fade_to=None, growth=.2)); fade = calculate(self.d, pe(exit_fy='2031-12-31', fade_to=.05, growth=.2))
        self.assertLess(fade['scenarios'][1]['future_price'], flat['scenarios'][1]['future_price'])

    def test_old_record_without_a_table_gives_the_same_result(self):
        d = copy.deepcopy(self.d); d.pop('period_table')
        self.assertEqual(calculate(d, pe())['scenarios'], calculate(self.d, pe())['scenarios'])

    def test_no_mutation(self):
        old = copy.deepcopy(self.d); calculate(self.d, pe()); self.assertEqual(self.d, old)


class Rejections(unittest.TestCase):
    def setUp(self):
        self.d = company()

    def test_exit_year_must_be_one_of_the_offered_fiscal_year_ends(self):
        for bad in ('2026-12-31', '2029-06-30', 'soon', '2040-12-31'):
            with self.assertRaises(ValueError): calculate(self.d, pe(exit_fy=bad))
        self.assertEqual(calculate(self.d, pe(exit_fy='FY2029'))['exit_fy'], 'FY2029')

    def test_missing_price_and_currency_mismatch(self):
        self.d['quote']['value'] = None
        with self.assertRaises(ValueError) as cm: calculate(self.d, pe())
        self.assertIn('price', str(cm.exception))
        d = company(currency='CAD', fin_currency='USD')
        with self.assertRaises(ValueError) as cm: calculate(d, pe())
        self.assertIn('no exchange rate', str(cm.exception))

    def test_loss_making_company_has_nothing_to_project(self):
        d = company(eps=(-1.0, -.8, -.5, -.2), est=None, ttm_eps=-.1)
        with self.assertRaises(ValueError): calculate(d, pe())

    def test_bear_growth_boundary(self):
        with self.assertRaises(ValueError): calculate(self.d, pe(growth=-.8, growth_spread=.3))

    def test_invalid_inputs(self):
        for kw in ({'growth': float('nan')}, {'exit_pe': float('inf')}, {'pe_spread': 1}, {'exit_pe': 0}, {'required_return': -1}):
            with self.assertRaises(ValueError): pe(**kw)
        with self.assertRaises(ValueError): Assumptions(required_return=.1, growth=.1, exit_pe=10, growth_spread=0, pe_spread=0)     # no exit year
        with self.assertRaises(ValueError): Assumptions(exit_fy='2029-12-31', years=3, required_return=.1, growth=.1, exit_pe=10, growth_spread=0, pe_spread=0)   # the old field is gone


class PfcfMath(unittest.TestCase):
    def setUp(self):
        self.d = company()

    def test_per_share_path_and_buybacks(self):
        r = calculate(self.d, pfcf()); b = r['scenarios'][1]
        ps = self.d['period_table']['rows']['fcf_per_share']['E1']['value'] * (1.10 / .98) ** 2    # FY2027 derived, then two user years with buybacks
        self.assertAlmostEqual(b['fcf_per_share'], ps); self.assertAlmostEqual(b['future_price'], ps * 17); self.assertAlmostEqual(b['fcf_yield'], 1 / 17)
        self.assertAlmostEqual(r['reverse']['required_exit_multiple'] * ps, 44 * 1.1 ** r['years'])
        self.assertTrue(any('no analyst forecast for free cash flow' in c['text'] for c in r['checks']))

    def test_after_sbc_basis_starts_lower(self):
        before = calculate(self.d, pfcf()); after = calculate(self.d, pfcf(basis='fcf_sbc', share_change=0))
        self.assertAlmostEqual(after['scenarios'][1]['fcf_per_share'], self.d['period_table']['rows']['fcf_per_share_sbc']['E1']['value'] * 1.1 ** 2)
        self.assertLess(after['scenarios'][1]['fcf_per_share'], before['scenarios'][1]['fcf_per_share'])
        self.assertTrue(any('second time' in c['text'] for c in calculate(self.d, pfcf(basis='fcf_sbc', share_change=.01))['checks']))

    def test_negative_cash_flow_cannot_be_projected(self):
        d = company(ocf=(10e6,) * 4, capex=(-30e6,) * 4, ttm_cash=(10e6, -30e6, 1e6))
        with self.assertRaises(ValueError): calculate(d, pfcf())


class EvMath(unittest.TestCase):
    def setUp(self):
        self.d = company()

    def test_equity_bridge_and_reverse(self):
        r = calculate(self.d, ev()); b = r['scenarios'][1]
        rev = 1210e6 * 1.08
        self.assertAlmostEqual(b['revenue'], rev); self.assertAlmostEqual(b['ebitda'], rev * .25)
        self.assertAlmostEqual(b['future_price'], (rev * .25 * 8 - 60e6 - 20e6) / 50e6)
        y = r['years']; needed = r['reverse']['required_ebitda']
        self.assertAlmostEqual((needed * 8 - 80e6) / 50e6, 44 * 1.1 ** y)
        self.assertAlmostEqual(r['reverse']['required_margin'] * rev, needed)
        self.assertAlmostEqual(b['ebitda'] * r['reverse']['required_exit_multiple'] - 80e6, 44 * 1.1 ** y * 50e6)
        self.assertEqual(r['scenarios'][0]['margin'], .23); self.assertAlmostEqual(r['scenarios'][2]['margin'], .27)

    def test_net_cash_and_floor(self):
        cash = calculate(self.d, ev(target_net_debt=-60e6)); debt = calculate(self.d, ev())
        self.assertAlmostEqual(cash['scenarios'][1]['future_price'] - debt['scenarios'][1]['future_price'], 120e6 / 50e6)
        loss = calculate(self.d, ev(target_net_debt=1e12))['scenarios'][1]
        self.assertEqual((loss['future_price'], loss['price_cagr'], loss['equity_floor_applied']), (0, -1, True))

    def test_invalid_basis(self):
        for kw in (dict(margin=.01, margin_spread=.02), dict(margin=.95, margin_spread=.1), dict(balance_assumption='hold_current_constant', target_shares=11)):
            with self.assertRaises(ValueError): calculate(self.d, ev(**kw))
        ok = calculate(self.d, ev(balance_assumption='hold_current_constant', target_net_debt=60e6, target_shares=50e6))
        self.assertEqual(ok['assumptions']['balance_assumption'], 'hold_current_constant')


class Checks(unittest.TestCase):
    def setUp(self):
        self.d = company()

    def test_multiple_expansion_warns_against_todays_multiple_on_this_years_figure(self):
        r = calculate(self.d, pe(exit_pe=40))
        self.assertTrue(any(c['level'] == 'warn' and 'multiple expansion' in c['text'] for c in r['checks']))
        self.assertTrue(any('de-rating' in c['text'] for c in calculate(self.d, pe(exit_pe=8))['checks']))
        self.assertFalse(any('multiple expansion' in c['text'] for c in calculate(self.d, pe())['checks']))

    def test_growth_above_the_analysts_warns_and_users_years_are_counted(self):
        r = calculate(self.d, pe(growth=.4, growth_spread=0))
        self.assertTrue(any(c['level'] == 'warn' and 'analysts' in c['text'] for c in r['checks']))
        self.assertTrue(any('2 of the years to FY2029 rest' in c['text'] for c in r['checks']))

    def test_stale_reported_year_warns(self):
        d = company(valuation='2027-06-01', next_fy='2027-12-31', est=(2.2, 2.5, 1100e6, 1210e6))
        self.assertTrue(any('months ago' in c['text'] for c in calculate(d, pe(exit_fy='2029-12-31'))['checks']))

    def test_grid(self):
        r = calculate(self.d, pe()); g = r['grid']
        self.assertEqual([x['label'] for x in g['rows']][:3], ['Your Base path', 'Falls 20% short', 'Falls 40% short'])
        vals = [c['value'] for c in g['columns']]; self.assertEqual(vals, sorted(vals))
        for row in g['rows']:
            cg = [c['cagr'] for c in row['cells']]; self.assertEqual(cg, sorted(cg))
        mine = next(i for i, c in enumerate(g['columns']) if c['label'] == 'Your exit multiple')
        self.assertAlmostEqual(g['rows'][0]['cells'][mine]['price'], r['scenarios'][1]['future_price'], places=4)

    def test_no_recovery_row_when_trailing_earnings_are_far_below(self):
        d = company(eps=(2.0, 1.5, 1.0, .6), ttm_eps=.6, est=(1.6, 2.0, 1100e6, 1210e6), price=30)
        g = calculate(d, pe(exit_pe=15))['grid']
        self.assertTrue(any('No recovery' in r['label'] for r in g['rows']))


class OtherBits(unittest.TestCase):
    def test_historical_pe_no_future_price_or_negative_eps(self):
        rows = [dict(period_end='2025-12-31', diluted_eps=2, currency='USD'), dict(period_end='2024-12-31', diluted_eps=-1, currency='USD')]
        prices = [dict(date='2025-12-30', close=40), dict(date='2026-01-01', close=1000), dict(date='2024-12-31', close=20)]
        r = historical_pe(rows, prices, 'USD')
        self.assertEqual(r['rows'][0]['pe'], 20); self.assertEqual(r['rows'][0]['price_date'], '2025-12-30')
        self.assertTrue(r['rows'][1]['pe'] is None and r['count'] == 1)
        self.assertEqual(historical_pe(rows, prices, 'CAD')['count'], 0)
        self.assertEqual(historical_pe(rows, [dict(date='2025-12-01', close=40)], 'USD')['count'], 0)

    def test_consensus_bridge_is_not_quarter_annualisation(self):
        d = dict(quote=dict(value=50, currency='USD'), estimates=[dict(metric='eps', period='0q', avg=1, currency='USD'), dict(metric='eps', period='+1y', avg=4, currency='USD')])
        r = consensus_bridge(d, 20, .1)
        self.assertEqual(len(r['rows']), 1); self.assertEqual([x['price'] for x in r['rows'][0]['prices']], [72, 80, 88])
        self.assertNotIn('price_cagr', r['rows'][0]['prices'][0])
        d['estimates'][1]['currency'] = 'CAD'
        self.assertIn('error', consensus_bridge(d, 20, .1)['rows'][0])


if __name__ == '__main__':
    unittest.main()
