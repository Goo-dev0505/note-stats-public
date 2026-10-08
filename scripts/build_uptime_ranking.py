#!/usr/bin/env python3
"""
稼働日ベースの記事ランキングを生成する（3指標を1本のCSVに統合）。

入力 : data/articles.csv   日次スナップショット（date, key, title, read_count, ...）
出力 : data/uptime_ranking.csv

3つの指標（ダッシュボードの3パネルに対応）
  ① 累計稼働日数 : 通算で何日PVが増えたか            … 総量
  ② 最長連続稼働 : 連続して増え続けた最長区間（歴代記録）… 過去のピーク
  ③ 現在継続日数 : 集計日時点で途切れていない連続日数   … 現在の状態

  この3つは順位相関が低い（①×③はほぼ無相関）ため、別々のランキングとして
  見る価値がある。1本のCSVで3パネル分を賄う。

用語
  稼働日   : 前回観測より累計PVが増えた日（diff > 0）
  観測日数 : 収集対象に入ってから差分が取れた日数（初日は差分が取れないので除く）
  稼働率   : 累計稼働日数 ÷ 観測日数。観測期間の長さを打ち消した指標
  継続区分 : 新作 / 復活 / 継続 / 小休止 / 休眠（下の CLASSIFY_* を参照）

注意
  累計稼働日数と最長連続稼働は観測期間が長い記事ほど有利。
  ランキング表示時は必ず稼働率・観測日数を併記すること。
"""
from pathlib import Path
import pandas as pd

SRC = Path("data/articles.csv")
DST = Path("data/uptime_ranking.csv")

# 収集に失敗した日のスナップショット。記事数・PV合計が明らかに欠損している日を列挙する。
# 新たな候補は detect_bad_snapshots() が警告として出すので、確認してここに追記する。
BAD_SNAPSHOTS = ["2026-06-02"]

CLASSIFY_NEW_LAG   = 3    # 観測初日からこの日数以内に連続開始 → 「新作」
CLASSIFY_DORMANT   = 7    # この日数以上の休眠を挟んで再稼働 → 「復活」
CLASSIFY_PAUSE     = 2    # 連続が切れていても休眠がこの日数以内 → 「小休止」（まだ生きている）
RECENT_WINDOW      = 30   # 「直近N日稼働」の集計幅


def detect_bad_snapshots(df: pd.DataFrame, drop_ratio: float = 0.03) -> list[str]:
    """PV合計が前日より drop_ratio 以上減っている日を収集失敗候補として返す。"""
    total = df.groupby("date")["read_count"].sum().sort_index()
    ratio = total.pct_change()
    return [str(d.date()) for d in ratio[ratio < -drop_ratio].index]


def _runs(flags) -> list[tuple[int, int]]:
    """True が連続する区間を [(開始index, 終了index), ...] で返す。"""
    out, start = [], None
    for i, x in enumerate(flags):
        if x and start is None:
            start = i
        if not x and start is not None:
            out.append((start, i - 1))
            start = None
    if start is not None:
        out.append((start, len(flags) - 1))
    return out


