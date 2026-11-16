# ---------------------------------------------------------------------------
# Module 3: Mansfield Relative Strength vs KSE-100
# ---------------------------------------------------------------------------

class MansfieldRS:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._cache = {}

    def get_stock_close(self, ticker: str) -> Optional[float]:
        r = self.conn.execute("SELECT close_price FROM psx_daily_eod WHERE ticker = ? ORDER BY trade_date DESC LIMIT 1", (ticker,)).fetchone()
        return r["close_price"] if r else None

    def get_kse100_close(self) -> Optional[float]:
        r = self.conn.execute("SELECT close_price FROM psx_daily_eod WHERE ticker = 'KSE-100' ORDER BY trade_date DESC LIMIT 1").fetchone()
        return r["close_price"] if r else None

    def _get_rs20(self, ticker: str) -> Optional[float]:
        if ticker in self._cache:
            return self._cache[ticker]
        stock = self.get_stock_close(ticker)
        kse100 = self.get_kse100_close()
        if not stock or not kse100 or kse100 == 0:
            self._cache[ticker] = None
            return None
        rs = stock / kse100
        rows = self.conn.execute("SELECT close_price FROM psx_daily_eod WHERE ticker = ? ORDER BY trade_date DESC LIMIT 20", (ticker,)).fetchall()
        rs_vals = []
        for r in rows:
            k = self.conn.execute("SELECT close_price FROM psx_daily_eod WHERE ticker = 'KSE-100' ORDER BY trade_date DESC LIMIT 1 OFFSET ?", (0,)).fetchone()
            if k:
                rs_vals.append(r["close_price"] / k["close_price"])
        if not rs_vals:
            self._cache[ticker] = None
            return None
        avg = sum(rs_vals) / len(rs_vals)
        self._cache[ticker] = avg
        return avg

    def compute_mansfield_rs(self, ticker: str) -> dict:
        stock_close = self.get_stock_close(ticker)
        kse100_close = self.get_kse100_close()
        if not stock_close or not kse100_close or kse100_close == 0:
            return {"ticker": ticker, "rs": None, "mansfieldRs": None, "hardDrop": False, "flagRisingPositive": False}
        rs = stock_close / kse100_close
        rs20 = self._get_rs20(ticker)
        if not rs20 or rs20 == 0:
            return {"ticker": ticker, "rs": round(rs, 4), "mansfieldRs": None, "hardDrop": False, "flagRisingPositive": False}
        mans = ((rs / rs20) - 1) * 100
        hard_drop = mans < 0
        LOGGER.info("Mansfield RS %s: rs=%.4f rs20=%.4f mans=%.2f drop=%s", ticker, rs, rs20, mans, hard_drop)
        return {"ticker": ticker, "rs": round(rs, 4), "mansfieldRs": round(mans, 2), "hardDrop": hard_drop, "flagRisingPositive": True}

    def evaluate(self) -> list[dict]:
        tickers = [r["ticker"] for r in self.conn.execute("SELECT DISTINCT ticker FROM psx_daily_eod ORDER BY ticker").fetchall()]
        return [self.compute_mansfield_rs(t) for t in tickers]


# ---------------------------------------------------------------------------
# Module 4: Director Footprint (Clause 5.6.4)
# ---------------------------------------------------------------------------

