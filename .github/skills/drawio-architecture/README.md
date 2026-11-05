# drawio-architecture

Azure・AWS のシステム構成図を draw.io 形式(.drawio)で作成・修正・レビューするための Agent Skill。
GitHub Copilot、Claude Code など、[Agent Skills](https://agentskills.io) に対応したエージェントで使える。

> このファイルは人が読むための説明書。エージェントには読ませない(SKILL.md で「開かない」と指示している)。

## 導入

配布用の zip は、リポジトリ直下で展開するとそのまま GitHub Copilot 用に配置される構成になっている。

```
.mcp.json                               作図指示エージェントが使う MCP サーバの設定
.github/
├─ agents/diagram-planner.agent.md      作図指示エージェント
└─ skills/drawio-architecture/          このスキル
```

個人用(全リポジトリ共通)にする場合や、ほかのエージェントで使う場合は、スキルのフォルダを次の場所にコピーする。

| エージェント | リポジトリ単位 | 全リポジトリ共通(個人) |
|---|---|---|
| GitHub Copilot(VS Code) | `.github/skills/drawio-architecture/` | `~/.copilot/skills/drawio-architecture/` |
| Claude Code | `.claude/skills/drawio-architecture/` | `~/.claude/skills/drawio-architecture/` |
| その他の対応エージェント | `.agents/skills/drawio-architecture/` | `~/.agents/skills/drawio-architecture/` |

Windows の `~` は `%USERPROFILE%` を指す。作図指示エージェントは GitHub Copilot 用で、個人用にする場合は `~/.copilot/agents/` にコピーする。

前提は Python 3.8 以上(標準ライブラリのみで動作)。PyYAML があれば仕様を YAML で書き、なければ JSON で書く。
生成した .drawio は draw.io デスクトップ版でそのまま開いて編集できる。

## フォルダ構成

スキル(`.github/skills/drawio-architecture/`)の中身。作図指示エージェントは `.github/agents/` に別に置く。

```
drawio-architecture/
├─ SKILL.md                 エージェント向けの手順(英語・簡潔)。作図のたびに読まれるのはこれだけ
├─ README.md                このファイル(人向け)
├─ LICENSE                  MIT License
├─ scripts/
│  ├─ build_drawio.py       仕様 → .drawio の生成と検査
│  └─ icons.json            draw.io 同梱アイコンのカタログ(116種)
├─ references/
│  ├─ best-practices.md     構成図のベストプラクティスと出典(レビュー依頼のときだけ読む)
│  └─ spec.md               高度な設定(矢印の種類の追加、長い記法、アイコン追加)
└─ examples/                見本の仕様(Azure: YAML / AWS: JSON)と作図指示書の見本(*.brief.md)
```

## 設計思想

### 1. 「仕様を書く → スクリプトが描く」の2段階に分ける

エージェントには、どのリソースを何列何行に置き、何と何をつなぐかだけを書かせる。座標の計算、枠の大きさ、矢印の経路はスクリプトが受け持つ。

- エージェントに座標や XML を直接扱わせると、矢印がアイコンや他の矢印に重なる、凡例がないといった見づらい図になりやすい。そこで描画は決定的なスクリプトに任せる。
- 矢印は、アイコンとラベルを障害物とみなした経路探索で引く。主要な通信(`main`)を先に引いて直線を確保し、交差は弧(ジャンプ)で示す。
- 矢印のラベルは、アイコン・ノード名・グループ名・他のラベルと重ならない区間と位置を探して置く。隣り合うノードを結ぶ短い矢印は、ラベルが収まるよう列の間隔を自動で広げる。
- 先頭の空の列・行は自動で詰める。途中の空の列・行は矢印の通り道として残す。
- .drawio の XML は手書きさせない。修正も仕様ファイルに対して行い、再生成する。

### 2. 外部に依存しない

- アイコンは draw.io 本体に同梱された Azure / AWS の公式アイコンを名前で参照するだけで、画像はダウンロードしない。名前は draw.io のソースコードと照合済み。
- MCP サーバや外部 API は使わない。
- 例外は作図指示エージェントで、必要なコンポーネントを公式ドキュメントで確認するためだけに、ベンダー公式のドキュメント用 MCP サーバ(と予備の Web)を使う(後述)。スキル(作図)自体は通信しない。
- Python の標準ライブラリだけで動く(YAML のみ PyYAML が必要)。

### 3. Windows・macOS・Linux で動く

- Python 3.8 以上があれば OS を問わず動く。
- Windows 向けに、BOM 付き UTF-8 の仕様ファイルや cp932 のコンソールでも止まらないようにしている。パスは `/` 区切りで PowerShell からそのまま実行でき、`python` がない環境では `py -3` を使うよう SKILL.md で指示している。

### 4. ベストプラクティスに従う

規則とその出典は `references/best-practices.md` にまとめている。主な出典は次の3つ。

- Microsoft「Azure architecture icons」の利用上の注意
- AWS Architecture Icons の利用ガイド(とその解説記事)
- C4 model の記法チェックリスト

規則は2種類に分けて扱っている。

| 種類 | 担保の仕方 | 例 |
|---|---|---|
| 機械的に検査できる規則 | スクリプトが `[BP]` 警告を出し、エージェントが警告ゼロになるまで直す | タイトル・凡例の有無、矢印ラベルの有無/あいまいさ、1枚の情報量、サービスの配置場所の慣習(PaaS は VNet 外など)、処理番号の重複/欠番、白黒で区別できない線種 |
| 判断が必要な規則 | SKILL.md の「範囲を決める」「セルフレビュー」の手順に組み込む | 図の目的と読み手、描く流れの絞り込み、矢印の向き、略語 |

見た目の面では、主要な流れに丸数字の番号を振って図の下に「処理の流れ」を並べる形式(Azure Architecture Center の参考構成図と同じ)を採用している。矢印の種類は、色だけでなく線種と太さでも区別する。

### 5. トークン効率を優先する

エージェントが読む量・書く量・往復回数を減らすことを、機能を足すときの判断基準にしている。

| 方針 | 理由 | 実装 |
|---|---|---|
| 作図のたびに読むのは SKILL.md だけにする | 毎回読む資料は、そのまま毎回のコストになる | 作図に必要な規則は SKILL.md に要約した。best-practices.md はレビュー依頼のときだけ、spec.md は高度な設定のときだけ読む |
| 読まないファイルを明示する | スクリプト本体(約12,000トークン)やアイコンカタログ(約7,500)、生成済み .drawio を誤って開くと、それだけでコストが倍以上になる | SKILL.md で `scripts/`・`README.md`・`.drawio` を開かないよう指示した。生成済みの .drawio は同梱しない |
| 一覧表示ではなく検索させる | アイコンの全件表示は使わない名前まで読ませる | `--find キーワード` で必要な分だけ引く(6件で約30トークン)。未知の名前には候補を示すエラーも出す |
| 検査と生成を1回のコマンドで行う | 往復の回数がそのままコストと待ち時間になる | 生成時に必ず検査が走る。`--check` は人が使う補助 |
| 仕様を1行記法で書かせる | 出力トークンは入力より高コストで、生成も遅い | `from > to \| ラベル \| 種類 \| 番号 \| 説明` のような `\|` 区切りの1行記法を用意した。長い記法も引き続き使える |
| 修正は差分編集させる | ファイル全体の書き直しは、変更のない行まで出力することになる | SKILL.md で「該当行だけを編集して再生成」と指示している |
| 画像の確認は必要なときだけ | 画像の読み込みは1枚で数百〜千トークン以上かかる | PNG での確認は、解消できない警告が残ったときかユーザーが求めたときだけ |
| SKILL.md は英語で書く | 日本語は英語より2〜3倍トークンを使う | SKILL.md は英語。ユーザーへの返答と図のラベルは、ユーザーの言語で出すよう指示している |

効果(概算。日本語1文字≒1トークン、英数字4文字≒1トークンで見積もり):

| | すべての資料を毎回読む場合 | この設計 |
|---|---|---|
| 1回の作図で読む資料 | 約7,500(SKILL.md、best-practices.md、spec.md、見本、アイコン一覧) | 約1,400(SKILL.md、アイコン検索) |
| 見本(Azure)の仕様ファイル | 約680(長い記法) | 約520(1行記法、約24%減) |

## 使い方(人が直接実行する場合)

```powershell
# 生成(検査も同時に行う)
python scripts/build_drawio.py examples/azure-web.yaml -o azure-web.drawio

# 検査だけ
python scripts/build_drawio.py examples/azure-web.yaml --check

# アイコンを探す / すべて表示する
python scripts/build_drawio.py --find postgres kubernetes
python scripts/build_drawio.py --list-icons azure

# draw.io デスクトップ版で PNG に書き出す
& "C:\Program Files\draw.io\draw.io.exe" -x -f png -s 1.5 -o azure-web.png azure-web.drawio   # Windows
/Applications/draw.io.app/Contents/MacOS/draw.io -x -f png -s 1.5 -o azure-web.png azure-web.drawio   # macOS
drawio -x -f png -s 1.5 -o azure-web.png azure-web.drawio   # Linux
```

`--edge-style straight` を付けると、矢印を生成時の経路のまま固定する。既定の `orth` は、draw.io 上でノードを動かしても矢印が直角を保つ。

## 作図指示エージェント(Diagram Planner)

きれいな構成図を作るには、目的・観点・前提・コンポーネント・つながりを先に決めておくことが一番効く。
`.github/agents/diagram-planner.agent.md` は、ユーザーへのヒアリングと公式ドキュメントの確認でこれらを埋め、作図指示書(`docs/diagrams/<テーマ>.brief.md`)を作る GitHub Copilot のカスタムエージェント。

**導入**: 配布用 zip をリポジトリ直下で展開すれば `.github/agents/` に入る。個人用にする場合は `~/.copilot/agents/` にコピーする。

公式ドキュメントの確認には、次の2つの MCP サーバを使う。どちらも認証不要のリモートサーバで、設定はリポジトリ直下の `.mcp.json`(`mcpServers` 形式)にある。

| サーバ名 | 提供元 | エンドポイント |
|---|---|---|
| `microsoft-learn` | Microsoft Learn MCP Server | `https://learn.microsoft.com/api/mcp` |
| `aws-knowledge-mcp` | AWS Knowledge MCP Server | `https://knowledge-mcp.global.api.aws` |

- `.mcp.json` は GitHub Copilot(VS Code)と Claude Code の両方が読む。VS Code ではワークスペースを信頼すると使えるようになる。
- 個人用にする場合は、同じ内容を `~/.copilot/mcp-config.json` に入れる。
- サーバ名を変えたときは、エージェントの `tools` にある `microsoft-learn/*`・`aws-knowledge-mcp/*` も合わせて変える。
- AWS Knowledge MCP Server には利用回数の制限がある(数値は非公開)。

**使い方**
1. チャットのエージェント一覧から **Diagram Planner** を選び、作りたい図のテーマを伝える(例: 「AWSのECSとRDSで動くWebシステムの本番構成図を設計書用に作りたい」)。
2. 不足している情報だけを、既定値の提案付きで質問してくる。分からなければ「おまかせ」でよい。必要なのに挙がっていないコンポーネントは `(提案)` として追加され、推測した内容は「未確定事項・仮定」に分けて書かれる。
3. 指示書を確認して OK を出すと、ファイルに保存される。
4. **この指示書で作図する** ボタンを押すと、通常のエージェントに切り替わり、drawio-architecture スキルで作図する(送信前にプロンプトを編集できる)。

指示書の見本は `examples/webapp-azure.brief.md`。

**設計上の判断**
- エージェントは作図しない。ヒアリングと指示書づくりに専念させ、作図はスキルに任せる(役割を分けると、それぞれの指示が短くなる)。
- 使えるツールは `read`・`search`・`edit`・`todo`・`microsoft-learn/*`・`aws-knowledge-mcp/*`・`web`。対象サービスの前提条件・必要な付随コンポーネント(エンドポイント、ID、ライセンス、シークレット、IAMロールなど)・ポート・上限値を確認するために使う。参照したURLは指示書の「出典」に残る。
- 確認には、まずベンダー公式の MCP サーバを使う。検索対象が最初から公式ドキュメントに限られるのでブログが混ざらず、必要な部分だけが返るのでページ全体を読むよりトークンが少ない。
- `web` は予備。MCP サーバがつながらないとき(社内ネットワークなど)や、Google Cloud など対応する MCP サーバがないときだけ使い、その場合もベンダーの公式ドキュメント(learn.microsoft.com、docs.aws.amazon.com など)だけを読む。
- モデルの知識だけでは、新しい機能や細かい前提を落としやすい(例: License Manager の RDS ライセンスサーバーと GPO の設定は、同時3セッション以上に必須だが見落としやすい)。公式ドキュメントで確認させるのはそのため。
- 外部への通信を避けたい環境では、`tools` から `microsoft-learn/*`・`aws-knowledge-mcp/*`・`web` を外す(`.mcp.json` も置かない)。その場合、確認できなかった項目は「未確定事項」に回される。
- 1枚の図は主要な流れ1〜2本・ノード15個・矢印12本を目安に、観点ごとに分けるよう指示している(スクリプトの警告の上限は25個・20本)。
- 引き継ぎボタン(handoffs)は、VS Code のローカルのエージェントで使える機能。使えない環境では、保存された指示書を添えて「この指示書で作図して」と頼めばよい。

## 設計書に載せる図を作る

設計書には、1枚にすべてを描くのではなく、観点ごとに分けた図(例: ①接続と認証、②ライセンス管理と構築)を載せる。
draw.io デスクトップ版で、Word・Excel 向けには `-f png -s 2`、拡大しても劣化させたくない場合は `-f svg` で書き出す。

## 保守

- **アイコンの追加**: `references/spec.md` の「Adding an icon」の手順で `scripts/icons.json` に追記する。
- **規則の追加**: 機械的に検査できるものは `build_drawio.py` の `lint()` に追加し、判断が必要なものは SKILL.md の手順に1行で追加する。SKILL.md は作図のたびに読まれるので、長くしすぎない。
- **仕様ファイルの管理**: 仕様ファイル(YAML/JSON)を図と一緒にリポジトリで管理する。構成を変えたら、同じ変更で図も更新する。

## ライセンス

[MIT License](LICENSE)

Azure・AWS のアイコン画像はこのリポジトリに含まれていない。生成した .drawio は draw.io 本体に同梱されたアイコンを名前で参照する。
アイコンの利用条件は各社のガイド([Azure](https://learn.microsoft.com/azure/architecture/icons/)、[AWS](https://aws.amazon.com/architecture/icons/))に従うこと。
