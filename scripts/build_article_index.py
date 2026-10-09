#!/usr/bin/env python3
"""
記事ごとの指標を1本に統合する（判断レイヤーの単一データ源）。

背景
  これまで記事の評価は9つのCSVに分散し、それぞれが別のTOP20を出していた。
  実測するとTOP20同士の重なりは20本中0〜6本しかなく（v2と資産記事7日の16本を除く）、
  9つのTOP20に載る111本のうち69本は1つの指標にしか載っていなかった。
  パネルを移動するたびに違う記事が1位として提示され、読み手が動けない状態だった。

  そこで「どのパネルを見るか」ではなく「どう並べるか」の問題に変える。
  全記事 × 全指標を1枚の表にし、並べ替えと絞り込みで読む。

出力 : data/article_index.csv
入力 : uptime_ranking / asset_score_v1 / asset_score_v2 / article_quality
        / trend_analysis / period_ranking

指標の3軸
  規模 : 累計PV, 期間増加PV, 累計スキ
  持続 : 稼働率, 累計稼働日数, 最長連続稼働, v1, v2, ハーフライフ, 持続率
  勢い : 現在継続日数, 直近30日稼働, トレンドスコア, 7日合計PV
"""
from pathlib import Path
import pandas as pd

DATA = Path("data")
DST  = DATA / "article_index.csv"


def latest(df: pd.DataFrame) -> pd.DataFrame:
    """集計日が複数ある表は最新日のぶんだけ残す。"""
    if "集計日" in df.columns and df["集計日"].notna().any():
        return df[df["集計日"] == df["集計日"].max()].copy()
    return df.copy()


def read(name: str) -> pd.DataFrame:
    p = DATA / f"{name}.csv"
    if not p.exists():
        print(f"[warn] {p} が無いので飛ばします")
        return pd.DataFrame()
    return latest(pd.read_csv(p, low_memory=False))


def main() -> None:
    up = read("uptime_ranking")
    if up.empty:
        raise SystemExit("uptime_ranking.csv が必要です。先に build_uptime_ranking.py を実行してください")

    # uptime_ranking を土台にする（563記事すべてを持つ唯一の表）
    out = up.drop(columns=["rank"], errors="ignore").copy()
    asof = {"uptime_ranking": up["集計日"].iloc[0]}

    def join(name, cols, rename=None):
        df = read(name)
        if df.empty or "key" not in df.columns:
            return
        if "集計日" in df.columns:
            asof[name] = str(df["集計日"].iloc[0])
        have = [c for c in cols if c in df.columns]
        sub = df[["key"] + have].drop_duplicates("key")
        if rename:
            sub = sub.rename(columns=rename)
        nonlocal out
        out = out.merge(sub, on="key", how="left")

    join("asset_score_v1", ["資産スコア", "平均日次ビュー", "安定性"],
         {"資産スコア": "v1スコア", "安定性": "v1安定性"})
    join("asset_score_v2", ["資産スコア", "安定性"],
         {"資産スコア": "v2スコア", "安定性": "v2安定性"})
    join("article_quality",
         ["Age", "累計スキ", "コメント数", "スキ率(%)", "初速PV(7日)", "ピーク日次PV",
          "ハーフライフ(日)", "持続率", "安定性スコア", "成長タイプ", "質スコア"])
    join("trend_analysis", ["7日合計PV", "7日合計スキ", "トレンドスコア", "状態"],
         {"状態": "トレンド状態"})
    join("period_ranking", ["期間増加PV", "1日平均PV", "分析期間(日)"])

    # ── 4象限の割り当て ──
    # 縦軸は3つの条件で選ぶ。(1)規模と相関しない (2)値の粒度が十分 (3)中央値に同値が集中しない
    #   スキ率(%)    相関+0.064  453種  中央値上0%   ★採用
    #   質スコア      相関-0.229  227種  中央値上1%
    #   ハーフライフ  相関-0.063    5種  中央値上48%  ← 除外
    #   稼働率       相関+0.844  332種             ← 規模の言い換え
    # ハーフライフは規模と無相関だが値が5種類しかなく、48%が中央値ちょうどに乗る。
    # 象限が均等に割れて見えるのは境界上の半分を片側へ寄せているだけで、実際には分離していない。
    # スキ率なら「読まれた量 × 刺さり具合」として解釈でき、打ち手も変わる。
    med_rate = out["スキ率(%)"].median()
    med_pv   = out["累計PV"].median()

    def quad(r):
        rate = r.get("スキ率(%)")
        if pd.isna(rate):
            return "判定不可"
        sticky = rate >= med_rate
        big    = r["累計PV"] >= med_pv
        if sticky and big:       return "伸ばす"   # 読まれて刺さった。続編・横展開が効く
        if sticky and not big:   return "様子見"   # 刺さっているのに読まれていない。露出を足す
        if not sticky and big:   return "直す"     # 読まれているのに刺さらない。中身か期待値のズレ
        return "捨てる"                             # 学びを取って次へ

    out["象限"] = out.apply(quad, axis=1)
    out["中央値_スキ率"] = round(float(med_rate), 3)
    out["中央値_累計PV"] = int(med_pv)

    # 基準日が表ごとに違う（週次/月次は3日遅れることがある）。
    # 画面で「いつ時点か」を出せるよう、一番古い基準日を添える。
    out["基準日_最古"] = min(asof.values())

    out = out.sort_values(["累計PV"], ascending=False).reset_index(drop=True)
    out.to_csv(DST, index=False)

    print(f"[ok] {DST} / {len(out)} 記事 / {len(out.columns)} 列")
    print("     基準日: " + ", ".join(f"{k}={v}" for k, v in sorted(asof.items())))
    print(f"     しきい値: スキ率 {med_rate:.2f}% / 累計PV {int(med_pv)}（いずれも中央値）")
    print("     象限: " + " / ".join(f"{k} {v}本" for k, v in out["象限"].value_counts().items()))
    miss = [c for c in ["v1スコア", "v2スコア", "質スコア", "トレンドスコア", "期間増加PV"] if c not in out.columns]
    if miss:
        print(f"[warn] 取り込めなかった指標: {miss}")


if __name__ == "__main__":
    main()
