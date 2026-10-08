from datetime import datetime, timezone
from typing import Any, Callable
import importlib


class OpenBBAdapterError(RuntimeError):
    """Provider-independent error raised by the OpenBB adapter."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        cause: Exception | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.cause = cause


class OpenBBAdapter:
    """
    Provider-neutral boundary around OpenBB.

    Compatibility rules:
    - keep get_equity_profile() for older callers
    - keep normalize_profile() for older callers
    - keep operation naming outside this class unchanged
    - normalized research snapshot is JSON-only and AI-neutral
    """

    SNAPSHOT_VERSION = "research-snapshot-v2.1"

    MAX_NEWS_ITEMS = 8
    MAX_NEWS_EXCERPT_CHARS = 500
    MAX_DESCRIPTION_CHARS = 2500
    MAX_CASH_HISTORY = 4

    def __init__(self, provider: str = "yfinance"):
        self.provider = provider

    def get_equity_profile(
        self,
        ticker: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        response = self._call(
            "equity.profile",
            lambda obb: obb.equity.profile(
                symbol=ticker,
                provider=self.provider,
            ),
        )

        results = self._results(response)

        if not results:
            raise OpenBBAdapterError(
                "invalid_ticker_or_no_data",
                f"OpenBB returned no equity profile data for {ticker}.",
            )

        return results, self._meta(response)

    def get_equity_research_snapshot(
        self,
        ticker: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:

        obb = self._load_openbb()

        warnings: list[str] = []
        raw_sections: dict[str, int] = {}
        raw: dict[str, Any] = {}

        def fetch(
            section: str,
            fn: Callable[[], Any],
            *,
            required: bool = False,
        ) -> list[dict[str, Any]]:

            try:
                response = fn()

                results = self._results(response)
                meta = self._meta(response)

                raw[section] = {
                    "results": results,
                    **meta,
                }

                raw_sections[section] = len(results)

                response_warnings = meta.get("warnings") or []
                if isinstance(response_warnings, list):
                    warnings.extend(str(item) for item in response_warnings)
                else:
                    warnings.append(str(response_warnings))

                if required and not results:
                    raise OpenBBAdapterError(
                        "invalid_ticker_or_no_data",
                        f"OpenBB returned no data for {ticker} from {section}.",
                    )

                return results

            except OpenBBAdapterError:
                raise

            except Exception as exc:

                message = f"{section}: {exc}"

                warnings.append(message)

                raw[section] = {
                    "results": [],
                    "error": str(exc)[:500],
                }

                raw_sections[section] = 0

                if required:
                    raise self._map_provider_error(
                        exc,
                        operation=section,
                    ) from exc

                return []

        profile = fetch(
            "profile",
            lambda: obb.equity.profile(
                symbol=ticker,
                provider=self.provider,
            ),
            required=True,
        )

        quote = fetch(
            "quote",
            lambda: obb.equity.price.quote(
                symbol=ticker,
                provider=self.provider,
            ),
        )

        metrics = fetch(
            "metrics",
            lambda: obb.equity.fundamental.metrics(
                symbol=ticker,
                provider=self.provider,
                ttm="only",
            ),
        )

        consensus = fetch(
            "consensus",
            lambda: obb.equity.estimates.consensus(
                symbol=ticker,
                provider=self.provider,
            ),
        )

        income = fetch(
            "income",
            lambda: obb.equity.fundamental.income(
                symbol=ticker,
                provider=self.provider,
                period="annual",
                limit=4,
            ),
        )

        cash = fetch(
            "cash",
            lambda: obb.equity.fundamental.cash(
                symbol=ticker,
                provider=self.provider,
                period="annual",
                limit=4,
            ),
        )

        news = fetch(
            "news",
            lambda: obb.news.company(
                symbol=ticker,
                provider=self.provider,
                limit=self.MAX_NEWS_ITEMS,
                order="desc",
            ),
        )

        normalized = self.normalize_research_snapshot(
            ticker=ticker,
            profile=profile,
            quote=quote,
            metrics=metrics,
            consensus=consensus,
            income=income,
            cash=cash,
            news=news,
        )

        normalized["data_quality"] = {
            "snapshot_version": self.SNAPSHOT_VERSION,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "provider": self.provider,
            "sections_available": [
                name for name, count in raw_sections.items()
                if count > 0
            ],
            "sections_missing": [
                name for name, count in raw_sections.items()
                if count == 0
            ],
            "warnings_count": len(warnings),
        }

        return normalized, {
            "raw": raw,
            "raw_sections": raw_sections,
            "warnings": warnings,
        }

    def normalize_research_snapshot(
        self,
        *,
        ticker: str,
        profile: list[dict[str, Any]],
        quote: list[dict[str, Any]],
        metrics: list[dict[str, Any]],
        consensus: list[dict[str, Any]],
        income: list[dict[str, Any]],
        cash: list[dict[str, Any]],
        news: list[dict[str, Any]],
    ) -> dict[str, Any]:

        p = profile[0] if profile else {}
        q = quote[0] if quote else {}
        m = metrics[0] if metrics else {}
        c = consensus[0] if consensus else {}

        company = {
            "symbol": self._pick(
                p,
                "symbol",
                default=ticker.upper(),
            ),
            "name": self._pick(p, "name", "long_name"),
            "sector": self._pick(p, "sector"),
            "industry": self._pick(
                p,
                "industry_category",
                "industry",
            ),
            "stock_exchange": self._pick(
                p,
                "stock_exchange",
                "exchange",
            ),
            "currency": self._pick(
                p,
                "currency",
                "reported_currency",
            ),
            "hq_country": self._pick(
                p,
                "hq_country",
                "country",
            ),
            "long_description": self._truncate(
                self._pick(
                    p,
                    "long_description",
                    "description",
                ),
                self.MAX_DESCRIPTION_CHARS,
            ),
            "company_url": self._pick(
                p,
                "company_url",
                "website",
                "website_url",
            ),
            "employees": self._pick(
                p,
                "employees",
                "employee_count",
            ),
        }

        current_price = self._pick(
            q,
            "last_price",
            default=m.get("last_price"),
        )

        year_high = self._pick(
            q,
            "year_high",
            default=m.get("year_high"),
        )

        market = {
            "current_price": current_price,
            "previous_close": self._pick(q, "prev_close"),
            "open": self._pick(q, "open"),
            "day_high": self._pick(q, "high"),
            "day_low": self._pick(q, "low"),
            "year_high": year_high,
            "year_low": self._pick(
                q,
                "year_low",
                default=m.get("year_low"),
            ),
            "volume": self._pick(q, "volume"),
            "average_volume": self._pick(
                q,
                "volume_average",
                "volume_avg",
                default=m.get("volume_avg"),
            ),
            "beta": self._pick(m, "beta"),
            "currency": self._pick(
                q,
                "currency",
                default=m.get("currency"),
            ),
            "market_cap": self._pick(m, "market_cap"),
            "distance_from_52w_high_pct": self._distance_from_high(
                current_price,
                year_high,
            ),
        }

        valuation = {
            "market_cap": self._pick(m, "market_cap"),
            "enterprise_value": self._pick(
                m,
                "enterprise_value",
            ),
            "pe_ttm": self._pick(m, "pe_ratio"),
            "forward_pe": self._pick(
                m,
                "forward_pe",
            ),
            "peg": self._pick(
                m,
                "peg_ratio",
                "peg_ratio_ttm",
            ),
            "price_to_sales": self._pick(
                m,
                "price_to_sales",
                "price_to_revenue",
            ),
            "price_to_book": self._pick(
                m,
                "price_to_book",
            ),
            "price_to_cash": self._pick(
                m,
                "price_to_cash",
            ),
            "price_to_free_cash_flow": self._pick(
                m,
                "price_to_free_cash_flow",
            ),
            "ev_to_sales": self._pick(
                m,
                "ev_to_sales",
                "enterprise_to_revenue",
            ),
            "ev_to_ebitda": self._pick(
                m,
                "ev_to_ebitda",
                "enterprise_to_ebitda",
            ),
            "ev_to_free_cash_flow": self._pick(
                m,
                "ev_to_free_cash_flow",
            ),
            "earnings_yield": self._pick(
                m,
                "earnings_yield",
            ),
            "free_cash_flow_yield": self._pick(
                m,
                "free_cash_flow_yield",
            ),
            "eps_ttm": self._pick(
                m,
                "eps_ttm",
                "eps",
            ),
            "eps_forward": self._pick(
                m,
                "eps_forward",
            ),
            "dividend_yield": self._pick(
                m,
                "dividend_yield",
            ),
        }

        latest_income = income[0] if income else {}

        financial_health = {
            "revenue_growth": self._pick(
                m,
                "revenue_growth",
            ),
            "earnings_growth": self._pick(
                m,
                "earnings_growth",
                "net_income_growth",
            ),
            "eps_growth": self._pick(
                m,
                "eps_growth",
            ),
            "ebitda_growth": self._pick(
                m,
                "ebitda_growth",
            ),
            "gross_margin": self._pick(
                m,
                "gross_margin",
            ),
            "operating_margin": self._pick(
                m,
                "operating_margin",
                "ebit_margin",
            ),
            "ebitda_margin": self._pick(
                m,
                "ebitda_margin",
            ),
            "profit_margin": self._pick(
                m,
                "profit_margin",
            ),
            "return_on_equity": self._pick(
                m,
                "return_on_equity",
            ),
            "return_on_invested_capital": self._pick(
                m,
                "return_on_invested_capital",
            ),
            "return_on_assets": self._pick(
                m,
                "return_on_assets",
            ),
            "debt_to_equity": self._pick(
                m,
                "debt_to_equity",
            ),
            "current_ratio": self._pick(
                m,
                "current_ratio",
            ),
            "quick_ratio": self._pick(
                m,
                "quick_ratio",
            ),
            "long_term_debt": self._pick(
                m,
                "long_term_debt",
            ),
            "total_debt": self._pick(
                m,
                "total_debt",
            ),
            "free_cash_flow_yield": self._pick(
                m,
                "free_cash_flow_yield",
            ),
            "free_cash_flow_to_firm": self._pick(
                m,
                "free_cash_flow_to_firm",
            ),
            "payout_ratio": self._pick(
                m,
                "payout_ratio",
            ),
            "income_statement_latest":
                self._compact_latest_financials(
                    latest_income
                ),
            "cash_flow_history":
                self._compact_cash_history(
                    cash
                ),
        }

        analyst_consensus = {
            "target_consensus": self._pick(
                c,
                "target_consensus",
            ),
            "target_median": self._pick(
                c,
                "target_median",
            ),
            "target_high": self._pick(
                c,
                "target_high",
            ),
            "target_low": self._pick(
                c,
                "target_low",
            ),
            "total_analysts": self._pick(
                c,
                "total_analysts",
            ),
            "raised": self._pick(
                c,
                "raised",
            ),
            "lowered": self._pick(
                c,
                "lowered",
            ),
            "most_recent_date": self._pick(
                c,
                "most_recent_date",
            ),
        }

        recent_news: list[dict[str, Any]] = []

        for item in news[: self.MAX_NEWS_ITEMS]:

            recent_news.append(
                {
                    "date": self._pick(
                        item,
                        "date",
                    ),
                    "title": self._pick(
                        item,
                        "title",
                    ),
                    "source": self._pick(
                        item,
                        "source",
                    ),
                    "url": self._pick(
                        item,
                        "url",
                    ),
                    "excerpt": self._truncate(
                        self._pick(
                            item,
                            "excerpt",
                            "summary",
                        ),
                        self.MAX_NEWS_EXCERPT_CHARS,
                    ),
                }
            )

        return {
            "schema_version": self.SNAPSHOT_VERSION,
            "company": company,
            "market": market,
            "valuation": valuation,
            "financial_health": financial_health,
            "analyst_consensus": analyst_consensus,
            "recent_news": recent_news,
        }

    # Backward-compatible profile normalization.
    def normalize_profile(
        self,
        results: list[dict[str, Any]],
    ) -> dict[str, Any]:

        first = results[0] if results else {}

        return {
            "symbol": self._pick(first, "symbol"),
            "name": self._pick(
                first,
                "name",
                "long_name",
            ),
            "sector": self._pick(
                first,
                "sector",
            ),
            "industry_category": self._pick(
                first,
                "industry_category",
                "industry",
            ),
            "stock_exchange": self._pick(
                first,
                "stock_exchange",
                "exchange",
            ),
            "currency": self._pick(
                first,
                "currency",
            ),
            "market_cap": self._pick(
                first,
                "market_cap",
            ),
            "hq_country": self._pick(
                first,
                "hq_country",
                "country",
            ),
            "long_description": self._truncate(
                self._pick(
                    first,
                    "long_description",
                    "description",
                ),
                self.MAX_DESCRIPTION_CHARS,
            ),
            "company_url": self._pick(
                first,
                "company_url",
                "website",
                "website_url",
            ),
            "employees": self._pick(
                first,
                "employees",
                "employee_count",
            ),
            "beta": self._pick(
                first,
                "beta",
            ),
            "dividend_yield": self._pick(
                first,
                "dividend_yield",
            ),
        }

    @staticmethod
    def yahoo_url(ticker: str) -> str:
        return f"https://finance.yahoo.com/quote/{ticker}/"

    @staticmethod
    def _compact_latest_financials(
        row: dict[str, Any],
    ) -> dict[str, Any]:

        fields = (
            "period_ending",
            "fiscal_year",
            "fiscal_period",
            "currency",
            "revenue",
            "gross_profit",
            "operating_income",
            "net_income",
            "ebitda",
            "ebit",
            "basic_eps",
            "diluted_eps",
        )

        return {
            field: row.get(field)
            for field in fields
            if row.get(field) is not None
        }

    @staticmethod
    def _compact_cash_history(
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:

        fields = (
            "period_ending",
            "fiscal_year",
            "operating_cash_flow",
            "capital_expenditure",
            "free_cash_flow",
            "net_cash_from_operating_activities",
        )

        return [
            {
                field: row.get(field)
                for field in fields
                if row.get(field) is not None
            }
            for row in rows[:4]
        ]

    @staticmethod
    def _truncate(
        value: Any,
        max_chars: int,
    ) -> Any:

        if value is None:
            return None

        value = OpenBBAdapter.to_jsonable(value)

        if isinstance(value, str) and len(value) > max_chars:
            return value[:max_chars].rstrip() + "…"

        return value

    @staticmethod
    def _pick(
        mapping: dict[str, Any],
        *keys: str,
        default: Any = None,
    ) -> Any:

        for key in keys:

            value = OpenBBAdapter._clean_value(
                mapping.get(key)
            )

            if value is not None:
                return value

        return default

    @staticmethod
    def _clean_value(value: Any) -> Any:

        if value is None:
            return None

        if isinstance(value, str) and not value.strip():
            return None

        return OpenBBAdapter.to_jsonable(value)

    @staticmethod
    def _distance_from_high(
        current: Any,
        high: Any,
    ) -> float | None:

        try:

            current_f = float(current)
            high_f = float(high)

            if high_f <= 0:
                return None

            return round(
                (current_f / high_f - 1.0) * 100.0,
                2,
            )

        except (TypeError, ValueError):

            return None

    @staticmethod
    def to_jsonable(value: Any) -> Any:

        if value is None or isinstance(
            value,
            (str, int, float, bool),
        ):
            return value

        if isinstance(value, dict):
            return {
                str(k): OpenBBAdapter.to_jsonable(v)
                for k, v in value.items()
            }

        if isinstance(value, (list, tuple)):
            return [
                OpenBBAdapter.to_jsonable(v)
                for v in value
            ]

        if hasattr(value, "model_dump"):
            return OpenBBAdapter.to_jsonable(
                value.model_dump(mode="json")
            )

        if hasattr(value, "dict"):
            return OpenBBAdapter.to_jsonable(
                value.dict()
            )

        if hasattr(value, "isoformat"):
            return value.isoformat()

        return str(value)

    @staticmethod
    def _results(
        response: Any,
    ) -> list[dict[str, Any]]:

        results = getattr(
            response,
            "results",
            None,
        ) or []

        value = OpenBBAdapter.to_jsonable(
            results
        )

        if isinstance(value, list):
            return [
                item
                if isinstance(item, dict)
                else {"value": item}
                for item in value
            ]

        if isinstance(value, dict):
            return [value]

        return []

    @staticmethod
    def _meta(
        response: Any,
    ) -> dict[str, Any]:

        return {
            "provider":
                OpenBBAdapter.to_jsonable(
                    getattr(
                        response,
                        "provider",
                        None,
                    )
                ),
            "warnings":
                OpenBBAdapter.to_jsonable(
                    getattr(
                        response,
                        "warnings",
                        None,
                    )
                ),
            "extra":
                OpenBBAdapter.to_jsonable(
                    getattr(
                        response,
                        "extra",
                        None,
                    )
                ),
        }

    @staticmethod
    def _load_openbb() -> Any:

        try:

            module = importlib.import_module(
                "openbb"
            )

            return module.obb

        except ImportError as exc:

            raise OpenBBAdapterError(
                "openbb_not_installed",
                "OpenBB is not installed. "
                "Install the 'openbb' package before running Sync.",
                cause=exc,
            ) from exc

        except Exception as exc:

            raise OpenBBAdapterError(
                "openbb_import_error",
                f"OpenBB could not be initialized: {exc}",
                cause=exc,
            ) from exc

    @staticmethod
    def _call(
        operation: str,
        fn: Callable[[Any], Any],
    ) -> Any:

        obb = OpenBBAdapter._load_openbb()

        try:

            return fn(obb)

        except Exception as exc:

            raise OpenBBAdapter._map_provider_error(
                exc,
                operation=operation,
            ) from exc

    @staticmethod
    def _map_provider_error(
        exc: Exception,
        *,
        operation: str = "OpenBB operation",
    ) -> OpenBBAdapterError:

        msg = str(exc).strip()
        lowered = msg.lower()

        if (
            "api key" in lowered
            or "credential" in lowered
            or "unauthor" in lowered
        ):
            code = "missing_credentials"

        elif "timeout" in lowered:
            code = "timeout"

        elif "failed to import extensions" in lowered:
            code = "openbb_extensions_missing"

        elif (
            "invalid" in lowered
            or "symbol" in lowered
            or "not found" in lowered
        ):
            code = "invalid_ticker_or_no_data"

        else:
            code = "provider_error"

        return OpenBBAdapterError(
            code,
            (
                f"{operation}: "
                f"{msg[:500] or exc.__class__.__name__}"
            ),
            cause=exc,
        )

