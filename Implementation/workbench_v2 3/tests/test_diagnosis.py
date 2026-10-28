"""2.29.1: the fixes found on MSFT, DEO, CNOOC and INTC, and the read-this-first block. Offline fixtures only."""
import unittest

from app.core.diagnosis import diagnose
from app.core.valuation import Assumptions, PfcfAssumptions, calculate
from app.core.valuation_defaults import build_defaults, GROWTH_CAP
from app.core.multiples import method_fit
from app.core.period_table import series
from tests.fixtures_val import company
from tests.test_valuation_turnaround import raw


def pe(**kw):
    base = dict(exit_fy='2029-12-31', required_return=.1, growth=.10, fade_to=.06, exit_pe=20, growth_spread=.05, pe_spread=.2)
    return Assumptions(**{**base, **kw})


def cnooc():
    """Cash margin has risen since the last reported year; revenue is expected higher still."""
    return company('CNO', price=23.12, eps=(3.5, 3.1, 3.0, 3.0), est=(3.97, 3.61, 566e9, 527e9), revenue=(495e9, 494e9, 468e9, 468e9), ebitda=(300e9, 290e9, 300e9, 302e9),
                   net_income=(150e9,) * 4, shares=47.5e9, ttm_eps=3.26, ttm_rev=509e9, ttm_ebitda=313e9, ocf=(150e9, 150e9, 170e9, 175e9), capex=(-60e9,) * 4,
                   ttm_cash=(220e9, -69e9, 0), sector='Energy', industry='Oil & Gas E&P', sbc=(0,) * 4)


def intc():
    return company('INT', price=86.96, eps=(1.94, .4, -4.38, -.06), est=(1.53, 2.11, 63e9, 72.7e9), revenue=(63e9, 54e9, 53e9, 52.85e9), ebitda=(21e9, 11e9, 1.2e9, 14e9),
                   net_income=(8e9, 1.7e9, -19e9, -.3e9), shares=4.5e9, ttm_eps=-2.12, ttm_rev=57e9, ttm_ebitda=16.8e9, ocf=(15e9, 11e9, 8e9, 8e9),
                   capex=(-25e9, -25e9, -24e9, -13e9), ttm_cash=(10e9, -7e9, 3e9), sector='Technology', industry='Semiconductors')


class DerivedCashFlow(unittest.TestCase):
    def test_uses_the_newer_margin_when_trailing_is_positive(self):
        d = cnooc(); t = d['period_table']
        self.assertEqual(t['fcf_base']['which'], 'TTM')
        ttm = t['rows']['fcf_per_share']['TTM']['value']
        e0 = t['rows']['fcf_per_share']['E0']
        self.assertAlmostEqual(e0['value'], ttm * 566e9 / 509e9, places=6)
        self.assertEqual(e0['kind'], 'derived')
        self.assertGreater(e0['value'], ttm)             # higher revenue at the same trailing margin cannot be lower than trailing

    def test_falls_back_to_the_reported_year_when_trailing_is_not_positive(self):
        d = company(ttm_cash=(10e6, -30e6, 0)); t = d['period_table']
        self.assertEqual(t['fcf_base']['which'], 'A0')


class Defaults(unittest.TestCase):
    def test_multiple_far_above_the_reference_band_is_pulled_back_with_a_reason(self):
        d = intc(); q = d['defaults']['pe']
        self.assertLessEqual(q['exit_pe'], 30.0)
        self.assertIn('top of the reference', q['multiple_note'])
        self.assertIn('stays in the reference table', q['multiple_note'])

    def test_rebound_growth_is_capped_for_the_first_user_year(self):
        d = company(eps=(1, 1, 1, 1.1), est=(1.5, 2.1, 1100e6, 1210e6)); q = build_defaults(d)['pe']
        self.assertEqual(q['growth'], GROWTH_CAP)
        self.assertIn('rebound', q['growth_note'])

    def test_an_ordinary_company_is_not_changed(self):
        d = company(); q = d['defaults']['pe']
        self.assertIsNone(q['growth_note']); self.assertIsNone(q['multiple_note'])


class FitUsesAvailability(unittest.TestCase):
    def test_pfcf_is_not_offered_when_there_is_no_positive_cash_flow(self):
        d = intc()
        with self.assertRaises(ValueError): series(d['period_table'], 'p_fcf')
        f = method_fit(d)
        self.assertEqual(f['p_fcf']['level'], 'avoid')
        self.assertNotEqual(f.get('recommended'), 'p_fcf')


