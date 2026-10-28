import unittest
from app.core.situation import situation, states_of, thresh, archetype_of
from app.core.valuation import calculate, Assumptions, PfcfAssumptions
from tests.fixtures_val import company


def a_pe(**k):
    d = dict(method='pe', growth=0.08, growth_spread=0.03, exit_pe=18, pe_spread=0.15, required_return=0.10, fade_to=None, exit_fy=None)
    d.update(k)
    return d


def run(data, **k):
    from app.core.period_table import table_of
    t = table_of(data)
    opt = next(o for o in t['exit_options'] if o['years'] >= 2.5)
    a = Assumptions(**{**dict(growth=0.08, growth_spread=0.03, exit_pe=18, pe_spread=0.15, required_return=0.10, exit_fy=opt['period_end']), **k})
    res = calculate(data, a)
    return a, res


def ids(sit):
    return {s['id']: s for s in sit['states']}


class Situation(unittest.TestCase):
    def test_stable_company_has_observed_tag_with_years(self):
        d = company(eps=(1.8, 1.9, 2.0, 2.0))
        a, r = run(d)
        s = situation(d, a, r)
        self.assertIn('stable', ids(s))
        self.assertIn('4 reported years', ids(s)['stable']['evidence'])
        self.assertEqual(ids(s)['stable']['status'], 'observed')
        self.assertIsNone(s['warning'])
        self.assertEqual([c['id'] for c in s['confidence']], ['data', 'earnings', 'forecast', 'method'])

    def test_negative_eps_is_persistent_loss_and_pe_unsupported(self):
        d = company(eps=(-1.0, -0.5, -0.2, 0.1), net_income=(-50e6, -25e6, -10e6, 5e6), ttm_eps=-0.3, est=(0.4, 0.9, 1100e6, 1210e6))
        a, r = run(d, exit_pe=15) if False else (None, None)
        sit = situation(d, Assumptions(growth=0.08, growth_spread=0.03, exit_pe=15, pe_spread=0.15, required_return=0.1, exit_fy=d['period_table']['exit_options'][2]['period_end']),
                        dict(required_exit_price=None, user_years=0))
        self.assertIn('persistent_loss', ids(sit))
        self.assertEqual(sit['suitability']['pe']['level'], 'Unsupported')
        self.assertEqual(sit['warning']['level'], 'Unsupported')
        self.assertIsNone(sit['implied'])

    def test_no_analysts_is_insufficient_forecast_evidence(self):
        d = company(est=None)
        a, r = run(d)
        s = situation(d, a, r)
        f = next(c for c in s['confidence'] if c['id'] == 'forecast')
        self.assertEqual(f['level'], 'Insufficient Evidence')

    def test_few_analysts_is_insufficient(self):
        d = company(n_est=2)
        a, r = run(d)
        f = next(c for c in situation(d, a, r)['confidence'] if c['id'] == 'forecast')
        self.assertEqual(f['level'], 'Insufficient Evidence')

    def test_missing_data_does_not_raise(self):
        d = company(cash=False)
        d['market_baseline'] = {}
        a, r = run(d)
        s = situation(d, a, r)
        self.assertEqual(next(c for c in s['confidence'] if c['id'] == 'data')['level'], 'Limited')
        self.assertFalse([c for c in s['characteristics'] if c['id'] in ('leverage', 'capex')])

    def test_high_dividend_with_weak_coverage_warns(self):
        d = company(price=20.0, ttm_eps=0.8)
        d['current_multiples']['dividend_yield'] = 0.08       # 1.60 a share against 0.80 EPS
        a, r = run(d)
        dv = next(c for c in situation(d, a, r)['characteristics'] if c['id'] == 'dividend')
        self.assertTrue(dv['warn'])
        self.assertIn('Coverage warning', dv['text'])
        self.assertIn('0.5x', dv['text'])

    def test_covered_dividend_has_no_warning(self):
        d = company(price=40.0, ttm_eps=2.1)
        d['current_multiples']['dividend_yield'] = 0.025
        a, r = run(d)
        dv = next(c for c in situation(d, a, r)['characteristics'] if c['id'] == 'dividend')
        self.assertFalse(dv['warn'])

    def test_leverage_uses_net_debt_over_ebitda_and_says_interest_not_evaluated(self):
        d = company(debt=1000e6, cash_bal=40e6)
        a, r = run(d)
        lv = next(c for c in situation(d, a, r)['characteristics'] if c['id'] == 'leverage')
        self.assertIn('3.6x', lv['text'])
        self.assertIn('Interest coverage is not evaluated', lv['text'])

    def test_industry_override_of_leverage(self):
        self.assertEqual(thresh(dict(industry='Utilities'))['leverage'], 5.0)
        self.assertEqual(thresh(dict(industry='Machinery'))['leverage'], 3.0)

    def test_high_capex_share(self):
        d = company(capex=(-100e6,) * 4, ocf=(110e6, 120e6, 135e6, 150e6))
        a, r = run(d)
        self.assertIn('capex', {c['id'] for c in situation(d, a, r)['characteristics']})

    def test_dilution_and_buyback(self):
        d = company()
        sh = d['period_table']['rows']['shares']
        for k, g in (('A-2', .05), ('A-1', .05), ('A0', .05)):
            sh[k]['growth'] = g
        a, r = run(d)
        self.assertIn('dilution', {c['id'] for c in situation(d, a, r)['characteristics']})
        for k in ('A-2', 'A-1', 'A0'):
            sh[k]['growth'] = -.05
        self.assertIn('buyback', {c['id'] for c in situation(d, a, r)['characteristics']})

    def test_financial_company_marks_ev_ebitda_and_pfcf_unsupported(self):
        d = company(sector='Financial Services', industry='Banks - Regional')
        a, r = run(d)
        s = situation(d, a, r)
        self.assertEqual(s['archetype']['key'], 'financial')
        self.assertEqual(s['suitability']['ev_ebitda']['level'], 'Unsupported')
        self.assertEqual(s['suitability']['pe']['level'], 'Supported')

    def test_holding_company_reit_is_limited_not_unsupported(self):
        d = company(sector='Real Estate', industry='REIT - Diversified')
        a, r = run(d)
        s = situation(d, a, r)
        self.assertEqual(s['archetype']['key'], 'reit')
        self.assertEqual(s['warning']['level'], 'Limited')
        self.assertIn('FFO', s['warning']['text'])

    def test_candidate_tags_wait_for_user_and_dismissal_is_kept(self):
        d = company(ttm_eps=0.5, pe_t=88.0, pe_f=17.6, est=(2.2, 2.5, 1100e6, 1210e6))
        self.assertEqual(d['earnings_dislocation']['kind'], 'recovery')
        a, r = run(d)
        s = situation(d, a, r)
        self.assertEqual(ids(s)['recovery']['status'], 'candidate')
        self.assertIsNone(ids(s)['recovery']['user'])
        s2 = situation(d, a, r, dict(states={'recovery': 'dismissed'}, note='not a recovery'))
        self.assertEqual(ids(s2)['recovery']['user'], 'dismissed')
        self.assertEqual(s2['review']['note'], 'not a recovery')

    def test_multiple_tags_at_once(self):
        d = company(eps=(-1.0, 2.0, -0.5, 3.0), net_income=(-50e6, 100e6, -25e6, 150e6), ttm_eps=0.5)
        a, r = run(d, exit_pe=15)
        s = situation(d, a, r)
        self.assertGreaterEqual(len(s['states']), 2)

    def test_archetype_override(self):
        d = company()
        a, r = run(d)
        s = situation(d, a, r, dict(archetype='cyclical'))
        self.assertEqual(s['archetype']['key'], 'cyclical')
        self.assertTrue(s['archetype']['overridden'])
        self.assertEqual(s['suitability']['pe']['level'], 'Limited')

    def test_situation_does_not_change_the_result(self):
        d = company()
        a, r = run(d)
        before = repr(r['scenarios'])
        situation(d, a, r, dict(archetype='financial'))
        self.assertEqual(before, repr(r['scenarios']))


