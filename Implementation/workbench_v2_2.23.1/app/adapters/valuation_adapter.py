"""Reuse OpenBB's boundary; supplement with direct Yahoo earnings estimates.
No price targets are used as earnings estimates. No fabricated fallback values.
"""
from datetime import datetime, timezone
import math
from .openbb_adapter import OpenBBAdapter
from .. import config

def clean(v):
    if isinstance(v, dict): return {str(k): clean(x) for k,x in v.items()}
    if isinstance(v, (list,tuple)): return [clean(x) for x in v]
    if v is None or isinstance(v, (str,bool,int)): return v
    if hasattr(v, "isoformat"): return v.isoformat()
    try:
        f=float(v)
        return f if math.isfinite(f) else None
    except (TypeError,ValueError): return str(v)

def auto_peers(ticker, info, n=8):
    """Top companies of the stock's Yahoo industry, as a starting peer set. Returns (symbols, label)."""
    key=info.get("industryKey")
    if not key: return [],"Yahoo gave no industry key for this ticker"
    try:
        import yfinance as yf
        frame=yf.Industry(key).top_companies
        syms=[str(x).upper() for x in frame.index if str(x).upper()!=ticker][:n]
        return syms,f'Yahoo top companies in "{info.get("industry")}"'
    except Exception as e: return [],f"Industry peers unavailable: {str(e)[:150]}"

