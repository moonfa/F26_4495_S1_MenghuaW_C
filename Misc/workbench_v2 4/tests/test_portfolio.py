import unittest
from app import portfolio as p

TH = "方向 代码 名称 订单价格 订单数量 订单金额 交易状态 已成交@均价 下单时间 类型 期限 盘前竞价 时段 触发价 允许开仓 市场 币种 订单来源 成交数量 成交价格 成交金额 成交时间 市场 币种 对手经纪 备注 佣金 平台使用费 交收费 证监会规费 交易活动费 印花税 交易费 证监会征费 财汇局征费 综合审计跟踪监管费 清算费 合计费用".split()


def trade(side, code, status, mkt, cur, qty="", price="", when="", fee=""):
    r = [""] * len(TH)
    r[0], r[1], r[2], r[6], r[15], r[16] = side, code, "n", status, mkt, cur
    r[18], r[19], r[20], r[21], r[22], r[23], r[-1] = qty, price, "1", when, mkt, cur, fee
    return "\t".join(r)


class PortfolioTests(unittest.TestCase):
    def test_trades_only_filled(self):
        t = "\t".join(TH) + "\n" + "\n".join([
            trade("买入", "TSM", "全部成交", "美股", "USD", "12", "395.00", "2026/07/17 15:12:19 (美东)", "2.03"),
            trade("卖出", "TGT", "等待成交", "美股", "USD"),
            trade("买入", "TSLA", "已撤单", "美股", "USD"),
            trade("买入", "1432", "部成已撤", "港股", "HKD", "6,000", "0.35", "2025/10/03 10:00:00 (香港)", "34.38")])
        r = p.parse_trades(t)
        self.assertEqual([x["code"] for x in r], ["TSM", "1432"])
        self.assertEqual(r[1]["quantity"], 6000.0); self.assertEqual(r[1]["symbol"], "1432.HK"); self.assertEqual(r[1]["currency"], "HKD")
        self.assertTrue(r[0]["executed_at"].startswith("2026-07-17T19:12:19"))       # EDT -> UTC
        self.assertEqual(p.parse_trades(t)[0]["key"], r[0]["key"])                  # stable de-dup key

    def test_trade_report(self):
        t = "\t".join(TH) + "\n" + "\n".join([
            trade("买入", "TLT", "全部成交", "美股", "USD", "10", "90", "2026/07/17 15:12:19 (美东)"),
            trade("买入", "TLT", "全部成交", "美股", "USD", "10", "90", "bad-time"),
            trade("买入", "TSLA", "已撤单", "美股", "USD")])
        r, rep = p.parse_trades_report(t)
        self.assertEqual((rep["rows"], rep["unfilled"], rep["bad_row"], rep["symbols"]), (3, 1, 1, ["TLT"]))

    def test_share_class_symbols(self):
        self.assertEqual(p.norm_symbol("BRK.B"), "BRK-B"); self.assertEqual(p.norm_symbol("bf.b"), "BF-B")
        self.assertEqual(p.norm_symbol("0700.HK"), "0700.HK"); self.assertEqual(p.symbol_of("BRK.B", "USD"), "BRK-B")
        self.assertEqual(p.symbol_of("C09", "SGD"), "C09.SI")

    def test_holdings(self):
        t = "代码\t名称\t现价\t今日盈亏\t摊薄成本价\t持仓盈亏\t盈亏比例\t持有数量\t市值\t持仓占比\nABEV\tAmbev SA\t2.860\t60.00\t1.007\t2,778.98\t184.01%\t1,500\t4,290.00\t0.73%\nTLT\tiShares 20+ Year Treasury Bond ETF\t90\t0\t95\t-50\t-5%\t10\t900\t0.15%"
        r = p.parse_holdings(t)
        self.assertAlmostEqual(r[0]["weight"], 0.0073); self.assertEqual(r[0]["quantity"], 1500.0)
        self.assertEqual([x["kind"] for x in r], ["stock", "etf"])

    def test_csv_and_gbk(self):
        raw = "代码,名称,现价,摊薄成本价,持仓盈亏,盈亏比例,持有数量,市值,持仓占比\n9961,携程集团-S,500,300,1,10%,50,25000,1%".encode("gbk")
        r = p.parse_holdings(p.decode(raw))
        self.assertEqual(r[0]["symbol"], "9961.HK")

    def test_singapore_file(self):
        hdr = "名称\t代码\t市值\t持有数量\t可用数量\t现价\t摊薄成本价\t今日盈亏\t持仓盈亏\t盈亏比例\t持仓占比\t币种\t今日成交额\tDelta"
        row = "栢能集团有限公司\tPCT\t6,760.00\t2,000\t2,000\t3.380\t2.69\t0.00\t1,380.00\t25.65%\t0.90%\tSGD\t0.00\t2000.00"
        r = p.parse_holdings(hdr + "\n" + row)
        self.assertEqual((r[0]["symbol"], r[0]["currency"], r[0]["quantity"]), ("PCT.SI", "SGD", 2000.0))
        self.assertAlmostEqual(r[0]["weight"], 0.009); self.assertAlmostEqual(r[0]["pnl_pct"], 0.2565)

    def test_missing_column(self):
        with self.assertRaises(ValueError):
            p.parse_holdings("代码,名称\nA,b")


if __name__ == "__main__":
    unittest.main()
