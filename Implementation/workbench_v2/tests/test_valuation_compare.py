import unittest
from app.core.compare import compare
from app.core.valuation import PfcfAssumptions, calculate
from app.core.valuation_context import fcf_anchors, fcf_status_quo, fcf_of


def mk(t, pe, g, fcfps, mult, fg=None):
    return dict(ticker=t, name=t, retrieved_at='2026-10-11T00:00:00+00:00', quote=dict(value=100, currency='USD'),
                anchors=[dict(id='consensus:0y', value=5, currency='USD', period_end='2027-03-31', category='market_consensus')],
                fcf_anchors=[dict(id='fcf:ttm', value=fcfps, currency='USD', period_end='2026-06-30', category='ttm_reported')],
                revenue_anchors=[], estimates=[], historical=[], current_multiples=dict(forward_pe=pe, price_to_fcf=mult),
                defaults=dict(pe=dict(growth=g, exit_pe=pe, growth_spread=3, pe_spread=10),
                              p_fcf=dict(growth=fg, exit_multiple=mult, share_change=0, growth_spread=3, multiple_spread=10), ev_ebitda={}))


class Fcf(unittest.TestCase):
    def test_fcf_of(self):
        self.assertEqual(fcf_of(dict(ocf=100, capex=-30)), 70)
        self.assertEqual(fcf_of(dict(fcf=55, ocf=1, capex=-1)), 55)
        self.assertIsNone(fcf_of(dict(ocf=100)))

    def test_anchors_and_status_quo(self):
        hist = [dict(period_end='2025-12-31', net_income=100, diluted_eps=1.0), dict(period_end='2024-12-31', net_income=80, diluted_shares=100)]
        cash = [dict(period_end='2025-12-31', ocf=150, capex=-40, sbc=20), dict(period_end='2024-12-31', fcf=70, sbc=10)]
        a, rows = fcf_anchors(cash, dict(period_end='2026-06-30', ocf=170, capex=-50, sbc=5), hist, 95, 'USD', 'X', 'now', 'src')
        ids = [x['id'] for x in a]
        self.assertEqual(ids[:2], ['fcf:ttm', 'fcfsbc:ttm'])
        self.assertAlmostEqual(next(x for x in a if x['id'] == 'fcf:2025-12-31')['value'], 1.1)
        g, m = fcf_status_quo(rows, 20)
        self.assertAlmostEqual(g, 1.1 / .7 - 1); self.assertGreater(m, 0)

    def test_pfcf_math(self):
        d = mk('A', 20, 10, 4, 25)
        a = PfcfAssumptions(method='p_fcf', anchor_id='fcf:ttm', years=3, required_return=.1, growth=.10, growth_spread=.03,
                            share_change=-.02, exit_multiple=25, multiple_spread=.1, acknowledge_basis=True)
        r = calculate(d, a)
        gy = r['growth_years']
        self.assertAlmostEqual(r['scenarios'][1]['fcf_per_share'], 4 * (1.10 / .98) ** gy)
        self.assertAlmostEqual(r['scenarios'][1]['future_price'], r['scenarios'][1]['fcf_per_share'] * 25)
        self.assertAlmostEqual(r['reverse']['required_exit_multiple'] * r['scenarios'][1]['fcf_per_share'], 100 * 1.1 ** 3)

    def test_pfcf_rejects_negative_anchor(self):
        d = mk('A', 20, 10, -1, 25)
        a = PfcfAssumptions(method='p_fcf', anchor_id='fcf:ttm', years=3, required_return=.1, growth=.1, growth_spread=.03, share_change=0,
                            exit_multiple=25, multiple_spread=.1, acknowledge_basis=True)
        with self.assertRaises(ValueError): calculate(d, a)


class Compare(unittest.TestCase):
    def test_rank_and_skip(self):
        r = compare([mk('A', 20, 10, 4, 25), mk('B', 30, 18, 2, 50), mk('C', 15, None, 5, 20)], 3, .1)
        names = [x['ticker'] for x in r['rows']]
        self.assertEqual(names, ['B', 'A', 'C'])
        self.assertEqual(r['rows'][0]['rank'], 1)
        c = r['rows'][-1]
        self.assertEqual(c['methods'], []); self.assertTrue(c['skipped'])

    def test_not_averaged_and_disagree_flag(self):
        r = compare([mk('B', 30, 18, 2, 50, fg=2), mk('A', 20, 10, 4, 25)], 3)
        b = next(x for x in r['rows'] if x['ticker'] == 'B')
        self.assertEqual(b['conservative'], min(m['base'] for m in b['methods']))
        self.assertTrue(b['disagree'])

    def test_shift_lowers_return(self):
        a = compare([mk('A', 20, 10, 4, 25), mk('A2', 20, 10, 4, 25)], 3, None, 0)['rows'][0]['conservative']
        b = compare([mk('A', 20, 10, 4, 25), mk('A2', 20, 10, 4, 25)], 3, None, -.2)['rows'][0]['conservative']
        self.assertLess(b, a)


if __name__ == '__main__':
    unittest.main()


