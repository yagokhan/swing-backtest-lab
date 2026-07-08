"""Başlangıç-tarihi jitter sağlamlık testi: gil-pnl92 avantajı pencere kaymasına dayanıklı mı?

5y penceresinin başlangıcı ±aylarla kaydırılır; her başlangıç için baz ve gil-pnl92
koşulur, Δroi + kaç takas olduğu yazılır. Avantaj tek şanslı takasa (MRVL→META)
dayanıyorsa, o takası içermeyen/ıskalayan pencerelerde Δ'nın çökmesi beklenir.
"""
import copy
import sys

sys.path.insert(0, "/home/gokhan")
import altguard_lab as L

STARTS = ["2020-11-01", "2021-01-01", "2021-03-01", "2021-05-01",
          "2021-07-01", "2021-09-01", "2021-11-01", "2022-01-01"]

L.load_data()
print("%-12s %10s %10s %8s %6s  %s" % ("başlangıç", "baz roi", "gil roi", "Δroi", "takas", "takaslar"))
for sd in STARTS:
    res = {}
    for name, gil in (("baz", None), ("gil", ("pnl", 92))):
        c = copy.deepcopy(L.base_cfg()); c.start_date = sd; c.end_date = ""
        L.GKX.GIL = gil; L.GKX.RSX = None; L.GKX.VOLK = None
        L.GKX.GIL_VPCT = 0.0; L.GKX.GIL_VUW = 0; L.GKX.GIL_MIN_AGE = 5
        bt = L.GKX(c, market=L.MARKET); bt.run()
        res[name] = (bt.metrics()["roi"], list(bt.gil_log))
    droi = res["gil"][0] - res["baz"][0]
    swaps = "; ".join("%s %s→%s(q%d)" % (g[0][2:7], g[1], g[2], g[5]) for g in res["gil"][1])
    print("%-12s %+10.1f %+10.1f %+8.1f %6d  %s" % (
        sd, res["baz"][0], res["gil"][0], droi, len(res["gil"][1]), swaps), flush=True)