def fetch(ticker, peer_symbols=(), industry=False):
    now=datetime.now(timezone.utc).isoformat()
    d=dict(ticker=ticker, retrieved_at=now, quote={}, anchors=[], estimates=[], historical=[], warnings=[], raw={})
    adapter=OpenBBAdapter(config.OPENBB_PROVIDER)
    def obb_rows(section, fn):
        try:
            response=adapter._call(section, fn)
            rows=clean(adapter._results(response))
            for warning in (adapter._meta(response).get("warnings") or []):
                d["warnings"].append(f"{section}: {warning}")
            if not rows: d["warnings"].append(f"{section}: provider returned no rows")
            d["raw"][section]=dict(results=rows,meta=clean(adapter._meta(response)))
            return rows
        except Exception as e:
            d["warnings"].append(f"{section}: {str(e)[:240]}")
            return []
    def fact(value, category, source, currency=None, period_end=None, basis=None, published_at=None, **extra):
        return dict(value=value,category=category,source=source,currency=currency,period_end=period_end,
                    basis=basis,published_at=published_at,retrieved_at=now,unit="currency_per_share",
                    source_url=f"https://finance.yahoo.com/quote/{ticker}/",**extra)
    quotes=obb_rows("quote",lambda obb: obb.equity.price.quote(symbol=ticker,provider=adapter.provider))
    incomes=obb_rows("income",lambda obb: obb.equity.fundamental.income(symbol=ticker,provider=adapter.provider,period="annual",limit=5))
    info={}; stock=None
    try:
        import yfinance as yf
        stock=yf.Ticker(ticker)
        info=stock.get_info() or {}
        d["raw"]["yfinance_info"]={k:clean(info.get(k)) for k in ("currency","financialCurrency","regularMarketPrice","regularMarketTime","longName","trailingPE","forwardPE","trailingEps","forwardEps","enterpriseToEbitda","ebitda","totalDebt","totalCash","sharesOutstanding","enterpriseValue","targetMeanPrice","targetMedianPrice","targetLowPrice","targetHighPrice","numberOfAnalystOpinions","sector","industry","nextFiscalYearEnd","lastFiscalYearEnd","mostRecentQuarter","industryKey","totalRevenue","freeCashflow","operatingCashflow","marketCap")}
    except Exception as e: d["warnings"].append(f"Yahoo quote metadata: {str(e)[:240]}")
    q=quotes[0] if quotes else {}
    price=q.get("last_price")
    currency=q.get("currency") or info.get("currency")
    source=f"OpenBB/{adapter.provider}: equity.price.quote"
    stamp=q.get("last_timestamp") or q.get("timestamp")
    if price is None:
        price=info.get("regularMarketPrice");stamp=info.get("regularMarketTime")
        source="yfinance/Yahoo: regularMarketPrice"
    if stamp is None and price == info.get("regularMarketPrice"):
        stamp=info.get("regularMarketTime")
        d["quote_time_source"]="yfinance/Yahoo: regularMarketTime (matching regularMarketPrice)"
    if isinstance(stamp,(float,int)):
        stamp=datetime.fromtimestamp(stamp,timezone.utc).isoformat()
    d["quote"]=fact(price,"observed_market",source,currency,observed_at=stamp)
    d["name"]=info.get("longName") or ticker
    if not stamp: d["warnings"].append("Quote observation time unavailable; retrieval time is not quote time.")
    if not incomes and stock is not None:
        try:
            frame=stock.get_income_stmt(freq="yearly")
            for col in frame.columns:
                row=frame[col]
                incomes.append(dict(period_ending=str(col)[:10],diluted_eps=clean(row.get("DilutedEPS")),
                                    diluted_shares=clean(row.get("DilutedAverageShares")),revenue=clean(row.get("TotalRevenue")),net_income=clean(row.get("NetIncome")),ebitda=clean(row.get("EBITDA")),
                                    currency=info.get("financialCurrency"),_direct=True))
            d["raw"]["yfinance_income"]=clean(incomes)
        except Exception as e: d["warnings"].append(f"Yahoo income: {str(e)[:240]}")
    # OpenBB provider field names differ from the legacy adapter's expected names.
    for row in incomes:
        if row.get("diluted_eps") is None: row["diluted_eps"]=row.get("diluted_earnings_per_share")
        if row.get("revenue") is None: row["revenue"]=row.get("total_revenue")
        if row.get("diluted_shares") is None: row["diluted_shares"]=row.get("weighted_average_diluted_shares_outstanding")
    for row in sorted(incomes,key=lambda r:str(r.get("period_ending") or ""),reverse=True):
        end=str(row.get("period_ending") or "")[:10]
        try: datetime.fromisoformat(end)
        except ValueError: continue
        src="yfinance/Yahoo: income_stmt" if row.get("_direct") else f"OpenBB/{adapter.provider}: equity.fundamental.income"
        cur=row.get("currency") or row.get("reported_currency") or info.get("financialCurrency")
        record=dict(period_end=end,source=src,currency=cur,retrieved_at=now,published_at=None,
                    unit="full_currency_units; EPS currency_per_share",revenue=row.get("revenue"),net_income=row.get("net_income"),diluted_shares=row.get("diluted_shares"),diluted_eps=row.get("diluted_eps"),ebitda=row.get("ebitda"),
                    ebitda_margin=row["ebitda"]/row["revenue"] if row.get("ebitda") is not None and row.get("revenue") and row["revenue"]>0 else None)
        d["historical"].append(record)
        if row.get("diluted_eps") is not None:
            d["anchors"].append(fact(row["diluted_eps"],"historical_reported",src,cur,end,
                                    "Annual reported diluted EPS (provider field; check issuer filing)",id=f"annual:{end}"))
    d["cashflow"]=[];d["cashflow_ttm"]=None
    if stock is not None:
        def cf_row(col,row):
            return dict(period_end=str(col)[:10],ocf=clean(row.get("OperatingCashFlow")),capex=clean(row.get("CapitalExpenditure")),
                        fcf=clean(row.get("FreeCashFlow")),sbc=clean(row.get("StockBasedCompensation")))
        try:
            frame=stock.get_cashflow(freq="yearly")
            d["cashflow"]=[cf_row(c,frame[c]) for c in frame.columns]
        except Exception as e: d["warnings"].append(f"Yahoo cash flow (annual): {str(e)[:200]}")
        try:
            frame=stock.get_cashflow(freq="trailing")
            if frame is not None and len(frame.columns): d["cashflow_ttm"]=cf_row(frame.columns[0],frame[frame.columns[0]])
        except Exception as e: d["warnings"].append(f"Yahoo cash flow (trailing): {str(e)[:200]}")
        d["raw"]["yfinance_cashflow"]=dict(annual=d["cashflow"],ttm=d["cashflow_ttm"])
    if stock is not None:
        for method in ("get_earnings_estimate","get_revenue_estimate"):
            try:
                frame=getattr(stock,method)()
                records=[] if frame is None else [dict(period=str(idx),**clean(row.to_dict())) for idx,row in frame.iterrows()]
                d["raw"][method]=records
                for row in records:
                    d["estimates"].append(dict(metric="eps" if method=="get_earnings_estimate" else "revenue",
                        category="market_consensus",source=f"yfinance/Yahoo: {method}",retrieved_at=now,
                        published_at=None,period_end=None,unit="currency_per_share" if method=="get_earnings_estimate" else "full_currency_units",currency=info.get("financialCurrency"),
                        basis="Provider consensus; GAAP/adjusted basis and exact period end unverified") | row)
            except Exception as e: d["warnings"].append(f"{method}: {str(e)[:240]}")
    d["warnings"].append("Reported annual EPS may include one-off items and is not normalized recurring earnings. Period ends are provider labels; publication dates are unknown.")
    d["warnings"].append("TTM and consensus EPS are offered as anchors, labelled by kind. Consensus period ends are derived from the provider fiscal-year-end date; GAAP/adjusted basis is unverified.")
    if not d["anchors"] and not info.get("trailingEps"): d["warnings"].append("No dated reported EPS available. P/E calculation is unavailable.")
    if stamp:
        try:
            observed=datetime.fromisoformat(str(stamp).replace("Z","+00:00"))
            if observed.tzinfo is None: observed=observed.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc)-observed).total_seconds()>4*86400:
                d["warnings"].append("Quote is more than four calendar days old; results use this observed price, not a live price.")
        except ValueError: d["warnings"].append("Quote timestamp format could not be verified.")
    if d["anchors"] and (d["anchors"][0].get("value") or 0)<=0:
        d["warnings"].append("Latest annual EPS is non-positive. P/E is unavailable for that period; selecting an older positive period does not resolve current losses.")
    d["methods"]=dict(pe="available" if any((a.get("value") or 0)>0 for a in d["anchors"]) else "unavailable",
        ev_ebitda="Not enabled: target net debt / other claims are not modelled.",
        p_fcf="available when free cash flow and share counts are reported")
    from .valuation_references import enrich
    if industry and not peer_symbols:
        peer_symbols,d["peer_source"]=auto_peers(ticker,info)
        if not peer_symbols: d["warnings"].append(d["peer_source"])
    elif peer_symbols: d["peer_source"]="Peers you chose"
    return enrich(clean(d),stock,info,peer_symbols)


