"""sector_rotation.py - sector performance tracking & catalyst filtering for PSX.

Groups tickers by PSX sector (Energy, Fertilizer, Banking, Cement, Tech, etc.),
tracks sector-relative momentum, and filters stock-level momentum selections to
favor names belonging to the top outperforming sectors of the month.

Sector scores are computed from the same in-memory bar store the rest of the
quant engine uses, so the module stays offline-only and has no external feed / messaging dependency.

Run as a module or import the functions from the quant package.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

from src.core.models import DailyBar  # noqa: E402

SESSIONS_PER_YEAR = 252
MONTHS_PER_YEAR = 12

# ---------------------------------------------------------------------------
# Sector registry
# ---------------------------------------------------------------------------

# Conservative, conservative-by-source PSX sector mapping for the tracked
# universe. Names absent from the map default to "OTHER" so a new ticker never
# silently gets assigned to a sector it does not belong to.
#
# The map covers the deep-backfill universe (core liquid names plus the wider
# active PSX equity list in scripts/deep_backfill.py). Sector labels here drive
# sector rotation, stat-arb pairing and the seasonality matrix, so a ticker that
# is added to the universe should be added here in the same change.
DEFAULT_SECTOR_MAP: Dict[str, str] = {
    # Full active PSX equity registry: 655 symbols mapped across the 36 official
    # PSX sector classifications (textile spinning / composite / weaving,
    # Modaraba, Leasing, Investment Banks, Jute, Apparel, Property, REIT,
    # Vanaspati, Woollen, Synthetic & Rayon, ...).
    #
    # Names absent here still default to "OTHER", but a ticker added to the
    # deep-backfill universe must be mapped here in the same change so sector
    # rotation, stat-arb pairing and the seasonality matrix stay aligned.
    # Apparel (5)
    "COTT": "Apparel", "IMAGE": "Apparel", "INKL": "Apparel", "MSOT": "Apparel",
    "STYLERS": "Apparel",
    # Auto (13)
    "AGTL": "Auto", "ATLH": "Auto", "DFML": "Auto", "GAIL": "Auto", "GAL": "Auto", "GHNI": "Auto",
    "GHNL": "Auto", "HCAR": "Auto", "HINO": "Auto", "INDU": "Auto", "MTL": "Auto", "PSMC": "Auto",
    "SAZEW": "Auto",
    # Auto Parts (13)
    "AGIL": "Auto Parts", "ATBA": "Auto Parts", "BELA": "Auto Parts", "BWHL": "Auto Parts",
    "DWAE": "Auto Parts", "EXIDE": "Auto Parts", "GTYR": "Auto Parts", "LOADS": "Auto Parts",
    "PTL": "Auto Parts", "SLM": "Auto Parts", "TBL": "Auto Parts", "THALL": "Auto Parts",
    "TREI": "Auto Parts",
    # Banking (24)
    "ABL": "Banking", "AKBL": "Banking", "BAFL": "Banking", "BAHL": "Banking", "BIPL": "Banking",
    "BML": "Banking", "BOK": "Banking", "BOP": "Banking", "FABL": "Banking", "HBL": "Banking",
    "HMB": "Banking", "JSBL": "Banking", "MCB": "Banking", "MEBL": "Banking", "NBP": "Banking",
    "NIB": "Banking", "SBL": "Banking", "SCBPL": "Banking", "SILK": "Banking", "SMBL": "Banking",
    "SMBLCPSA": "Banking", "SMBLCPSB": "Banking", "SNBL": "Banking", "UBL": "Banking",
    # Cable & Electrical (11)
    "CECL": "Cable & Electrical", "EMCO": "Cable & Electrical", "FCL": "Cable & Electrical",
    "JOPP": "Cable & Electrical", "PAEL": "Cable & Electrical", "PCAL": "Cable & Electrical",
    "SIEM": "Cable & Electrical", "SING": "Cable & Electrical", "WAVES": "Cable & Electrical",
    "WAVESAPP": "Cable & Electrical", "WHALE": "Cable & Electrical",
    # Cement (21)
    "ACPL": "Cement", "BWCL": "Cement", "CHCC": "Cement", "DBCI": "Cement", "DCL": "Cement",
    "DGKC": "Cement", "DNCC": "Cement", "FCCL": "Cement", "FECTC": "Cement", "FLYNG": "Cement",
    "GWLC": "Cement", "KOHC": "Cement", "LPCL": "Cement", "LUCK": "Cement", "MLCF": "Cement",
    "PAKCEM": "Cement", "PIOC": "Cement", "POWER": "Cement", "SMCPL": "Cement", "THCCL": "Cement",
    "ZELP": "Cement",
    # Chemicals (29)
    "ARPL": "Chemicals", "BAPL": "Chemicals", "BERG": "Chemicals", "BIFO": "Chemicals",
    "BUXL": "Chemicals", "DAAG": "Chemicals", "DOL": "Chemicals", "DYNO": "Chemicals",
    "EPCL": "Chemicals", "GCIL": "Chemicals", "GCWL": "Chemicals", "GCWLPRS": "Chemicals",
    "GGL": "Chemicals", "ICI": "Chemicals", "ICL": "Chemicals", "LCI": "Chemicals",
    "LINDE": "Chemicals", "LOTCHEM": "Chemicals", "LPGL": "Chemicals", "NICL": "Chemicals",
    "NRSL": "Chemicals", "PAKOXY": "Chemicals", "PGCL": "Chemicals", "PPVC": "Chemicals",
    "SARC": "Chemicals", "SHCI": "Chemicals", "SITC": "Chemicals", "SPL": "Chemicals",
    "WAHN": "Chemicals",
    # Energy (4)
    "MARI": "Energy", "OGDC": "Energy", "POL": "Energy", "PPL": "Energy",
    # Engineering (19)
    "ADOS": "Engineering", "AGHA": "Engineering", "ASL": "Engineering", "ASTL": "Engineering",
    "BCL": "Engineering", "BECO": "Engineering", "CSAP": "Engineering", "DADX": "Engineering",
    "DKL": "Engineering", "DSL": "Engineering", "HSPI": "Engineering", "INIL": "Engineering",
    "ISL": "Engineering", "ITTEFAQ": "Engineering", "KSBP": "Engineering", "MSCL": "Engineering",
    "MUGHAL": "Engineering", "MUGHALC": "Engineering", "PECO": "Engineering",
    # Fertilizer (7)
    "AGL": "Fertilizer", "AHCL": "Fertilizer", "EFERT": "Fertilizer", "ENGRO": "Fertilizer",
    "FATIMA": "Fertilizer", "FFBL": "Fertilizer", "FFC": "Fertilizer",
    # Food (31)
    "ASC": "Food", "BBFL": "Food", "BFAGRO": "Food", "BNL": "Food", "CLOV": "Food", "COLG": "Food",
    "FCEPL": "Food", "FFL": "Food", "GDL": "Food", "GIL": "Food", "GLPL": "Food", "ISIL": "Food",
    "MFFL": "Food", "MFL": "Food", "MUREB": "Food", "NATF": "Food", "NESTLE": "Food",
    "NMFL": "Food", "PREMA": "Food", "QUICE": "Food", "RMPL": "Food", "SCL": "Food",
    "SHEZ": "Food", "SLSOPVI": "Food", "SOYASUP": "Food", "TOMCL": "Food", "TREET": "Food",
    "UNITY": "Food", "UPFL": "Food", "WAHDAT": "Food", "ZIL": "Food",
    # Glass (9)
    "BGL": "Glass", "FRCL": "Glass", "GGGL": "Glass", "GHGL": "Glass", "GVGL": "Glass",
    "KCL": "Glass", "REGAL": "Glass", "STCL": "Glass", "TGL": "Glass",
    # Insurance (40)
    "AGIC": "Insurance", "AICL": "Insurance", "ALAC": "Insurance", "ALIFE": "Insurance",
    "ASIC": "Insurance", "ATIL": "Insurance", "BEEM": "Insurance", "BIIC": "Insurance",
    "CENI": "Insurance", "CSIL": "Insurance", "EFUG": "Insurance", "EFUL": "Insurance",
    "EWIC": "Insurance", "EWLA": "Insurance", "HICL": "Insurance", "HMICL": "Insurance",
    "IGIHL": "Insurance", "IGIIL": "Insurance", "IGIL": "Insurance", "INL": "Insurance",
    "JAZZSURE": "Insurance", "JGICL": "Insurance", "JLICL": "Insurance", "PAKQATAR": "Insurance",
    "PAKRI": "Insurance", "PGIC": "Insurance", "PIL": "Insurance", "PINL": "Insurance",
    "PKGI": "Insurance", "PQGTL": "Insurance", "PRIC": "Insurance", "RICL": "Insurance",
    "SHNI": "Insurance", "SICL": "Insurance", "SSIC": "Insurance", "SWL": "Insurance",
    "TPLI": "Insurance", "TPLL": "Insurance", "UNIC": "Insurance", "UVIC": "Insurance",
    # Investment Banks (48)
    "AHL": "Investment Banks", "AKDSL": "Investment Banks", "AMBL": "Investment Banks",
    "AMSL": "Investment Banks", "ARMG": "Investment Banks", "BIPLS": "Investment Banks",
    "CASH": "Investment Banks", "CYAN": "Investment Banks", "DAWH": "Investment Banks",
    "DCM": "Investment Banks", "DEL": "Investment Banks", "DHPL": "Investment Banks",
    "DLL": "Investment Banks", "EFGH": "Investment Banks", "ENGROH": "Investment Banks",
    "ESBL": "Investment Banks", "FCEL": "Investment Banks", "FCIBL": "Investment Banks",
    "FCSC": "Investment Banks", "FDIBL": "Investment Banks", "FDPL": "Investment Banks",
    "FNEL": "Investment Banks", "ICIBL": "Investment Banks", "IFSL": "Investment Banks",
    "IGIBL": "Investment Banks", "IML": "Investment Banks", "IMS": "Investment Banks",
    "ITSL": "Investment Banks", "JSCL": "Investment Banks", "JSGCL": "Investment Banks",
    "JSIL": "Investment Banks", "LSECL": "Investment Banks", "LSEFSL": "Investment Banks",
    "LSEVL": "Investment Banks", "MCBAH": "Investment Banks", "MCBIM": "Investment Banks",
    "NEXT": "Investment Banks", "OLPL": "Investment Banks", "PASL": "Investment Banks",
    "PIAHCLA": "Investment Banks", "PIAHCLB": "Investment Banks", "PRIB": "Investment Banks",
    "PSX": "Investment Banks", "SIBL": "Investment Banks", "SPAC1": "Investment Banks",
    "SPAC2": "Investment Banks", "TRIBL": "Investment Banks", "TSBL": "Investment Banks",
    # Jute (3)
    "ASRL": "Jute", "CJPL": "Jute", "SUHJ": "Jute",
    # Leasing (9)
    "CPAL": "Leasing", "ENGL": "Leasing", "GRYL": "Leasing", "PGLC": "Leasing", "PICL": "Leasing",
    "SLCL": "Leasing", "SLL": "Leasing", "SPCL": "Leasing", "SPLC": "Leasing",
    # Leather (6)
    "BATA": "Leather", "FIL": "Leather", "LEUL": "Leather", "PAKL": "Leather", "SGF": "Leather",
    "SRVI": "Leather",
    # Miscellaneous (23)
    "AKDHL": "Miscellaneous", "AKGL": "Miscellaneous", "ARPAK": "Miscellaneous",
    "DCTL": "Miscellaneous", "DIIL": "Miscellaneous", "ECOP": "Miscellaneous",
    "GAMON": "Miscellaneous", "GEMPACRA": "Miscellaneous", "GOC": "Miscellaneous",
    "HACC": "Miscellaneous", "HADC": "Miscellaneous", "MWMP": "Miscellaneous",
    "OML": "Miscellaneous", "PABC": "Miscellaneous", "PHDL": "Miscellaneous",
    "PSEL": "Miscellaneous", "SHFA": "Miscellaneous", "STPL": "Miscellaneous",
    "TISL": "Miscellaneous", "TRIPF": "Miscellaneous", "UBDL": "Miscellaneous",
    "UDLI": "Miscellaneous", "UDPL": "Miscellaneous",
    # Modaraba (26)
    "BFMOD": "Modaraba", "CSM": "Modaraba", "FANM": "Modaraba", "FCONM": "Modaraba",
    "FECM": "Modaraba", "FEM": "Modaraba", "FFLM": "Modaraba", "FHAM": "Modaraba",
    "FIBLM": "Modaraba", "FIM": "Modaraba", "FIMM": "Modaraba", "FNBM": "Modaraba",
    "FPJM": "Modaraba", "FPRM": "Modaraba", "FTMM": "Modaraba", "FTSM": "Modaraba",
    "GEMBCEM": "Modaraba", "OLPM": "Modaraba", "ORIXM": "Modaraba", "ORM": "Modaraba",
    "PIM": "Modaraba", "PMI": "Modaraba", "SINDM": "Modaraba", "TRSM": "Modaraba",
    "UCAPM": "Modaraba", "WASL": "Modaraba",
    # Oil Marketing (11)
    "APL": "Oil Marketing", "BPL": "Oil Marketing", "HASCOL": "Oil Marketing",
    "HTL": "Oil Marketing", "OBOY": "Oil Marketing", "PSO": "Oil Marketing",
    "SHEL": "Oil Marketing", "SNGP": "Oil Marketing", "SPSL": "Oil Marketing",
    "SSGC": "Oil Marketing", "WAFI": "Oil Marketing",
    # Paper (13)
    "ABSON": "Paper", "CEPB": "Paper", "CPPL": "Paper", "DBSL": "Paper", "GEMPAPL": "Paper",
    "IPAK": "Paper", "MACFL": "Paper", "MERIT": "Paper", "PKGS": "Paper", "PPP": "Paper",
    "RPL": "Paper", "SEPL": "Paper", "SPEL": "Paper",
    # Pharma (18)
    "ABOT": "Pharma", "AGP": "Pharma", "BFBIO": "Pharma", "CPHL": "Pharma", "CWHC": "Pharma",
    "FEROZ": "Pharma", "GLAXO": "Pharma", "GSKCH": "Pharma", "HALEON": "Pharma",
    "HINOON": "Pharma", "HPL": "Pharma", "IBLHL": "Pharma", "LIVEN": "Pharma", "MACTER": "Pharma",
    "OTSU": "Pharma", "SAPL": "Pharma", "SEARL": "Pharma", "WYETH": "Pharma",
    # Power (19)
    "ALTN": "Power", "EPQL": "Power", "GEMMEL": "Power", "GENP": "Power", "HUBC": "Power",
    "KAPCO": "Power", "KEL": "Power", "KOHE": "Power", "KOHP": "Power", "LPL": "Power",
    "NCPL": "Power", "NGLEL": "Power", "NPL": "Power", "PKGP": "Power", "SEL": "Power",
    "SEPCO": "Power", "SGPL": "Power", "SPWL": "Power", "TSPL": "Power",
    # Property (5)
    "BRRG": "Property", "HUSI": "Property", "JVDC": "Property", "PACE": "Property",
    "TPLP": "Property",
    # REIT (7)
    "DCR": "REIT", "GRR": "REIT", "IREIT": "REIT", "JSRR": "REIT", "NNAR": "REIT", "SRR": "REIT",
    "TPLRF1": "REIT",
    # Refining (5)
    "ATRL": "Refining", "BYCO": "Refining", "CNERGY": "Refining", "NRL": "Refining",
    "PRL": "Refining",
    # Sugar (34)
    "AABS": "Sugar", "ADAMS": "Sugar", "AGSML": "Sugar", "ALNRS": "Sugar", "ANSM": "Sugar",
    "BAFS": "Sugar", "CHAS": "Sugar", "DWSM": "Sugar", "FRSM": "Sugar", "HABSM": "Sugar",
    "HAL": "Sugar", "HRPL": "Sugar", "HSM": "Sugar", "HWQS": "Sugar", "IMSL": "Sugar",
    "JDWS": "Sugar", "JSML": "Sugar", "KPUS": "Sugar", "MIRKS": "Sugar", "MRNS": "Sugar",
    "MZSM": "Sugar", "NONS": "Sugar", "PMRS": "Sugar", "PNGRS": "Sugar", "SANSM": "Sugar",
    "SASML": "Sugar", "SHJS": "Sugar", "SHSML": "Sugar", "SKRS": "Sugar", "SLSO": "Sugar",
    "SML": "Sugar", "TCORP": "Sugar", "TICL": "Sugar", "TSML": "Sugar",
    # Synthetic & Rayon (12)
    "AASM": "Synthetic & Rayon", "DSFL": "Synthetic & Rayon", "GATI": "Synthetic & Rayon",
    "IBFL": "Synthetic & Rayon", "NAFL": "Synthetic & Rayon", "NORS": "Synthetic & Rayon",
    "NSRM": "Synthetic & Rayon", "PSYL": "Synthetic & Rayon", "RUPL": "Synthetic & Rayon",
    "SGABL": "Synthetic & Rayon", "SGFL": "Synthetic & Rayon", "TRPOL": "Synthetic & Rayon",
    # Tech (24)
    "AIRLINK": "Tech", "AVN": "Tech", "GEMNETS": "Tech", "GEMSPNL": "Tech", "HCL": "Tech",
    "HUMNL": "Tech", "ITANZ": "Tech", "MDTL": "Tech", "NETSOL": "Tech", "OCTOPUS": "Tech",
    "PAKD": "Tech", "PTC": "Tech", "QTECH": "Tech", "SELECT": "Tech", "STL": "Tech", "SYM": "Tech",
    "SYS": "Tech", "TELE": "Tech", "TPL": "Tech", "TPLT": "Tech", "TRG": "Tech", "WTL": "Tech",
    "ZAL": "Tech", "ZUMA": "Tech",
    # Textile Composite (51)
    "ADMM": "Textile Composite", "AHTM": "Textile Composite", "ANL": "Textile Composite",
    "ANLNV": "Textile Composite", "ANTM": "Textile Composite", "ARUJ": "Textile Composite",
    "BHAT": "Textile Composite", "BTL": "Textile Composite", "CHBL": "Textile Composite",
    "CRTM": "Textile Composite", "FASM": "Textile Composite", "FML": "Textile Composite",
    "FSWL": "Textile Composite", "FTHM": "Textile Composite", "FZCM": "Textile Composite",
    "GATM": "Textile Composite", "GFIL": "Textile Composite", "HAEL": "Textile Composite",
    "HAFL": "Textile Composite", "HATM": "Textile Composite", "ILP": "Textile Composite",
    "ISTM": "Textile Composite", "JUBS": "Textile Composite", "KAKL": "Textile Composite",
    "KHYT": "Textile Composite", "KML": "Textile Composite", "KOIL": "Textile Composite",
    "KTML": "Textile Composite", "MEHT": "Textile Composite", "MFTM": "Textile Composite",
    "MTIL": "Textile Composite", "MUBT": "Textile Composite", "NCL": "Textile Composite",
    "NINA": "Textile Composite", "NML": "Textile Composite", "PASM": "Textile Composite",
    "QUET": "Textile Composite", "REDCO": "Textile Composite", "REWM": "Textile Composite",
    "SAPT": "Textile Composite", "SCHT": "Textile Composite", "SFAT": "Textile Composite",
    "SFL": "Textile Composite", "SFLL": "Textile Composite", "STML": "Textile Composite",
    "SURC": "Textile Composite", "TAJT": "Textile Composite", "TOWL": "Textile Composite",
    "USMT": "Textile Composite", "ZAHID": "Textile Composite", "ZHCM": "Textile Composite",
    # Textile Spinning (84)
    "AAL": "Textile Spinning", "AATM": "Textile Spinning", "ADTM": "Textile Spinning",
    "ALQT": "Textile Spinning", "AMTEX": "Textile Spinning", "ANNT": "Textile Spinning",
    "APOT": "Textile Spinning", "AQTM": "Textile Spinning", "ARCTM": "Textile Spinning",
    "ASTM": "Textile Spinning", "AWTX": "Textile Spinning", "AZMT": "Textile Spinning",
    "AZTM": "Textile Spinning", "BCML": "Textile Spinning", "BILF": "Textile Spinning",
    "BROT": "Textile Spinning", "CCM": "Textile Spinning", "CFL": "Textile Spinning",
    "CLOUD": "Textile Spinning", "CTM": "Textile Spinning", "CWSM": "Textile Spinning",
    "DFSM": "Textile Spinning", "DINT": "Textile Spinning", "DKTM": "Textile Spinning",
    "DMC": "Textile Spinning", "DMIL": "Textile Spinning", "DMTM": "Textile Spinning",
    "DMTX": "Textile Spinning", "DSIL": "Textile Spinning", "DSML": "Textile Spinning",
    "DWTM": "Textile Spinning", "ELCM": "Textile Spinning", "ELSM": "Textile Spinning",
    "FAEL": "Textile Spinning", "GADT": "Textile Spinning", "GLAT": "Textile Spinning",
    "GLOT": "Textile Spinning", "GOEM": "Textile Spinning", "GSPM": "Textile Spinning",
    "GUSM": "Textile Spinning", "GUTM": "Textile Spinning", "HAJT": "Textile Spinning",
    "HIRAT": "Textile Spinning", "HMIM": "Textile Spinning", "IDEAL": "Textile Spinning",
    "IDRT": "Textile Spinning", "IDSM": "Textile Spinning", "IDYM": "Textile Spinning",
    "ISHT": "Textile Spinning", "JATM": "Textile Spinning", "JDMT": "Textile Spinning",
    "JKSM": "Textile Spinning", "KACM": "Textile Spinning", "KHSM": "Textile Spinning",
    "KOHTM": "Textile Spinning", "KOSM": "Textile Spinning", "KSTM": "Textile Spinning",
    "LMSM": "Textile Spinning", "MDTM": "Textile Spinning", "MQTM": "Textile Spinning",
    "MUKT": "Textile Spinning", "NAGC": "Textile Spinning", "NATM": "Textile Spinning",
    "NCML": "Textile Spinning", "NPSM": "Textile Spinning", "OLSM": "Textile Spinning",
    "PRET": "Textile Spinning", "RAVT": "Textile Spinning", "RCML": "Textile Spinning",
    "RUBY": "Textile Spinning", "SAIF": "Textile Spinning", "SERT": "Textile Spinning",
    "SHCM": "Textile Spinning", "SHDT": "Textile Spinning", "SLSOPP": "Textile Spinning",
    "SLYT": "Textile Spinning", "SNAI": "Textile Spinning", "SRSM": "Textile Spinning",
    "SSML": "Textile Spinning", "SUCM": "Textile Spinning", "SUTM": "Textile Spinning",
    "SZTM": "Textile Spinning", "TATM": "Textile Spinning", "THAS": "Textile Spinning",
    # Textile Weaving (15)
    "ASHT": "Textile Weaving", "AYZT": "Textile Weaving", "HKKT": "Textile Weaving",
    "ICCI": "Textile Weaving", "ICCT": "Textile Weaving", "MOHE": "Textile Weaving",
    "PCML": "Textile Weaving", "PRWM": "Textile Weaving", "SDIL": "Textile Weaving",
    "SDOT": "Textile Weaving", "SERF": "Textile Weaving", "SMTM": "Textile Weaving",
    "STJT": "Textile Weaving", "YOUW": "Textile Weaving", "ZTL": "Textile Weaving",
    # Tobacco (3)
    "KHTC": "Tobacco", "PAKT": "Tobacco", "PMPK": "Tobacco",
    # Transport (7)
    "BLUEX": "Transport", "CLVL": "Transport", "GEMBLUEX": "Transport", "PIBTL": "Transport",
    "PICT": "Transport", "PNSC": "Transport", "SLGL": "Transport",
    # Vanaspati (3)
    "POML": "Vanaspati", "SSOM": "Vanaspati", "SURAJ": "Vanaspati",
    # Woollen (2)
    "BNWM": "Woollen", "MOON": "Woollen",
    # 786 Investments is a live equity whose numeric symbol breaks the usual
    # alpha-prefix convention; Yahoo carries no series for it, so it is listed
    # for registry completeness only.
    "786": "Investment Banks",
}


@dataclass
class SectorStats:
    sector: str
    members: int
    momentum: float  # average composite 3M+6M ROC across members with enough history
    avg_volume: float
    # Catalyst: retail-driven turnover spike minus its own trailing norm, in volume units.
    catalyst_score: float


def sector_of(ticker: str, sector_map: Optional[Dict[str, str]] = None) -> str:
    """Return the canonical sector label for a ticker, defaulting to 'OTHER'."""
    return (sector_map or DEFAULT_SECTOR_MAP).get(ticker.strip().upper(), "OTHER")


def group_by_sector(
    tickers: List[str],
    sector_map: Optional[Dict[str, str]] = None,
) -> Dict[str, List[str]]:
    """Return {sector: [tickers]} for the given universe."""
    out: Dict[str, List[str]] = {}
    for t in tickers:
        out.setdefault(sector_of(t, sector_map), []).append(t)
    return out


# ---------------------------------------------------------------------------
# Risk / volatility helpers (shared by sizing module)
# ---------------------------------------------------------------------------

def atr(bars: List[DailyBar], period: int = 14) -> Optional[float]:
    """Average True Range ending at the last bar in `bars`."""
    if len(bars) < 2:
        return None
    recent = bars[-(period + 1) :]
    trs: List[float] = []
    for i in range(1, len(recent)):
        curr, prev = recent[i], recent[i - 1]
        tr = max(
            curr.high_price - curr.low_price,
            abs(curr.high_price - prev.close_price),
            abs(curr.low_price - prev.close_price),
        )
        trs.append(tr)
    return sum(trs) / len(trs)


def atr_pct(bars: List[DailyBar], period: int = 14) -> float:
    """ATR expressed as a % of the latest close (volatility intensity)."""
    a = atr(bars, period)
    close = bars[-1].close_price if bars else 0.0
    if a is None or close <= 0:
        return 0.0
    return a / close * 100


def beta_vs_index(
    stock_bars: List[DailyBar],
    index_bars: List[DailyBar],
    window: int = 63,
) -> float:
    """Simple single-factor beta of stock returns vs index returns over a trailing window.

    Falls back to 1.0 when either tape is too short or variance is degenerate, which
    is the neutral prior a risk engine would use for an unmeasurable name.
    """
    if len(stock_bars) < window + 1 or len(index_bars) < window + 1:
        return 1.0
    stock = stock_bars[-window - 1 :]
    index = index_bars[-window - 1 :]
    if len(stock) != len(index):
        return 1.0
    stock_ret: List[float] = []
    index_ret: List[float] = []
    for i in range(1, len(stock)):
        sr = (stock[i].close_price / stock[i - 1].close_price) - 1
        ir = (index[i].close_price / index[i - 1].close_price) - 1
        stock_ret.append(sr)
        index_ret.append(ir)
    n = len(stock_ret)
    if n < 2:
        return 1.0
    mean_s = sum(stock_ret) / n
    mean_i = sum(index_ret) / n
    cov = sum((s - mean_s) * (i - mean_i) for s, i in zip(stock_ret, index_ret)) / n
    var_i = sum((i - mean_i) ** 2 for i in index_ret) / n
    if var_i <= 1e-12:
        return 1.0
    beta = cov / var_i
    if not math.isfinite(beta) or beta <= 0:
        return 1.0
    return beta


# ---------------------------------------------------------------------------
# Sector scoring
# ---------------------------------------------------------------------------

def composite_momentum(bars: List[DailyBar], session_index: int) -> float:
    """3-month + 6-month ROC combined — mirrors momentum_rotation.composite_momentum."""
    lookback3 = max(1, int(3 * SESSIONS_PER_YEAR / MONTHS_PER_YEAR))
    lookback6 = max(1, int(6 * SESSIONS_PER_YEAR / MONTHS_PER_YEAR))

    def roc(months_back: int, lb: int) -> float:
        start = session_index - lb
        if start < 0:
            return 0.0
        past = bars[start].close_price
        current = bars[session_index].close_price
        if past <= 0:
            return 0.0
        return (current / past - 1) * 100

    return roc(3, lookback3) + roc(6, lookback6)


def sector_momentum_stats(
    bars_by_ticker: Dict[str, List[DailyBar]],
    sector_map: Optional[Dict[str, str]] = None,
) -> Dict[str, SectorStats]:
    """Score every sector in the tape by member momentum and average turnover.

    Only members with a full 6-month lookback score into the momentum average;
    a sector full of unmeasurable names scores low, which is the conservative
    choice for a catalyst filter.
    """
    groups = group_by_sector(list(bars_by_ticker.keys()), sector_map)
    stats: Dict[str, SectorStats] = {}
    for sector, members in groups.items():
        mom_scores: List[float] = []
        vols: List[float] = []
        for t in members:
            bars = bars_by_ticker.get(t)
            if not bars or len(bars) < int(7 * SESSIONS_PER_YEAR / MONTHS_PER_YEAR):
                continue
            idx = len(bars) - 1
            mom_scores.append(composite_momentum(bars, idx))
            vols.append(bars[-1].volume)
        momentum = sum(mom_scores) / len(mom_scores) if mom_scores else 0.0
        avg_volume = sum(vols) / len(vols) if vols else 0.0
        stats[sector] = SectorStats(
            sector=sector,
            members=len(members),
            momentum=round(momentum, 2),
            avg_volume=round(avg_volume, 0),
            catalyst_score=0.0,
        )
    return stats


def sector_catalyst_scores(
    bars_by_ticker: Dict[str, List[DailyBar]],
    sector_map: Optional[Dict[str, str]] = None,
    window_sessions: int = 10,
) -> Dict[str, float]:
    """Per-sector retail-catalyst score: recent turnover spike above trailing norm.

    For each ticker, catalyst = last-session volume / (avg volume over the trailing
    `window_sessions`) minus 1; the sector score is the member average. A sector whose
    members are collectively seeing elevated turnover (frontside of a catalyst) scores
    higher than a dormant one.
    """
    groups = group_by_sector(list(bars_by_ticker.keys()), sector_map)
    scores: Dict[str, float] = {}
    for sector, members in groups.items():
        cat: List[float] = []
        for t in members:
            bars = bars_by_ticker.get(t)
            if not bars or len(bars) < window_sessions + 1:
                continue
            recent = bars[-(window_sessions + 1) :]
            avg_vol = sum(b.volume for b in recent[:-1]) / window_sessions
            last_vol = recent[-1].volume
            if avg_vol > 0:
                cat.append(last_vol / avg_vol - 1)
        scores[sector] = round(sum(cat) / len(cat) * 100, 2) if cat else 0.0
    return scores


def top_n_sectors(
    bars_by_ticker: Dict[str, List[DailyBar]],
    top_n: int = 2,
    sector_map: Optional[Dict[str, str]] = None,
    use_catalyst: bool = True,
) -> List[Tuple[str, float]]:
    """Return the top-N outperforming sectors of the moment.

    Ranking blends momentum (3M+6M member ROC) with the catalyst score when
    ``use_catalyst`` is on, which is the institutional tilt toward sectors that
    are both strong and actively repricing.
    """
    stats = sector_momentum_stats(bars_by_ticker, sector_map)
    catalysts = sector_catalyst_scores(bars_by_ticker, sector_map) if use_catalyst else {}
    ranked: List[Tuple[str, float]] = []
    for sector, s in stats.items():
        momentum = s.momentum
        catalyst = catalysts.get(sector, 0.0)
        # Momentum carries the weight; catalyst is a tie-breaker/overlay.
        combined = momentum + max(0.0, catalyst) * 0.25
        ranked.append((sector, round(combined, 2)))
    ranked.sort(key=lambda item: -item[1])
    return ranked[: max(top_n, 1)]


def sector_filtered_leaders(
    ticker_ranking: List[Tuple[str, float]],
    bars_by_ticker: Dict[str, List[DailyBar]],
    top_sectors: List[str],
    sector_map: Optional[Dict[str, str]] = None,
    sector_bias_weight: float = 0.5,
) -> List[Tuple[str, float]]:
    """Bias a stock-level momentum ranking toward tickers in `top_sectors`.

    Names in the leading sectors keep their momentum score; names outside them
    are discounted by `sector_bias_weight` so the filter favors sector leaders
    without fully excluding out-of-sector strong names (a basket still wants
    diversification).
    """
    top_set = set(top_sectors)
    out: List[Tuple[str, float]] = []
    for ticker, score in ticker_ranking:
        sec = sector_of(ticker, sector_map)
        adj = score if sec in top_set else score * (1 - sector_bias_weight)
        out.append((ticker, round(adj, 2)))
    out.sort(key=lambda item: -item[1])
    return out