class RecoverySplit(unittest.TestCase):
    def test_return_split_starts_from_the_analyst_year_for_a_rebound(self):
        d = raw(); a = Assumptions(exit_fy='2029-06-30', required_return=.1, growth=.069, fade_to=.05, exit_pe=12.07, growth_spread=.03, pe_spread=.1)
        r = calculate(d, a)
        self.assertIn('(analyst)', r['reference']['label'])
        self.assertIn('recovery', r['reference']['why'])
        base = r['scenarios'][1]
        self.assertLess(abs(base['earnings_effect']), .25)       # not the +115% jump counted as growth

    def test_an_ordinary_company_still_splits_from_ttm(self):
        r = calculate(company(), pe())
        self.assertEqual(r['reference']['label'], 'TTM')


class ReadThisFirst(unittest.TestCase):
    def setUp(self):
        self.d = company()

    def test_does_not_change_the_inputs_or_the_result(self):
        a = pe(); r = calculate(self.d, a); before = (a.model_dump(), [s['price_cagr'] for s in r['scenarios']])
        diagnose(self.d, a, r)
        self.assertEqual(before, (a.model_dump(), [s['price_cagr'] for s in r['scenarios']]))

    def test_lenses_change_only_the_multiple_and_cautious_growth(self):
        a = pe(exit_pe=30); r = calculate(self.d, a); g = diagnose(self.d, a, r)
        ids = [l['id'] for l in g['lenses']]
        self.assertEqual(ids[0], 'yours')
        self.assertIn('cautious', ids)
        yours = g['lenses'][0]; self.assertAlmostEqual(yours['base'], r['scenarios'][1]['price_cagr'])
        ref = next(l for l in g['lenses'] if l['id'] == 'reference'); self.assertLess(ref['exit_multiple'], 30); self.assertLess(ref['base'], yours['base'])
        self.assertTrue(any(f['id'] == 'multiple_driven' for f in g['flags']))

    def test_few_analysts_flag(self):
        d = company(n_est=2); a = pe(); g = diagnose(d, a, calculate(d, a))
        self.assertTrue(any(f['id'] == 'few_analysts' for f in g['flags']))

    def test_dividend_note_and_total_return(self):
        d = company(); d['current_multiples']['dividend_yield'] = .06; a = pe(); r = calculate(d, a); g = diagnose(d, a, r)
        self.assertTrue(any(f['id'] == 'dividend' for f in g['flags']))
        self.assertAlmostEqual(g['dividend']['approx_total'], r['scenarios'][1]['price_cagr'] + .06)

    def test_huge_share_change_is_flagged_with_a_suggestion(self):
        a = PfcfAssumptions(method='p_fcf', basis='fcf', exit_fy='2029-12-31', required_return=.1, growth=.10, growth_spread=.03, share_change=.23, exit_multiple=17, multiple_spread=.1)
        r = calculate(self.d, a); g = diagnose(self.d, a, r)
        self.assertTrue(any(f['id'] == 'share_change' for f in g['flags']))
        self.assertTrue(any(s['id'] == 'share_change' and s['set'] == {'sharechg': 0.0} for s in g['suggestions']))

    def test_growth_is_not_flagged_when_the_exit_year_is_an_analyst_year(self):
        a = pe(exit_fy='2027-12-31', growth=.6); r = calculate(self.d, a); self.assertEqual(r['user_years'], 0)
        self.assertFalse(any(f['id'] == 'high_growth' for f in diagnose(self.d, a, r)['flags']))

    def test_short_holding_gets_a_longer_suggestion(self):
        a = pe(exit_fy='2027-12-31'); r = calculate(self.d, a); g = diagnose(self.d, a, r)
        s = next(x for x in g['suggestions'] if x['id'] == 'longer'); self.assertIn('exit_fy', s['set'])

    def test_what_the_price_asks_for_matches_the_required_exit_price(self):
        a = pe(); r = calculate(self.d, a); g = diagnose(self.d, a, r)
        self.assertAlmostEqual(g['assumes']['price'], 44.0 * 1.1 ** r['years'], places=4)
        for row in g['assumes']['rows']: self.assertAlmostEqual(row['needed'] * row['multiple'], g['assumes']['price'], places=6)

    def test_pfcf_on_a_company_without_cash_flow_is_reported_as_not_suiting(self):
        d = intc(); a = pe(exit_fy='2029-12-31', exit_pe=25); g = diagnose(d, a, calculate(d, a))
        self.assertTrue(g['level'] in ('ok', 'care'))                       # P/E on the analyst years is computable
        a2 = PfcfAssumptions(method='p_fcf', basis='fcf', exit_fy='2029-12-31', required_return=.1, growth=.1, growth_spread=.03, share_change=0, exit_multiple=20, multiple_spread=.1)
        with self.assertRaises(ValueError): calculate(d, a2)


if __name__ == '__main__':
    unittest.main()