class DirectorFootprint:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.acq_kw = ["acquisition", "acquirer", "bid", "takeover", "merger", "joint venture", "investment"]
        self.disposal_kw = ["disposal", "sale", "divestiture", "exit", "partition", "transfer", "donation", "sell"]

    def _classify(self, headline: str) -> str:
        hl = headline.lower()
        for kw in self.acq_kw:
            if kw in hl:
                return "ACQ"
        for kw in self.disposal_kw:
            if kw in hl:
                return "DIS"
        return "NONE"

    def get_disclosures(self, ticker: str) -> list[dict]:
        try:
            rows = self.conn.execute(
                "SELECT trade_date, headline, disclosure_url FROM psx_disclosures WHERE ticker = ? AND headline IS NOT NULL ORDER BY trade_date DESC LIMIT 10", (ticker,)
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    def get_current_close(self, ticker: str) -> Optional[float]:
        r = self.conn.execute("SELECT close_price FROM psx_daily_eod WHERE ticker = ? ORDER BY trade_date DESC LIMIT 1", (ticker,)).fetchone()
        return r["close_price"] if r else None

    def get_poc(self) -> Optional[float]:
        ls = LiquiditySweep(self.conn)
        poc, _ = ls.compute_poc()
        return poc

    def evaluate(self, ticker: str) -> dict:
        disclosures = self.get_disclosures(ticker)
        if not disclosures:
            return {"ticker": ticker, "totalDisclosures": 0, "acquisitionDeclarations": 0, "disposalDisclosures": 0, "recentConvictionBoost": False, "priceWithin3pctPoc": False, "priceWithin3pctDisclosure": False}
        acq = sum(1 for d in disclosures if self._classify(d["headline"]) == "ACQ")
        dis = sum(1 for d in disclosures if self._classify(d["headline"]) == "DIS")
        current_close = self.get_current_close(ticker)
        poc = self.get_poc()
        boost = False
        if current_close and poc:
            if abs(current_close - poc) / poc * 100 <= DIRECTOR_CONVICTION_TIGHT:
                boost = True
        return {
            "ticker": ticker,
            "totalDisclosures": len(disclosures),
            "acquisitionDeclarations": acq,
            "disposalDisclosures": dis,
            "recentConvictionBoost": boost,
            "priceWithin3pctPoc": boost,
            "priceWithin3pctDisclosure": False,
        }


# ---------------------------------------------------------------------------
# Main aggregation & JSON export
# ---------------------------------------------------------------------------

def aggregate_results() -> dict:
    conn = get_db_connection()
    try:
        ensure_psx_tables(conn)
        count = conn.execute("SELECT COUNT(*) FROM psx_daily_eod").fetchone()[0]
        if conn.execute("SELECT COUNT(DISTINCT trade_date) FROM psx_daily_eod").fetchone()[0] < 20:
            LOGGER.info("Only %d raw sessions in DB; backfilling from .Z", count)
            backfill_last_n_sessions(conn, 25)

        ls = LiquiditySweep(conn)
        coc = CostOfCarry(conn)
        mr = MansfieldRS(conn)
        df = DirectorFootprint(conn)

        ls_eval = ls.evaluate()
        coc_results = coc.evaluate_all()
        mans_results = mr.evaluate()
        tickers = [r["ticker"] for r in conn.execute("SELECT DISTINCT ticker FROM psx_daily_eod ORDER BY ticker").fetchall()]
        director_results = [df.evaluate(t) for t in tickers]

        payload = {
            "sessionDate": datetime.now().strftime("%Y-%m-%d"),
            "sessionTime": datetime.now().strftime("%H:%M:%S"),
            "poc": ls_eval.get("poc"),
            "volZScore": ls_eval.get("volZScore"),
            "liquiditySweep": ls_eval.get("liquidity_sweep"),
            "annualizedCarryPct": {r["ticker"]: r["annualizedCarryPct"] for r in coc_results},
            "carryFlags": {
                r["ticker"]: {"leverageOverheated": r["leverageOverheated"], "daysToExpiry": r["days_to_expiry"]}
                for r in coc_results
            },
            "mansfieldRs": {r["ticker"]: {
                "rs": r["rs"], "mansfieldRs": r["mansfieldRs"], "mansfieldRs20dAvg": r["mansfield_rs_20d_avg"],
                "hardDrop": r["hardDrop"], "flagRisingPositive": r["flagRisingPositive"],
            } for r in mans_results},
            "directorFootprint": {
                t["ticker"]: {
                    "totalDisclosures": t["totalDisclosures"],
                    "acquisitionDeclarations": t["acquisitionDeclarations"],
                    "disposalDisclosures": t["disposalDisclosures"],
                    "priceWithin3pctPoc": t["priceWithin3pctPoc"],
                    "priceWithin3pctDisclosure": t["priceWithin3pctDisclosure"],
                    "recentConvictionBoost": t["recentConvictionBoost"],
                } for t in director_results
            },
        }
        LOGGER.info("Aggregated %d tickers into latest.json", len(tickers))
        return payload
    finally:
        if not isinstance(conn, sqlite3.Connection):
            try:
                conn.close()
            except Exception:
                pass


def write_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = None
    if path.exists():
        try:
            with open(path) as f:
                existing = json.load(f)
        except Exception:
            existing = None
    if existing != payload:
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)
        LOGGER.info("Wrote %s (%d bytes)", path, path.stat().st_size)
    else:
        LOGGER.info("No change - skipped write")


def main(argv: Optional[list[str]] = None) -> int:
    _setup_logging()
    LOGGER.info("Starting daily tape processor (quantitative pipeline)")
    try:
        payload = aggregate_results()
        write_json(payload, OUTPUT_PATH)
        LOGGER.info("Daily tape processor completed successfully")
        return 0
    except Exception as e:
        LOGGER.exception("Daily tape processor failed: %s", e)
        try:
            err = {
                "sessionDate": datetime.now().strftime("%Y-%m-%d"),
                "sessionTime": datetime.now().strftime("%H:%M:%S"),
                "error": str(e), "poc": None, "volZScore": None,
                "liquiditySweep": False, "annualizedCarryPct": {},
                "carryFlags": {}, "mansfieldRs": {}, "directorFootprint": {},
            }
            write_json(err, OUTPUT_PATH)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
