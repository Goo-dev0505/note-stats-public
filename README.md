# note-stats-public

note.com の運用統計を配信する公開リポジトリ。
データ収集は別リポジトリ（`note-stats-tracker`）で行い、ここには**配信用のCSVと閲覧用のダッシュボード**だけを置く。

**ダッシュボード** → https://goo-dev0505.github.io/note-stats-public/index.html

---

## 構成

```
data/     配信用CSV。note-stats-tracker が日次で更新・push する
docs/     GitHub Pages で公開されるダッシュボード（単一HTML・ビルド不要）
scripts/  このリポジトリ内のCSVから派生CSVを作るスクリプト
```

ダッシュボードは CSV を `raw.githubusercontent.com/Goo-dev0505/note-stats-public/main/data/` から直接 fetch する。
配信先URLは `docs/index.html` の `CONFIG.dataBase` で定義している。

### ダッシュボードの種類

| ファイル | 用途 |
|---|---|
| `docs/index.html` | フル版（本体） |
| `docs/index_pro.html` | 拡張版 |
| `docs/index_lite.html` / `index_lite_v2.html` | 軽量版 |
| `docs/note_stats_mobile.html` | モバイル向け |
| `docs/funnel.html` | ファネル分析（インプレッション→PV→スキ→コメント） |

---

## データファイル

| ファイル | 粒度 | 内容 |
|---|---|---|
| `articles.csv` | 記事 × 日 | **全データの元**。日次スナップショット（累計PV・スキ・コメント） |
| `daily_summary.csv` | 日 | アカウント全体の日次集計 |
| `followers.csv` | 日 | フォロワー数の推移 |
| `weekly_summary.csv` / `monthly_summary.csv` | 記事 × 週/月 | 期間ごとの増加PV・スキとランク |
| `trend_analysis.csv` | 記事 | 直近7日の動態とトレンドスコア |
| `asset_articles.csv` | 記事 | バースト後の定着確認（直近ウィンドウ） |
| `asset_score_v1/v2.csv` | 記事 | 資産スコア（2つの定義を併走させて比較中） |
| `article_quality.csv` | 記事 | 初速・ハーフライフ・持続率・成長タイプ |
| `article_trend.csv` | 記事 | 公開からの経過日ごとの日次PV（day0〜） |
| `period_ranking.csv` | 記事 | 指定期間のPV増加ランキング |
| `funnel_*.csv` | 日 / 累計 | 公式ダッシュボード由来のファネル指標 |
| `uptime_ranking.csv` | 記事 | **稼働日ベースの3指標**（下記） |

---

## 稼働日ベースの3指標（uptime_ranking.csv）

`articles.csv` の日次スナップショットから「その日PVが増えたか」を判定し、記事の**働きぶり**を3つの角度で測る。
生成は `scripts/build_uptime_ranking.py`。

| 指標 | 性質 | 答える問い | 対応パネル |
|---|---|---|---|
| 累計稼働日数 | 総量 | 通算どれだけ働いたか | UPTIME |
| 最長連続稼働 | 過去のピーク | 一番ノッてた時どこまで続いたか | RECORD |
| 現在継続日数 | 現在の状態 | 今どれが生きてるか | LIVE |

この3つは順位相関が低く、独立した指標として扱える（実測値・n=554）。

| | 累計稼働 | 最長連続 | 現在継続 |
|---|---|---|---|
| **累計稼働** | 1.000 | 0.455 | -0.024 |
| **最長連続** | 0.455 | 1.000 | 0.241 |
| **現在継続** | -0.024 | 0.241 | 1.000 |

TOP20の重複は 累計∩現在 = 1本のみ。3つすべてに入る記事は1本。

### 用語

- **稼働日** — 前回観測より累計PVが増えた日（diff > 0）
- **観測日数** — 収集対象に入ってから差分が取れた日数（初日は差分が取れないので除く）
- **稼働率** — 累計稼働日数 ÷ 観測日数。観測期間の長さを打ち消した指標
- **継続区分** — 記事の現在状態を5分類

| 区分 | 条件 |
|---|---|
| 新作 | 観測初日から3日以内に連続開始（公開以来一度も止まっていない） |
| 復活 | 7日以上の休眠を挟んで再稼働 |
| 継続 | 連続中。上記以外 |
| 小休止 | 連続は切れたが最終稼働から2日以内 |
| 休眠 | 最終稼働から3日以上 |

### 読み方の注意

- **累計稼働日数と最長連続稼働は、観測期間が長い記事ほど有利**。ランキングとして見るときは稼働率・観測日数を必ず併記する。
- **稼働率は観測期間が短いほど100%に張り付く**。ダッシュボードでは `CONFIG.uptimeMinObs`（既定30日）で足切りしている。
- **新作は構造上かならず「自己ベスト」になる**。古い記事と比べるときは自己ベスト比ではなく日数そのもので見る。
- **プロフィール固定記事はPVが底上げされる**。除外はせず「固定」バッジで明示する（`CONFIG.pinnedKeys` にキーを列挙）。

### データ品質

収集に失敗した日のスナップショットは集計から除外する。`scripts/build_uptime_ranking.py` の `BAD_SNAPSHOTS` に列挙。

- `2026-06-02` — 記事数390本（前後は396〜401本）、PV合計が前日比 -2.5万。除外しないと329記事が「マイナス成長」と誤判定される。

スクリプトは `detect_bad_snapshots()` でPV合計が前日比3%以上減った日を警告する。新しい候補が出たら内容を確認のうえ `BAD_SNAPSHOTS` に追記する。

なお収集が飛んだだけの日（`2026-01-04` / `2026-01-17` / `2026-06-03`）は連続区間を分断せず、またいで1稼働日として数える。ここを非稼働扱いにすると最長記録が不当に割れるため。

---

## 更新フロー

```
note-stats-tracker (private)
  └─ note API から収集 → articles.csv ほかを生成
       └─ note-stats-public/data/ へ push
            └─ GitHub Pages が docs/ を配信
                 └─ ダッシュボードが raw.githubusercontent から CSV を fetch
```

### uptime_ranking.csv を日次更新するには

現状 `scripts/build_uptime_ranking.py` はこのリポジトリに置いてあるが、**本来の置き場所は `note-stats-tracker` 側**。
tracker のワークフローで `articles.csv` を生成した**後**に実行し、生成物を他のCSVと同じ経路で配信する。

```yaml
- name: Build uptime ranking
  run: python build_uptime_ranking.py   # data/articles.csv を読み、data/uptime_ranking.csv を書く
```

これを入れるまで `data/uptime_ranking.csv` は手動生成した断面のまま固定される（現在 **2026-10-08** 時点）。

### CSVが無くてもダッシュボードは壊れない

`uptime_ranking.csv` はローダーの `optional` 配列に入れてあるため、取得に失敗しても例外にならず該当パネルが出ないだけ。
ダッシュボードとデータ配信は独立して更新できる。

---

## ローカルでの動かし方

```bash
# 派生CSVの再生成（リポジトリ直下で実行。pandas が必要）
python scripts/build_uptime_ranking.py

# ダッシュボードの確認
python -m http.server 8000 --directory docs
# → http://localhost:8000/index.html
```

ダッシュボードは CSV を GitHub の raw URL から読むため、ローカルで配信しても**表示されるデータは main ブランチの内容**になる。
ローカルのCSVを見たい場合は `CONFIG.dataBase` を `'../data/'` に書き換える。
