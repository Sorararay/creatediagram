---
name: drawio-architecture
description: Create, update or review Azure/AWS architecture diagrams as draw.io (.drawio) files, e.g. "構成図を描いて", "draw.ioで図にして", "構成図を直して/レビューして". Uses official icons bundled with draw.io, auto-routed arrows, legend and numbered flows. No network access.
---

# draw.io architecture diagrams

Write a spec file (YAML, or JSON if PyYAML is missing), then run the script to generate the .drawio.
Reply to the user in their language (usually Japanese) and write diagram labels in that language.

**Do not open** `scripts/`, `README.md` or any `.drawio` file. Never hand-write or edit .drawio XML.
Everything you need is on this page; the script's messages tell you what to fix.

`<SKILL>` = this folder (e.g. `.github/skills/drawio-architecture`, `.claude/skills/drawio-architecture`). Use `/` in paths; it also works in PowerShell.
Run `python` (or `python3`); on Windows, if it is missing or opens the Microsoft Store, use `py -3`.

## 1. Decide scope (before drawing)

- Audience and purpose of the diagram. Draw only 1–2 main flows per diagram; split monitoring, ops access, DR etc. into separate diagrams.
- `title`: system + environment + viewpoint (e.g. 〇〇システム 本番環境 ネットワーク構成図).
- Nesting: account/subscription → region → VNet/VPC → subnet. PaaS (Key Vault, Storage, ACR, Log Analytics, S3, CloudWatch…) goes outside VNet/VPC, reached via private/VPC endpoints. Global services (Front Door, Entra ID, CloudFront, Route 53, IAM) go outside regions.

## 2. Find icons

`python <SKILL>/scripts/build_drawio.py --find postgres kubernetes` (English keywords, several at once). Unknown names also get suggestions in error messages. If nothing fits, use `box` (text-only box). Never invent icon names.

Group types: `azure.region|subscription|resource_group|vnet|subnet`, `aws.cloud|account|region|az|vpc|public_subnet|private_subnet|security_group`, `generic.onprem|box`.

## 3. Lay out on a grid

Nodes sit on cells `col,row` (0-based); sizes and spacing are automatic.
1. Columns follow the request flow left→right (user at left, data at right).
2. Put the main flow on one row so its arrows are straight.
3. Monitoring/logs/backup on the bottom row; identity/ops at the edges.
4. One node per cell. A group is the rectangle around its members: never put a non-member node inside that rectangle; sibling groups must not overlap.
5. If a node has 5+ arrows, spread its peers over different rows.

## 4. Write the spec (one line per item)

```yaml
title: Webシステム 本番環境 構成図
groups:  # id | type | parent | label
  - vnet | azure.vnet | - | vnet-prod 10.0.0.0/16
  - snet-app | azure.subnet | vnet | snet-app 10.0.1.0/24
nodes:   # id | icon | col,row | group | label   (\n = line break)
  - user | generic.users | 0,0 | - | 利用者
  - agw | azure.application_gateway | 1,0 | snet-app | App Gateway\n(WAF v2)
  - kv | azure.key_vault | 2,1 | - | Key Vault
edges:   # from > to | label | kind | step | desc   (<> = bidirectional)
  - user > agw | HTTPS 443 | main | 1 | 利用者がHTTPSでアクセス
  - agw > kv | 証明書取得 | private
edge_kinds:  # optional: rename/add kinds
  private: {label: プライベートエンドポイント経由}
```

- Trailing fields may be omitted; `-` means empty. `: ` inside a line is fine; quote the line if it contains ` #` (YAML comment).
- In JSON, use the same lines as strings: `"edges": ["user > agw | HTTPS 443 | main | 1 | 利用者がHTTPSでアクセス"]`.
- Kinds: `main` (default), `private`, `mgmt`, `log`, `backup`, `vpn`. Adding kinds: see `references/spec.md`.
- Arrow direction = who initiates the connection. Do not draw return traffic. Use `<>` only for truly bidirectional links (VPN tunnels).
- Every arrow needs a specific label (protocol/port or purpose). Give the main flow `step` 1, 2, 3… and a one-sentence `desc`.
- Node labels: product/resource name; spell out abbreviations readers may not know.

## 5. Generate (checks run automatically)

`python <SKILL>/scripts/build_drawio.py docs/diagrams/web.yaml -o docs/diagrams/web.drawio`

- `ERROR`: nothing is written. Fix the spec as told.
- `WARN … アイコンかラベルの上を通っています`: move nodes or leave an empty column/row as a corridor.
- `WARN [BP] …`: best-practice violation. Fix as told.
- Repeat until no warnings. If you keep one on purpose, tell the user why.

## 6. Self-review, then report

Check what the script cannot: nothing irrelevant to the purpose is drawn; arrow directions are right; one icon per resource type; abbreviations are understandable. Report the .drawio path and any remaining warnings.

Render a PNG only if warnings remain that you cannot resolve or the user asks (images cost many tokens), with the draw.io desktop CLI: `<drawio> -x -f png -s 1.5 -o web.png web.drawio`, where `<drawio>` is `& "C:\Program Files\draw.io\draw.io.exe"` (Windows), `/Applications/draw.io.app/Contents/MacOS/draw.io` (macOS) or `drawio` (Linux).

## Images for design documents

Split by viewpoint (e.g. ① access & authentication, ② licensing & build) instead of one dense diagram; number the titles ①②. Export with the draw.io CLI above using `-f png -s 2` (Word/Excel) or `-f svg` (scalable).

## Changing an existing diagram

Edit only the affected lines of the spec, then regenerate. Regenerating overwrites manual edits made in draw.io; warn the user first. If only a .drawio exists, recreate its spec from what the user tells you.

## Reviewing a diagram

Read `references/best-practices.md` (only for review requests). Run the script on the spec if there is one and include its `[BP]` warnings.