class Fade(unittest.TestCase):
    def test_growth_factor(self):
        from app.core.valuation import growth_factor
        self.assertAlmostEqual(growth_factor(.2, None, 3), 1.2 ** 3)
        self.assertAlmostEqual(growth_factor(.2, .05, 3), 1.2 * 1.125 * 1.05)

    def test_fade_lowers_price(self):
        from app.core.valuation import Assumptions
        d = mk('A', 20, 10, 4, 25)
        kw = dict(anchor_id='consensus:0y', years=3, required_return=.1, growth=.2, exit_pe=20, growth_spread=.03, pe_spread=.1, acknowledge_basis=True)
        flat = calculate(d, Assumptions(**kw)); fade = calculate(d, Assumptions(**kw, fade_to=.05))
        self.assertLess(fade['scenarios'][1]['future_price'], flat['scenarios'][1]['future_price'])

    def test_compare_fade(self):
        a = compare([mk('A', 20, 10, 4, 25), mk('B', 30, 18, 2, 50)], 3, .1, 0, None)
        b = compare([mk('A', 20, 10, 4, 25), mk('B', 30, 18, 2, 50)], 3, .1, 0, .03)
        self.assertLess(b['rows'][0]['conservative'], a['rows'][0]['conservative'])

    def test_industry_summary(self):
        from app.core.valuation_context import industry_summary
        peers = [dict(forward_pe=p, eps_growth=g, price_to_fcf=q) for p, g, q in ((20, .1, 25), (30, .15, 30), (25, .1, 28), (40, .2, 35))]
        s = industry_summary(peers, 'x')
        self.assertEqual(s['forward_pe'], 27.5); self.assertAlmostEqual(s['peg'], 2.0)
        self.assertIsNone(industry_summary(peers[:2], 'x'))


class Feedback(unittest.TestCase):
    def test_quarter_end(self):
        from app.core.valuation_context import consensus_quarter_end
        self.assertEqual(consensus_quarter_end({'mostRecentQuarter': '2026-05-31'}, '0q'), '2026-08-31')
        self.assertEqual(consensus_quarter_end({'mostRecentQuarter': '2026-11-30'}, '+1q'), '2027-05-30')
        self.assertIsNone(consensus_quarter_end({}, '0q'))

    def test_growth_refs_and_status_quo(self):
        from app.core.valuation_context import growth_refs, status_quo
        d = dict(estimates=[dict(metric='eps', period='0y', avg=2), dict(metric='eps', period='+1y', avg=3),
                            dict(metric='revenue', period='0y', avg=100), dict(metric='revenue', period='+1y', avg=110)],
                 historical=[], current_multiples=dict(trailing_pe=30, forward_pe=20))
        refs = {r['id']: r['value'] for r in growth_refs(d)}
        self.assertEqual(refs['eps_cons'], 50.0); self.assertEqual(refs['rev_cons'], 10.0)
        q = status_quo(d)
        self.assertEqual(q['pe']['exit_pe'], 30)            # trailing basis, not forward
        self.assertEqual(q['pe']['fade_to'], 5.0); self.assertEqual(q['ev_ebitda']['growth'], 10.0)

    def test_method_fit(self):
        from app.core.multiples import method_fit
        d = dict(industry='Semiconductors', sector='Technology', current_multiples=dict(trailing_eps=5, enterprise_to_ebitda=15),
                 fcf_anchors=[dict(id='fcf:ttm', value=3)], fcf_history=[], market_baseline=dict(net_debt=1))
        f = method_fit(d)
        self.assertEqual(f['recommended'], 'p_fcf'); self.assertEqual(f['pe']['level'], 'caution')
        bank = dict(industry='Banks', sector='Financial Services', current_multiples=dict(trailing_eps=5), fcf_anchors=[], market_baseline={})
        self.assertEqual(method_fit(bank)['ev_ebitda']['level'], 'avoid'); self.assertEqual(method_fit(bank)['recommended'], 'pe')

    def test_path_matches_exit(self):
        from app.core.valuation import Assumptions
        d = mk('A', 20, 10, 4, 25)
        a = Assumptions(anchor_id='consensus:0y', years=3, required_return=.1, growth=.15, fade_to=.05, exit_pe=22, growth_spread=.03, pe_spread=.1, acknowledge_basis=True)
        r = calculate(d, a)
        self.assertAlmostEqual(r['path'][-1]['price'], r['scenarios'][1]['future_price'], places=6)
        self.assertEqual(len(r['path']), 3)

    def test_tiny_base_is_visible_but_not_ranked(self):
        d = mk('X', 20, 10, 0.01, 25)           # price / FCF per share = 10000: no meaningful projection
        r = compare([d, mk('A', 20, 10, 4, 25)], 3, .1)
        row = next(x for x in r['rows'] if x['ticker'] == 'X')
        self.assertTrue(row['review']); self.assertIsNone(row.get('rank'))
        self.assertTrue(any(k['method'] == 'p_fcf' for k in row['skipped']))      # the reason stays visible
        self.assertEqual(r['rows'][0]['ticker'], 'A'); self.assertEqual(r['rows'][0]['rank'], 1)

    def test_implausible_default_is_flagged_not_dropped(self):
        d = mk('Y', 20, 100, 4, 25)             # +100%/yr default growth
        r = compare([d, mk('A', 20, 10, 4, 25)], 3, .1)
        row = next(x for x in r['rows'] if x['ticker'] == 'Y')
        self.assertTrue(any(m['implausible'] for m in row['methods'])); self.assertTrue(row['review'])

    def test_share_mismatch_is_review(self):
        d = mk('Z', 20, 10, 4, 25); d['share_check'] = dict(differs=True)
        row = compare([d, mk('A', 20, 10, 4, 25)], 3, .1)['rows'][-1]
        self.assertEqual(row['ticker'], 'Z'); self.assertTrue(any('P/FCF' in x for x in row['review']))