class ImpliedMargin(unittest.TestCase):
    def test_pe_implied_net_margin_tiers(self):
        d = company()
        a, r = run(d, exit_pe=5)       # a low multiple needs a lot of EPS
        imp = situation(d, a, r)['implied']
        self.assertEqual(imp['name'], 'net margin')
        self.assertGreater(imp['required'], imp['best'])
        self.assertIn('x the best', imp['text'])

    def test_easy_requirement_is_within_range(self):
        d = company()
        a, r = run(d, exit_pe=40, required_return=0.0)
        imp = situation(d, a, r)['implied']
        self.assertEqual(imp['tier'], 'within the range the company has reported')
        self.assertFalse(imp['flag'])

    def test_pfcf_uses_fcf_margin(self):
        d = company()
        from app.core.period_table import table_of
        opt = next(o for o in table_of(d)['exit_options'] if o['years'] >= 2.5)
        a = PfcfAssumptions(method='p_fcf', share_change=0.0, growth=0.08, growth_spread=0.03, exit_multiple=15, multiple_spread=0.15, required_return=0.1, exit_fy=opt['period_end'])
        r = calculate(d, a)
        self.assertEqual(situation(d, a, r)['implied']['name'], 'free-cash-flow margin')


if __name__ == '__main__':
    unittest.main()


class Wording(unittest.TestCase):
    def test_missing_analyst_count_is_limited_not_zero(self):
        d = company()
        for c in d['period_table']['rows']['eps'].values():
            if c.get('kind') == 'analyst':
                c['n'] = None
        a, r = run(d)
        f = next(c for c in situation(d, a, r)['confidence'] if c['id'] == 'forecast')
        self.assertEqual(f['level'], 'Limited')
        self.assertNotIn('0 analysts', f['why'])

    def test_warning_uses_short_archetype_name(self):
        d = company(sector='Real Estate', industry='REIT - Diversified')
        a, r = run(d)
        self.assertNotIn('((', situation(d, a, r)['warning']['text'])