def build(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["key", "date"])
    # 収集が飛んだ日は区間を分断しない。差分がプラスならまたいで1稼働日として数える。
    df["is_active"] = df.groupby("key")["read_count"].diff() > 0

    last_day = df["date"].max()
    recent_from = last_day - pd.Timedelta(days=RECENT_WINDOW)

    rows = []
    for key, s in df.groupby("key"):
        s = s.sort_values("date")
        dates = s["date"].to_numpy()
        act = s["is_active"].fillna(False).to_numpy()
        obs_start = pd.Timestamp(dates[0])
        obs_days = len(s) - 1
        active_days = int(act.sum())

        rec = {
            "key": key,
            "title": s["title"].iloc[-1],
            "累計PV": int(s["read_count"].iloc[-1]),
            "観測初日": obs_start.date().isoformat(),
            "観測日数": obs_days,
            "累計稼働日数": active_days,
            "稼働率": round(active_days / obs_days, 3) if obs_days else 0.0,
            "直近30日稼働": int(s.loc[s["date"] > recent_from, "is_active"].fillna(False).sum()),
        }

        runs = _runs(act)
        if not runs:
            rec |= {
                "最長連続稼働": 0, "記録開始": None, "記録終了": None, "記録更新中": False,
                "現在継続日数": 0, "継続開始": None, "継続区分": "休眠",
                "直前休眠日数": 0, "最終稼働日": None, "休眠日数": obs_days,
            }
            rows.append(rec)
            continue

        best = max(runs, key=lambda r: r[1] - r[0])
        last_run = runs[-1]
        ongoing = last_run[1] == len(act) - 1          # 最終観測日まで途切れていない

        if ongoing:
            cur_len = last_run[1] - last_run[0] + 1
            cur_start = pd.Timestamp(dates[last_run[0]])
            dormant = last_run[0] - runs[-2][1] - 1 if len(runs) >= 2 else 0
            if (cur_start - obs_start).days <= CLASSIFY_NEW_LAG:
                kind = "新作"                            # 公開以来一度も止まっていない
            elif dormant >= CLASSIFY_DORMANT:
                kind = "復活"                            # 休眠から戻ってきた
            else:
                kind = "継続"
        else:
            cur_len, cur_start, dormant, kind = 0, None, 0, None   # kind は休眠日数を見て後で決める

        last_active = pd.Timestamp(dates[max(i for i, x in enumerate(act) if x)])
        idle = int((last_day - last_active).days)
        if kind is None:
            # 1〜2日止まっただけの記事を「休眠」と呼ぶと実態とズレるので分ける
            kind = "小休止" if idle <= CLASSIFY_PAUSE else "休眠"

        rec |= {
            "最長連続稼働": best[1] - best[0] + 1,
            "記録開始": pd.Timestamp(dates[best[0]]).date().isoformat(),
            "記録終了": pd.Timestamp(dates[best[1]]).date().isoformat(),
            "記録更新中": bool(ongoing and best == last_run),
            "現在継続日数": cur_len,
            "継続開始": cur_start.date().isoformat() if cur_start is not None else None,
            "継続区分": kind,
            "直前休眠日数": int(dormant),
            "最終稼働日": last_active.date().isoformat(),
            "休眠日数": idle,
        }
        rows.append(rec)

    out = pd.DataFrame(rows)
    out["集計日"] = last_day.date().isoformat()
    out = out.sort_values(["累計稼働日数", "累計PV"], ascending=False).reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out


def main() -> None:
    df = pd.read_csv(SRC, low_memory=False)
    df["date"] = pd.to_datetime(df["date"])

    suspects = set(detect_bad_snapshots(df)) - set(BAD_SNAPSHOTS)
    if suspects:
        print(f"[warn] 収集失敗の可能性がある日: {sorted(suspects)} "
              f"→ 内容を確認して BAD_SNAPSHOTS に追記してください")

    df = df[~df["date"].isin(pd.to_datetime(BAD_SNAPSHOTS))]

    out = build(df)
    DST.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(DST, index=False)

    live = (out["現在継続日数"] > 0).sum()
    print(f"[ok] {DST}")
    print(f"     {len(out)} 記事 / 集計日 {out['集計日'].iloc[0]}")
    print(f"     継続中 {live} 本（復活 {(out['継続区分'] == '復活').sum()} / "
          f"新作 {(out['継続区分'] == '新作').sum()} / 継続 {(out['継続区分'] == '継続').sum()}）")
    print(f"     小休止 {(out['継続区分'] == '小休止').sum()} 本 / 休眠 {(out['継続区分'] == '休眠').sum()} 本")
    print(f"     歴代最長 {out['最長連続稼働'].max()} 日 / 記録更新中 {out['記録更新中'].sum()} 本")


if __name__ == "__main__":
    main()
