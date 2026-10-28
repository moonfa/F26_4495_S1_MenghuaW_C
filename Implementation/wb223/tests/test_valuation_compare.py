"""Compare (several companies on one scale), free cash flow rows, growth sources and method fit, on offline company fixtures (valuation-v4)."""
import unittest

from app.core.compare import compare, build
from app.core.valuation import PfcfAssumptions, Assumptions, calculate
from app.core.valuation_context import fcf_anchors, fcf_status_quo, fcf_of, industry_summary, consensus_quarter_end
from app.core.valuation_defaults import growth_refs
from app.core.multiples import method_fit
from tests.fixtures_val import company


class Fcf(unittest.TestCase):
    def test_fcf_of(self):
        self.assertEqual(fcf_of(dict(ocf=100, capex=-30)), 70)
        self.assertEqual(fcf_of(dict(fcf=55, ocf=1, capex=-1)), 55)
        self.assertIsNone(fcf_of(dict(ocf=100)))

    def test_anchors_and_status_quo(self):
        hist = [dict(period_end='2025-12-31', net_income=100, diluted_eps=1.0), dict(period_end='2024-12-31', net_income=80, diluted_shares=100)]
        cash = [dict(period_end='2025-12-31', ocf=150, capex=-40, sbc=20), dict(period_end='2024-12-31', fcf=70, sbc=10)]
        a, rows = fcf_anchors(cash, dict(period_end='2026-06-30', ocf=170, capex=-50, sbc=5), hist, 95, 'USD', 'X', 'now', 'src')
        self.assertEqual([x['id'] for x in a][:2], ['fcf:ttm', 'fcfsbc:ttm'])
        self.assertAlmostEqual(next(x for x in a if x['id'] == 'fcf:2025-12-31')['value'], 1.1)
        g, m = fcf_status_quo(rows, 20)
        self.assertAlmostEqual(g, 1.1 / .7 - 1); self.assertGreater(m, 0)

    def test_pfcf_math_on_the_table(self):
        d = company()
        t = d['period_table']['rows']['fcf_per_share']
        a = PfcfAssumptions(method='p_fcf', exit_fy='2028-12-31', required_return=.1, growth=.10, growth_spread=.03, share_change=-.02, exit_multiple=25, multiple_spread=.1)
        r = calculate(d, a)
        e1 = t['E1']['value']
        self.assertAlmostEqual(r['scenarios'][1]['fcf_per_share'], e1 * 1.10 / .98)          # one user year after the analyst years
        self.assertAlmostEqual(r['scenarios'][1]['future_price'], r['scenarios'][1]['fcf_per_share'] * 25)
        self.assertAlmostEqual(r['reverse']['required_exit_multiple'] * r['scenarios'][1]['fcf_per_share'], 44 * 1.1 ** r['years'])

    def test_pfcf_rejects_a_company_without_positive_cash_flow(self):
        d = company(ocf=(10e6, 10e6, 10e6, 10e6), capex=(-30e6,) * 4, ttm_cash=(10e6, -30e6, 0))
        a = PfcfAssumptions(method='p_fcf', exit_fy='2028-12-31', required_return=.1, growth=.1, growth_spread=.03, share_change=0, exit_multiple=25, multiple_spread=.1)
        with self.assertRaises(ValueError):
            calculate(d, a)


class Compare(unittest.TestCase):
    def test_rank_skip_and_not_averaged(self):
        cheap = company(ticker='A', price=30.0)
        dear = company(ticker='B', price=90.0)
        none = company(ticker='C', est=None, eps=(-1, -1, -1, -1), ttm_eps=-1, ocf=(-1e6,) * 4, capex=(-1e6,) * 4, ttm_cash=(-1e6, -1e6, 0),
                         ebitda=(-1e6,) * 4, ttm_ebitda=-1e6)
        r = compare([dear, none, cheap], 3, .1)
        names = [x['ticker'] for x in r['rows']]
        self.assertEqual(names[:2], ['A', 'B']); self.assertEqual(names[-1], 'C')
        self.assertEqual(r['rows'][0]['rank'], 1)
        c = r['rows'][-1]
        self.assertEqual(c['methods'], []); self.assertTrue(c['skipped'])
        a = r['rows'][0]
        self.assertEqual(a['conservative'], min(m['base'] for m in a['methods']))        # the lowest, never an average

    def test_each_company_exits_at_its_own_nearest_fiscal_year_end(self):
        dec = company(ticker='D')
        jun = company(ticker='J', last_fy='2026-06-30', next_fy='2027-06-30', mrq='2026-06-30')
        rows = {x['ticker']: x for x in compare([dec, jun], 3, .1)['rows']}
        self.assertEqual(rows['D']['exit_fy'], 'FY2029'); self.assertEqual(rows['J']['exit_fy'], 'FY2029')
        self.assertEqual(rows['D']['exit_date'], '2029-12-31'); self.assertEqual(rows['J']['exit_date'], '2029-06-30')
        self.assertNotAlmostEqual(rows['D']['years'], rows['J']['years'], places=1)
        for x in rows.values():
            self.assertLess(abs(x['years'] - 3), .6)

    def test_shift_lowers_return(self):
        a = compare([company(ticker='A'), company(ticker='A2')], 3, None, 0)['rows'][0]['conservative']
        b = compare([company(ticker='A'), company(ticker='A2')], 3, None, -.2)['rows'][0]['conservative']
        self.assertLess(b, a)

    def test_fade_lowers_return(self):
        flat = compare([company(ticker='A'), company(ticker='B')], 3, .1, 0, None)['rows'][0]['conservative']
        fade = compare([company(ticker='A'), company(ticker='B')], 3, .1, 0, .01)['rows'][0]['conservative']
        self.assertLess(fade, flat)

    def test_tiny_base_is_visible_but_not_ranked(self):
        x = company(ticker='X', ocf=(31e6, 31e6, 31e6, 31e6), capex=(-30e6,) * 4, ttm_cash=(30.01e6, -30e6, 0), est=(2.2, 2.5, 1100e6, 1210e6))
        r = compare([x, company(ticker='A')], 3, .1)
        row = next(m for m in r['rows'] if m['ticker'] == 'X')
        self.assertTrue(any(k['method'] == 'p_fcf' for k in row['skipped']))              # the reason stays visible
        self.assertTrue(row['review']); self.assertIsNone(row.get('rank'))
        self.assertEqual(r['rows'][0]['ticker'], 'A'); self.assertEqual(r['rows'][0]['rank'], 1)

    def test_rebound_growth_default_is_capped_and_says_so(self):
        y = company(ticker='Y', est=(2.2, 6.0, 1100e6, 1210e6))      # E1 EPS growth of 173% would have become the default growth
        q = y['defaults']['pe']
        self.assertEqual(q['growth'], 25.0); self.assertIn('rebound', q['growth_note'])
        self.assertTrue(compare([y, company(ticker='A')], 3, .1)['rows'])

    def test_share_mismatch_is_review(self):
        z = company(ticker='Z'); z['share_check'] = dict(differs=True)
        row = next(m for m in compare([z, company(ticker='A')], 3, .1)['rows'] if m['ticker'] == 'Z')
        self.assertTrue(any('P/FCF' in x for x in row['review']))

    def test_default_result_is_growth_when_the_multiple_is_held(self):
        d = company()
        a, _ = build(d, 'pe', 3, .1, 0, .05)
        r = calculate(d, a)
        base = r['scenarios'][1]
        self.assertGreater(base['price_cagr'], .03); self.assertLess(base['price_cagr'], .20)
        self.assertEqual(r['exit_fy'], 'FY2029'); self.assertEqual(r['reference']['label'], 'TTM')
        self.assertAlmostEqual((1 + base['earnings_effect']) * (1 + base['multiple_effect']), 1 + base['price_cagr'])


class Refs(unittest.TestCase):
    def test_growth_refs_come_from_the_table(self):
        d = company()
        refs = {r['id']: r['value'] for r in growth_refs(d)}
        self.assertAlmostEqual(refs['eps_e1'], 13.6, places=1); self.assertAlmostEqual(refs['eps_e0'], 10.0, places=1)
        self.assertAlmostEqual(refs['rev_e1'], 10.0, places=1); self.assertAlmostEqual(refs['rev_e0'], 10.0, places=1)
        self.assertAlmostEqual(refs['eps_last'], 11.1, places=1)
        self.assertEqual(d['growth_refs'], growth_refs(d))

    def test_pfcf_growth_default_is_revenue_growth(self):
        d = company()
        self.assertEqual(d['defaults']['p_fcf']['growth_source'], 'rev_e1'); self.assertEqual(d['defaults']['ev_ebitda']['growth_source'], 'rev_e1')
        self.assertEqual(d['defaults']['pe']['growth_source'], 'eps_e1')

    def test_quarter_end(self):
        self.assertEqual(consensus_quarter_end({'mostRecentQuarter': '2026-05-31'}, '0q'), '2026-08-31')
        self.assertEqual(consensus_quarter_end({'mostRecentQuarter': '2026-11-30'}, '+1q'), '2027-05-30')
        self.assertIsNone(consensus_quarter_end({}, '0q'))

    def test_method_fit(self):
        d = dict(industry='Semiconductors', sector='Technology', current_multiples=dict(trailing_eps=5, enterprise_to_ebitda=15),
                 fcf_anchors=[dict(id='fcf:ttm', value=3)], fcf_history=[], market_baseline=dict(net_debt=1))
        f = method_fit(d)
        self.assertEqual(f['recommended'], 'p_fcf'); self.assertEqual(f['pe']['level'], 'caution')
        bank = dict(industry='Banks', sector='Financial Services', current_multiples=dict(trailing_eps=5), fcf_anchors=[], market_baseline={})
        self.assertEqual(method_fit(bank)['ev_ebitda']['level'], 'avoid'); self.assertEqual(method_fit(bank)['recommended'], 'pe')

    def test_industry_summary(self):
        peers = [dict(forward_pe=p, eps_growth=g, price_to_fcf=q) for p, g, q in ((20, .1, 25), (30, .15, 30), (25, .1, 28), (40, .2, 35))]
        s = industry_summary(peers, 'x')
        self.assertEqual(s['forward_pe'], 27.5); self.assertAlmostEqual(s['peg'], 2.0)
        self.assertIsNone(industry_summary(peers[:2], 'x'))


if __name__ == '__main__':
    unittest.main()
