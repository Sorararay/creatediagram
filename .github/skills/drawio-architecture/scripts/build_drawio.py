#!/usr/bin/env python3
"""構成図の仕様ファイル(YAML/JSON)から draw.io(.drawio)ファイルを生成する。

  python build_drawio.py spec.yaml -o diagram.drawio
  python build_drawio.py spec.yaml --check        # 検査のみ(ファイルは書かない)
  python build_drawio.py --list-icons [azure|aws|generic]

外部への通信は一切行わない。アイコンは draw.io 本体に同梱されている
Azure / AWS の標準アイコンを参照するだけなので、デスクトップ版でそのまま表示できる。
標準ライブラリのみで動作する(YAMLを読む場合だけ PyYAML が必要)。
"""
import argparse
import difflib
import heapq
import html
import json
import os
import sys
import unicodedata
from xml.sax.saxutils import quoteattr

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- 定数
BASE_GAP = 60      # トラック間の通路幅(矢印を通す余白)
PAD = 18           # グループ枠の左右・下の余白
TITLE = 34         # グループ枠の上余白(タイトル用)
OUTER = 40         # 図全体の外周余白
MIN_COL_W = 90
FONT = 12
LANE = 9           # 通路内で矢印を並べる間隔
ICON_MARGIN = 8    # アイコンのまわりに確保する余白

COST_BEND = 30
COST_REUSE = 400       # 既存の矢印と線分が重なる
COST_CROSS = 25        # 既存の矢印と交差する
COST_TOUCH_BEND = 250  # 既存の矢印の曲がり角を通る
COST_TITLE = 600       # グループ名の文字の上を通る
COST_PORT_USED = 220   # 同じ接続点を他の矢印が使っている
COST_PORT_OFFCENTER = 12
COST_HARD = 20000      # 障害物(アイコン/ラベル)を貫通する ※最後の手段

DEFAULT_KINDS = {  # 白黒印刷・色覚多様性に配慮し、色だけでなく線種でも区別できるようにしている
    "main":    {"label": "主要な通信", "color": "#0078D4", "width": 2},
    "private": {"label": "閉域通信", "color": "#107C10", "width": 2, "dash": "10 4"},
    "mgmt":    {"label": "管理アクセス", "color": "#5C2D91", "width": 2, "dash": "5 4"},
    "log":     {"label": "ログ・メトリクス", "color": "#C239B3", "width": 2, "dash": "2 3"},
    "backup":  {"label": "バックアップ・複製", "color": "#D83B01", "width": 2, "dash": "10 3 2 3"},
    "vpn":     {"label": "VPN・専用線", "color": "#008575", "width": 4},
}

# 配置の慣習チェック用(VNet/VPC の中に置かない、リージョンの中に置かないサービス)
AZ_OUTSIDE_VNET = {"front_door", "entra_id", "ad_b2c", "traffic_manager", "dns_zone", "log_analytics", "monitor",
                   "app_insights", "key_vault", "storage_account", "acr", "cosmos_db", "sql_database", "event_grid",
                   "communication_services", "openai", "devops", "data_collection_rule", "recovery_services_vault",
                   "backup_vault", "automation", "ddos_protection", "waf_policy", "firewall_policy", "entra_domain_services"}
AWS_GLOBAL = {"cloudfront", "route53", "iam", "shield"}
AWS_OUTSIDE_VPC = {"s3", "dynamodb", "sqs", "sns", "cloudwatch", "cloudtrail", "ecr", "kms", "secrets_manager", "cognito",
                   "eventbridge", "ses", "guardduty", "security_hub", "backup", "codepipeline", "cloudformation",
                   "api_gateway", "systems_manager", "waf"}
VNET_TYPES = {"azure.vnet", "azure.subnet"}
VPC_TYPES = {"aws.vpc", "aws.public_subnet", "aws.private_subnet", "aws.security_group"}
REGION_TYPES = {"aws.region", "aws.az"} | VPC_TYPES
VAGUE_LABELS = {"通信", "接続", "使用", "利用", "アクセス", "連携", "データ", "uses", "use", "access", "connect", "data"}


def line_style(k):
    dash = k.get("dash") or ("6 4" if k.get("dashed") else None)
    st = f"strokeColor={k['color']};strokeWidth={k.get('width', 2)};"
    return st + (f"dashed=1;dashPattern={dash};" if dash else "dashed=0;")


def step_mark(n):
    return chr(0x2460 + n - 1) if 1 <= n <= 20 else f"({n})"

AZ_GROUP_BASE = ("rounded=0;whiteSpace=wrap;html=1;container=1;collapsible=0;recursiveResize=0;"
                 "pointerEvents=0;verticalAlign=top;align=left;spacingTop=6;fontSize=12;")
AWS_GROUP_BASE = ("sketch=0;outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=12;fontStyle=0;"
                  "container=1;pointerEvents=0;collapsible=0;recursiveResize=0;")
GROUP_TYPES = {
    "azure.region":         {"style": AZ_GROUP_BASE + "fillColor=none;strokeColor=#0078D4;dashed=1;fontColor=#0078D4;fontStyle=1;spacingLeft=10;"},
    "azure.subscription":   {"style": AZ_GROUP_BASE + "fillColor=none;strokeColor=#E8A900;strokeWidth=1.5;fontColor=#1F1F1F;fontStyle=1;spacingLeft=34;",
                             "icon": "img/lib/azure2/general/Subscriptions.svg"},
    "azure.resource_group": {"style": AZ_GROUP_BASE + "fillColor=none;strokeColor=#737373;dashed=1;fontColor=#1F1F1F;fontStyle=1;spacingLeft=34;",
                             "icon": "img/lib/azure2/general/Resource_Groups.svg"},
    "azure.vnet":           {"style": AZ_GROUP_BASE + "fillColor=#F2F8FD;strokeColor=#0078D4;strokeWidth=1.5;fontColor=#0F548C;fontStyle=1;spacingLeft=34;",
                             "icon": "img/lib/azure2/networking/Virtual_Networks.svg"},
    "azure.subnet":         {"style": AZ_GROUP_BASE + "fillColor=#FFFFFF;strokeColor=#6CB8F6;dashed=1;fontColor=#0F548C;fontStyle=0;spacingLeft=34;",
                             "icon": "img/lib/azure2/networking/Subnet.svg"},
    "aws.cloud":            {"style": AWS_GROUP_BASE + "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_aws_cloud_alt;strokeColor=#232F3E;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#232F3E;dashed=0;"},
    "aws.account":          {"style": AWS_GROUP_BASE + "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_account;strokeColor=#CD2264;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#CD2264;dashed=0;"},
    "aws.region":           {"style": AWS_GROUP_BASE + "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_region;strokeColor=#00A4A6;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#147EBA;dashed=1;"},
    "aws.az":               {"style": "fillColor=none;strokeColor=#147EBA;dashed=1;verticalAlign=top;fontStyle=0;fontColor=#147EBA;whiteSpace=wrap;html=1;container=1;collapsible=0;recursiveResize=0;pointerEvents=0;"},
    "aws.vpc":              {"style": AWS_GROUP_BASE + "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_vpc2;strokeColor=#8C4FFF;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#8C4FFF;dashed=0;"},
    "aws.public_subnet":    {"style": AWS_GROUP_BASE + "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_security_group;grStroke=0;strokeColor=#7AA116;fillColor=#F2F6E8;verticalAlign=top;align=left;spacingLeft=30;fontColor=#248814;dashed=0;"},
    "aws.private_subnet":   {"style": AWS_GROUP_BASE + "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_security_group;grStroke=0;strokeColor=#00A4A6;fillColor=#E6F6F7;verticalAlign=top;align=left;spacingLeft=30;fontColor=#147EBA;dashed=0;"},
    "aws.security_group":   {"style": "fillColor=none;strokeColor=#DD3522;verticalAlign=top;fontStyle=0;fontColor=#DD3522;whiteSpace=wrap;html=1;container=1;collapsible=0;recursiveResize=0;pointerEvents=0;"},
    "generic.onprem":       {"style": AWS_GROUP_BASE + "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_corporate_data_center;strokeColor=#7D8998;fillColor=none;verticalAlign=top;align=left;spacingLeft=30;fontColor=#5A6C86;dashed=0;"},
    "generic.box":          {"style": AZ_GROUP_BASE + "fillColor=none;strokeColor=#8A8886;dashed=1;fontColor=#3B3A39;fontStyle=1;spacingLeft=10;"},
}

BOX_STYLE = ("rounded=1;arcSize=10;whiteSpace=wrap;html=1;fillColor=#FFFFFF;strokeColor=#8A8886;"
             "fontColor=#1F1F1F;fontSize=12;align=center;verticalAlign=middle;")


# ---------------------------------------------------------------- 文字幅の見積もり
def text_width(s, size=FONT):
    w = 0.0
    for ch in s:
        w += size * (1.0 if unicodedata.east_asian_width(ch) in "WF" else 0.6)
    return w


def label_lines(label):
    return str(label).split("\n") if label else []


def html_label(label):
    return "<br>".join(html.escape(line) for line in label_lines(label))


# ---------------------------------------------------------------- 入力
class SpecError(Exception):
    pass


def load_spec(path):
    # Windowsのエディタが付けるBOMにも対応する
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    if path.lower().endswith(".json"):
        return json.loads(text)
    try:
        import yaml  # noqa
    except ImportError:
        sys.exit("YAMLを読むには PyYAML が必要です(pip install pyyaml)。入手できない場合は仕様をJSONで書いてください。")
    return yaml.safe_load(text)


def load_icons():
    with open(os.path.join(HERE, "icons.json"), encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- 幾何
def hits_interior(seg, rect):
    """軸に平行な線分 seg((x1,y1),(x2,y2)) が矩形の内部を通るか(辺上はセーフ)。"""
    (x1, y1), (x2, y2) = seg
    rx1, ry1, rx2, ry2 = rect
    if x1 == x2:
        lo, hi = sorted((y1, y2))
        return rx1 < x1 < rx2 and lo < ry2 and hi > ry1
    lo, hi = sorted((x1, x2))
    return ry1 < y1 < ry2 and lo < rx2 and hi > rx1


def expand(rect, m):
    return (rect[0] - m, rect[1] - m, rect[2] + m, rect[3] + m)


# ---------------------------------------------------------------- 1行記法
# 仕様を書く(=出力する)トークンを減らすため、各要素を「|」区切りの1行でも書けるようにしている。
#   group: "id | type | parent | label"
#   node : "id | icon | 列,行 | group | label"        (label 内の \n は改行)
#   edge : "from > to | label | kind | step | desc"   (「<>」で両方向)
# 後ろの項目は省略でき、空欄または「-」は未指定扱い。

def _fields(text, n):
    parts = [p.strip() for p in str(text).split("|")]
    parts += [""] * (n - len(parts))
    head, rest = parts[:n - 1], parts[n - 1:]
    last = " | ".join(p for p in rest if p) if len(parts) > n else rest[0]
    return [None if v in ("", "-") else v for v in head + [last]]


def _label(v):
    return v.replace("\\n", "\n") if isinstance(v, str) else v


def _unsplit(item):
    """YAMLで「: 」を含む1行記法が {"前半": "後半"} と解釈された場合に、元の1行へ戻す。"""
    if isinstance(item, dict) and len(item) == 1:
        (k, v), = item.items()
        if isinstance(k, str) and "|" in k and not isinstance(v, (dict, list)):
            return f"{k}: {'' if v is None else v}"
    return item


def normalize(spec, errors):
    spec = dict(spec or {})
    for key in ("groups", "nodes", "edges"):
        spec[key] = [_unsplit(x) for x in (spec.get(key) or [])]
    groups = []
    for g in spec.get("groups") or []:
        if isinstance(g, str):
            gid, gtype, parent, label = _fields(g, 4)
            g = {"id": gid, "type": gtype or "generic.box", "parent": parent}
            if label:
                g["label"] = _label(label)
        groups.append(g)
    nodes = []
    for n in spec.get("nodes") or []:
        if isinstance(n, str):
            nid, icon, pos, grp, label = _fields(n, 5)
            try:
                at = [int(v) for v in (pos or "").split(",")]
            except ValueError:
                at = None
            n = {"id": nid, "icon": icon or "box", "at": at, "group": grp}
            if label:
                n["label"] = _label(label)
        nodes.append(n)
    edges = []
    for i, e in enumerate(spec.get("edges") or []):
        if isinstance(e, str):
            ends, label, kind, step, desc = _fields(e, 5)
            both = "<>" in (ends or "")
            pair = [v.strip() for v in (ends or "").replace("<>", ">").split(">")]
            if len(pair) != 2 or not all(pair):
                errors.append(f"edges[{i}]: 「from > to | ラベル | kind | step | 説明」の形式で書いてください: {e}")
                continue
            e = {"from": pair[0], "to": pair[1], "both": both}
            if label:
                e["label"] = _label(label)
            if kind:
                e["kind"] = kind
            if step:
                e["step"] = int(step) if step.isdigit() else step
            if desc:
                e["desc"] = desc
        edges.append(e)
    spec.update(groups=groups, nodes=nodes, edges=edges)
    return spec


# ---------------------------------------------------------------- 本体
class Diagram:
    def __init__(self, spec, icons):
        self.errors = []
        self.warnings = []
        self.spec = normalize(spec, self.errors)
        self.icons = icons

    # ---------- 検証と前処理
    def prepare(self):
        sp = self.spec
        self.title = sp.get("title")
        self.kinds = dict(DEFAULT_KINDS)
        for k, v in (sp.get("edge_kinds") or {}).items():
            base = dict(self.kinds.get(k, {}))
            base.update(v or {})
            if "color" not in base:
                self.errors.append(f"edge_kinds.{k}: color を指定してください")
            self.kinds[k] = base

        self.groups = {}
        for g in sp.get("groups") or []:
            gid = g.get("id")
            if not gid:
                self.errors.append(f"groups: id がないグループがあります: {g}")
                continue
            if gid in self.groups:
                self.errors.append(f"グループIDが重複しています: {gid}")
            gtype = g.get("type", "generic.box")
            if gtype not in GROUP_TYPES:
                sug = difflib.get_close_matches(gtype, GROUP_TYPES.keys(), n=3)
                self.errors.append(f"グループ {gid}: 未知の type '{gtype}'" + (f"(候補: {', '.join(sug)})" if sug else ""))
                gtype = "generic.box"
            self.groups[gid] = {"id": gid, "type": gtype, "label": g.get("label", gid), "parent": g.get("parent")}
        for g in self.groups.values():
            if g["parent"] and g["parent"] not in self.groups:
                self.errors.append(f"グループ {g['id']}: parent '{g['parent']}' が存在しません")
                g["parent"] = None
        for g in self.groups.values():  # 循環チェック
            seen, cur = set(), g
            while cur["parent"]:
                if cur["id"] in seen:
                    self.errors.append(f"グループの親子関係が循環しています: {g['id']}")
                    g["parent"] = None
                    break
                seen.add(cur["id"])
                cur = self.groups[cur["parent"]]

        self.nodes = {}
        cells = {}
        for n in sp.get("nodes") or []:
            nid = n.get("id")
            if not nid:
                self.errors.append(f"nodes: id がないノードがあります: {n}")
                continue
            if nid in self.nodes or nid in self.groups:
                self.errors.append(f"IDが重複しています: {nid}")
            at = n.get("at")
            if not (isinstance(at, (list, tuple)) and len(at) == 2 and all(isinstance(v, int) and v >= 0 for v in at)):
                self.errors.append(f"ノード {nid}: at は [列, 行] の0以上の整数で指定してください(現在: {at})")
                continue
            icon = n.get("icon", "box")
            if icon != "box" and icon not in self.icons:
                sug = difflib.get_close_matches(icon, self.icons.keys(), n=3, cutoff=0.5)
                self.errors.append(f"ノード {nid}: 未知のアイコン '{icon}'" + (f"(候補: {', '.join(sug)})" if sug else "(--list-icons で一覧表示、なければ icon: box)"))
                icon = "box"
            grp = n.get("group")
            if grp and grp not in self.groups:
                self.errors.append(f"ノード {nid}: group '{grp}' が存在しません")
                grp = None
            label = n.get("label", nid)
            key = tuple(at)
            if key in cells:
                self.errors.append(f"ノード {nid} と {cells[key]} が同じ位置 {list(at)} にあります")
            cells[key] = nid
            for line in label_lines(label):
                if text_width(line) > 170:
                    self.warnings.append(f"ノード {nid}: ラベルの1行が長いです「{line}」(\\n で改行すると見やすくなります)")
            self.nodes[nid] = {"id": nid, "icon": icon, "label": label, "col": at[0], "row": at[1], "group": grp}

        self.edges = []
        for i, e in enumerate(sp.get("edges") or []):
            s, t = e.get("from"), e.get("to")
            ok = True
            for end in (s, t):
                if end not in self.nodes:
                    self.errors.append(f"edges[{i}]: ノード '{end}' が存在しません" + (" (グループには矢印をつなげません。代表ノードにつないでください)" if end in self.groups else ""))
                    ok = False
            if ok and s == t:
                self.errors.append(f"edges[{i}]: from と to が同じです({s})")
                ok = False
            kind = e.get("kind", "main")
            if kind not in self.kinds:
                self.errors.append(f"edges[{i}]: 未知の kind '{kind}'(edge_kinds に定義してください)")
                kind = "main"
            if ok:
                step = e.get("step")
                if step is not None and not (isinstance(step, int) and step >= 1):
                    self.errors.append(f"edges[{i}]: step は1以上の整数で指定してください")
                    step = None
                self.edges.append({"idx": i, "from": s, "to": t, "kind": kind, "label": e.get("label", ""),
                                   "both": bool(e.get("both", False)), "step": step, "desc": e.get("desc", "")})
        if not self.nodes:
            self.errors.append("nodes が空です")
        if self.errors:
            return
        # 先頭の空の列・行は余白になるだけなので詰める(途中の空の列・行は矢印の通り道として残す)
        c0 = min(n["col"] for n in self.nodes.values())
        r0 = min(n["row"] for n in self.nodes.values())
        for n in self.nodes.values():
            n["col"] -= c0
            n["row"] -= r0
        self._check_groups()

    def ancestors(self, gid):
        out = []
        while gid:
            out.append(gid)
            gid = self.groups[gid]["parent"]
        return out

    def depth(self, gid):
        return len(self.ancestors(gid))

    def _check_groups(self):
        # 各グループの範囲(子孫ノードの外接セル範囲)
        for g in self.groups.values():
            g["members"] = [n for n in self.nodes.values() if n["group"] and g["id"] in self.ancestors(n["group"])]
            if not g["members"]:
                self.errors.append(f"グループ {g['id']}: 所属ノードがありません(空のグループは描けません)")
                continue
            g["c0"] = min(n["col"] for n in g["members"])
            g["c1"] = max(n["col"] for n in g["members"])
            g["r0"] = min(n["row"] for n in g["members"])
            g["r1"] = max(n["row"] for n in g["members"])
        if self.errors:
            return
        for n in self.nodes.values():
            anc = set(self.ancestors(n["group"])) if n["group"] else set()
            for g in self.groups.values():
                if g["c0"] <= n["col"] <= g["c1"] and g["r0"] <= n["row"] <= g["r1"] and g["id"] not in anc:
                    self.errors.append(
                        f"ノード {n['id']} [{n['col']},{n['row']}] がグループ {g['id']} の範囲"
                        f" 列{g['c0']}-{g['c1']}×行{g['r0']}-{g['r1']} の中にありますが所属していません。"
                        f"ノードを範囲外へ動かすか group: {g['id']} 配下にしてください")
        gl = list(self.groups.values())
        for i, a in enumerate(gl):
            for b in gl[i + 1:]:
                if a["id"] in self.ancestors(b["id"]) or b["id"] in self.ancestors(a["id"]):
                    continue
                if a["c0"] <= b["c1"] and b["c0"] <= a["c1"] and a["r0"] <= b["r1"] and b["r0"] <= a["r1"]:
                    self.errors.append(f"グループ {a['id']} と {b['id']} の範囲が重なっています。どちらかのノードの列/行をずらしてください")

    # ---------- レイアウト
    def layout(self):
        ncol = max(n["col"] for n in self.nodes.values()) + 1
        nrow = max(n["row"] for n in self.nodes.values()) + 1

        for n in self.nodes.values():
            lines = label_lines(n["label"])
            if n["icon"] == "box":
                n["w"] = max(110, max((text_width(l) for l in lines), default=0) + 24)
                n["h"] = max(48, len(lines) * 16 + 18)
                n["lw"] = n["lh"] = 0
            else:
                ic = self.icons[n["icon"]]
                n["w"], n["h"] = ic["w"], ic["h"]
                n["lw"] = max((text_width(l) for l in lines), default=0) + 8
                n["lh"] = len(lines) * 15 + 4 if lines else 0

        col_w = [MIN_COL_W] * ncol
        row_top = [0] * nrow     # アイコン中心より上に必要な高さ
        row_bot = [0] * nrow     # アイコン中心より下に必要な高さ(ラベル込み)
        for n in self.nodes.values():
            col_w[n["col"]] = max(col_w[n["col"]], n["w"] + 16, n["lw"] + 16)
            row_top[n["row"]] = max(row_top[n["row"]], n["h"] / 2 + 4)
            row_bot[n["row"]] = max(row_bot[n["row"]], n["h"] / 2 + (n["lh"] + 6 if n["lh"] else 0) + 4)
        for r in range(nrow):
            if row_top[r] == 0:
                row_top[r] = row_bot[r] = 20

        groups = list(self.groups.values())

        def stack(axis_lo, axis_hi, other_lo, other_hi, idx, which, n_other):
            """track idx の端に積み重なるグループ枠の段数(他軸方向の最大値)。"""
            best = 0
            for o in range(n_other):
                cnt = sum(1 for g in groups
                          if g[which[0]] == idx and g[other_lo] <= o <= g[other_hi])
                best = max(best, cnt)
            return best

        def col_start(c):
            return stack("c0", "c1", "r0", "r1", c, ("c0",), nrow)

        def col_end(c):
            return stack("c0", "c1", "r0", "r1", c, ("c1",), nrow)

        def row_start(r):
            return stack("r0", "r1", "c0", "c1", r, ("r0",), ncol)

        def row_end(r):
            return stack("r0", "r1", "c0", "c1", r, ("r1",), ncol)

        label_gap = {}  # 列c と c+1 の間に必要なラベル幅(左ノード幅, 右ノード幅, 必要長)
        for e in self.edges:
            a, b = self.nodes[e["from"]], self.nodes[e["to"]]
            if a["row"] == b["row"] and abs(a["col"] - b["col"]) == 1 and self.edge_text(e):
                l, r = (a, b) if a["col"] < b["col"] else (b, a)
                need = text_width(self.edge_text(e), 11) + 36
                cur = label_gap.get(l["col"])
                if not cur or cur[2] < need:
                    label_gap[l["col"]] = (l["w"], r["w"], need)

        for _ in range(6):  # グループ名が枠に収まるまで列幅を広げる
            top_offset = OUTER + (44 if self.title else 0)
            self.col_x = []
            x = OUTER + PAD * col_start(0)
            for c in range(ncol):
                self.col_x.append(x)
                x += col_w[c]
                if c < ncol - 1:
                    gap = BASE_GAP + PAD * col_end(c) + PAD * col_start(c + 1)
                    if c in label_gap:
                        wl, wr, need = label_gap[c]
                        seg = gap + (col_w[c] - wl) / 2 + (col_w[c + 1] - wr) / 2
                        gap += max(0, need - seg)
                    x += gap
            self.col_w = col_w
            self.row_y = []
            y = top_offset + TITLE * row_start(0)
            for r in range(nrow):
                self.row_y.append(y)
                y += row_top[r] + row_bot[r]
                if r < nrow - 1:
                    y += BASE_GAP + PAD * row_end(r) + TITLE * row_start(r + 1)
            self.row_h = [row_top[r] + row_bot[r] for r in range(nrow)]
            self.row_cy = [self.row_y[r] + row_top[r] for r in range(nrow)]

            for n in self.nodes.values():
                cx = self.col_x[n["col"]] + col_w[n["col"]] / 2
                cy = self.row_cy[n["row"]]
                n["cx"], n["cy"] = cx, cy
                n["x"], n["y"] = cx - n["w"] / 2, cy - n["h"] / 2
                n["rect"] = (n["x"], n["y"], n["x"] + n["w"], n["y"] + n["h"])
                if n["lh"]:
                    ly = n["y"] + n["h"] + 2
                    n["lrect"] = (cx - n["lw"] / 2, ly, cx + n["lw"] / 2, ly + n["lh"])
                else:
                    n["lrect"] = None

            # グループ枠: 子から順に外接矩形を作る
            order = sorted(groups, key=lambda g: -self.depth(g["id"]))
            for g in order:
                xs1, ys1, xs2, ys2 = [], [], [], []
                for n in g["members"]:
                    if n["group"] == g["id"]:
                        c, r = n["col"], n["row"]
                        xs1.append(self.col_x[c]); xs2.append(self.col_x[c] + col_w[c])
                        ys1.append(self.row_y[r]); ys2.append(self.row_y[r] + self.row_h[r])
                for ch in groups:
                    if ch["parent"] == g["id"]:
                        xs1.append(ch["rect"][0]); ys1.append(ch["rect"][1])
                        xs2.append(ch["rect"][2]); ys2.append(ch["rect"][3])
                g["rect"] = (min(xs1) - PAD, min(ys1) - TITLE, max(xs2) + PAD, max(ys2) + PAD)
                tw = text_width(str(g["label"])) + 40
                g["trect"] = (g["rect"][0], g["rect"][1], g["rect"][0] + tw, g["rect"][1] + 28)
            widened = False
            for g in groups:
                need = (g["trect"][2] - g["trect"][0]) - (g["rect"][2] - g["rect"][0])
                if need > 0:
                    col_w[g["c1"]] += need
                    widened = True
            if not widened:
                break

        all_rects = [n["rect"] for n in self.nodes.values()] + [n["lrect"] for n in self.nodes.values() if n["lrect"]] \
            + [g["rect"] for g in groups]
        self.width = max(r[2] for r in all_rects) + OUTER
        self.height = max(r[3] for r in all_rects) + OUTER

    # ---------- 配線
    def _corridors(self, lo, hi, borders):
        pts = sorted({lo, hi} | {b for b in borders if lo < b < hi})
        out = []
        for a, b in zip(pts, pts[1:]):
            if b - a >= 10:
                m = (a + b) / 2
                out.append(m)
                k = 1
                while (b - a) / 2 - k * LANE >= 6:
                    out += [m - k * LANE, m + k * LANE]
                    k += 1
        return out

    def build_grid(self):
        xs, ys = set(), set()
        for n in self.nodes.values():
            x1, y1, x2, y2 = n["rect"]
            xs |= {n["cx"], n["cx"] - n["w"] / 4, n["cx"] + n["w"] / 4, x1, x2}
            ys |= {n["cy"], n["cy"] - n["h"] / 4, n["cy"] + n["h"] / 4, y1, y2}
        vb = [g["rect"][0] for g in self.groups.values()] + [g["rect"][2] for g in self.groups.values()]
        hb = [g["rect"][1] for g in self.groups.values()] + [g["rect"][3] for g in self.groups.values()] \
            + [g["trect"][3] for g in self.groups.values()]
        ncol, nrow = len(self.col_x), len(self.row_y)
        edges_x = [0] + [v for c in range(ncol) for v in (self.col_x[c], self.col_x[c] + self.col_w[c])] + [self.width]
        for a, b in zip(edges_x[0::2], edges_x[1::2]):
            xs |= set(self._corridors(a, b, vb))
        edges_y = [0] + [v for r in range(nrow) for v in (self.row_y[r], self.row_y[r] + self.row_h[r])] + [self.height]
        for a, b in zip(edges_y[0::2], edges_y[1::2]):
            ys |= set(self._corridors(a, b, hb))
        # セル内でアイコンの横を通る線(ラベル下)
        for r in range(nrow):
            ys.add(self.row_y[r] + self.row_h[r] - 2)
        self.xs = sorted(xs)
        self.ys = sorted(ys)
        self.xi = {v: i for i, v in enumerate(self.xs)}
        self.yi = {v: i for i, v in enumerate(self.ys)}

        # 線分ごとの障害物を事前計算
        self.seg_info = {}
        nodes = list(self.nodes.values())
        titles = [g["trect"] for g in self.groups.values()]
        for i in range(len(self.xs)):
            for j in range(len(self.ys)):
                for di, dj in ((1, 0), (0, 1)):
                    i2, j2 = i + di, j + dj
                    if i2 >= len(self.xs) or j2 >= len(self.ys):
                        continue
                    seg = ((self.xs[i], self.ys[j]), (self.xs[i2], self.ys[j2]))
                    exp_hit, exact_hit, label_hit = [], [], 0
                    for n in nodes:
                        if hits_interior(seg, expand(n["rect"], ICON_MARGIN)):
                            exp_hit.append(n["id"])
                            if hits_interior(seg, n["rect"]):
                                exact_hit.append(n["id"])
                        if n["lrect"] and hits_interior(seg, expand(n["lrect"], 2)):
                            label_hit += 1
                    title_hit = sum(1 for t in titles if hits_interior(seg, t))
                    self.seg_info[(i, j, i2, j2)] = (exp_hit, exact_hit, label_hit, title_hit)

    DIRS = {"R": (1, 0), "L": (-1, 0), "D": (0, 1), "U": (0, -1)}
    OPP = {"R": "L", "L": "R", "U": "D", "D": "U"}

    def ports(self, n):
        """(x, y, 外向き方向, 接続位置の相対座標, コスト)"""
        out = []
        fr = [(0.5, 0)] if n["icon"] == "box" and False else [(0.5, 0), (0.25, COST_PORT_OFFCENTER), (0.75, COST_PORT_OFFCENTER)]
        x1, y1, x2, y2 = n["rect"]
        for f, c in fr:
            y = y1 + n["h"] * f
            out.append((x1, y, "L", (0, f), c))
            out.append((x2, y, "R", (1, f), c))
            x = x1 + n["w"] * f
            out.append((x, y1, "U", (f, 0), c))
            if not n["lrect"]:
                out.append((x, y2, "D", (f, 1), c))
        return [p for p in out if p[0] in self.xi and p[1] in self.yi]

    def seg_cost(self, i, j, i2, j2, src, dst):
        key = (min(i, i2), min(j, j2), max(i, i2), max(j, j2))
        exp_hit, exact_hit, label_hit, title_hit = self.seg_info[key]
        cost = 0
        hard = False
        for nid in exp_hit:
            if nid in (src, dst):
                if nid in exact_hit:
                    hard = True
            else:
                hard = True
        if label_hit:
            hard = True
        if hard:
            cost += COST_HARD
        cost += COST_TITLE * title_hit
        orient = "h" if j == j2 else "v"
        if (key, orient) in self.used_seg:
            cost += COST_REUSE * self.used_seg[(key, orient)]
        p = (i2, j2)
        if p in self.used_pt:
            ors = self.used_pt[p]
            if "bend" in ors:
                cost += COST_TOUCH_BEND
            elif (orient == "h" and "v" in ors) or (orient == "v" and "h" in ors):
                cost += COST_CROSS
        return cost, hard

    def route(self, e):
        s, t = self.nodes[e["from"]], self.nodes[e["to"]]
        heap = []
        best = {}
        counter = 0
        tports = {}
        for (x, y, d, rel, c) in self.ports(t):
            pen = c + (COST_PORT_USED if (t["id"], rel) in self.used_port else 0)
            tports[(self.xi[x], self.yi[y], self.OPP[d])] = (pen, rel)
        for (x, y, d, rel, c) in self.ports(s):
            pen = c + (COST_PORT_USED if (s["id"], rel) in self.used_port else 0)
            st = (self.xi[x], self.yi[y], d)
            heapq.heappush(heap, (pen, counter, st, None, rel, False))
            counter += 1
        prev = {}
        start_rel = {}
        found = None
        nx, ny = len(self.xs), len(self.ys)
        while heap:
            cost, _, st, parent, rel, hard = heapq.heappop(heap)
            if st in best:
                continue
            best[st] = cost
            prev[st] = parent
            if parent is None:
                start_rel[st] = rel
            if st in tports and parent is not None:
                found = (st, hard)
                break
            i, j, d = st
            for nd in (d, *(("U", "D") if d in "LR" else ("L", "R"))):
                di, dj = self.DIRS[nd]
                i2, j2 = i + di, j + dj
                if not (0 <= i2 < nx and 0 <= j2 < ny):
                    continue
                nst = (i2, j2, nd)
                if nst in best:
                    continue
                sc, h = self.seg_cost(i, j, i2, j2, s["id"], t["id"])
                step = abs(self.xs[i2] - self.xs[i]) + abs(self.ys[j2] - self.ys[j])
                add = step + sc + (COST_BEND if nd != d else 0)
                if nst in tports:
                    add += tports[nst][0]
                heapq.heappush(heap, (cost + add, counter, nst, st, rel, hard or h))
                counter += 1
        if not found:
            return None
        st, _ = found
        path = []
        cur = st
        while cur is not None:
            path.append(cur)
            first = cur
            cur = prev[cur]
        path.reverse()
        pts = [(self.xs[p[0]], self.ys[p[1]]) for p in path]
        # 経路上の障害物貫通を再判定
        hard = any(self.seg_cost(a[0], a[1], b[0], b[1], s["id"], t["id"])[1] for a, b in zip(path, path[1:]))
        return {"pts": pts, "grid": path, "src_rel": start_rel[first], "dst_rel": tports[st][1], "hard": hard}

    @staticmethod
    def simplify(pts):
        out = [pts[0]]
        for p in pts[1:]:
            if len(out) >= 2:
                a, b = out[-2], out[-1]
                if (a[0] == b[0] == p[0]) or (a[1] == b[1] == p[1]):
                    out[-1] = p
                    continue
            if p != out[-1]:
                out.append(p)
        return out

    def edge_text(self, e):
        text = str(e["label"] or "")
        if e["step"]:
            text = step_mark(e["step"]) + (" " + text if text else "")
        return text

    def place_labels(self):
        """矢印ラベルを、アイコン・ノード名・グループ名・他のラベルと重ならない位置に置く。"""
        def overlap(a, b):
            return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

        blocks = [expand(n["rect"], 3) for n in self.nodes.values()] \
            + [expand(n["lrect"], 2) for n in self.nodes.values() if n["lrect"]] \
            + [g["trect"] for g in self.groups.values()]
        all_segs = []
        for e in self.edges:
            r = e.get("route")
            if r:
                pts = self.simplify(r["pts"])
                e["_pts"] = pts
                all_segs += [(e["idx"], a, b) for a, b in zip(pts, pts[1:])]
        placed = []
        for e in sorted(self.edges, key=lambda e: (e["step"] is None, e["step"] or 0, e["idx"])):
            text = self.edge_text(e)
            e["label_x"] = 0
            if not text or not e.get("_pts"):
                continue
            pts = e["_pts"]
            w, h = text_width(text, 11) + 8, 16
            segs = list(zip(pts, pts[1:]))
            lens = [abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in segs]
            total = sum(lens) or 1
            best = None
            for i, (a, b) in enumerate(segs):
                for rank, f in enumerate((0.5, 0.35, 0.65, 0.2, 0.8)):
                    cx, cy = a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f
                    rect = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
                    hard = sum(1 for bl in blocks + placed if overlap(rect, bl))
                    soft = sum(1 for idx, p, q in all_segs if idx != e["idx"] and hits_interior((p, q), rect))
                    score = hard * 1000 + soft * 40 + rank * 3 - lens[i] / 50
                    if best is None or score < best[0]:
                        best = (score, hard, rect, sum(lens[:i]) + lens[i] * f)
            _, hard, rect, dist = best
            e["label_x"] = round(dist / total * 2 - 1, 3)
            placed.append(rect)
            if hard:
                self.warnings.append(f"矢印 {e['from']}→{e['to']} のラベル「{text}」が他の要素と重なっています。"
                                     "ラベルを短くするか、ノードの間に空の列/行を入れてください")

    def route_all(self):
        self.build_grid()
        self.used_seg, self.used_pt, self.used_port = {}, {}, set()
        # 主要な通信(main)を先に引いて直線を優先的に確保し、その後は短い矢印から引く
        order = sorted(self.edges, key=lambda e: (e["kind"] != "main",) + (abs(self.nodes[e["from"]]["cx"] - self.nodes[e["to"]]["cx"])
                       + abs(self.nodes[e["from"]]["cy"] - self.nodes[e["to"]]["cy"]),))
        for e in order:
            r = self.route(e)
            if r is None:
                self.warnings.append(f"矢印 {e['from']}→{e['to']}: 経路が見つかりませんでした(draw.io の自動配線に任せます)")
                e["route"] = None
                continue
            e["route"] = r
            if r["hard"]:
                self.warnings.append(f"矢印 {e['from']}→{e['to']}: アイコンかラベルの上を通っています。"
                                     f"ノードの列/行をずらして通り道を空けてください")
            g = r["grid"]
            for a, b in zip(g, g[1:]):
                key = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
                orient = "h" if a[1] == b[1] else "v"
                self.used_seg[(key, orient)] = self.used_seg.get((key, orient), 0) + 1
                self.used_pt.setdefault((b[0], b[1]), set()).add(orient)
                self.used_pt.setdefault((a[0], a[1]), set()).add(orient)
            for a, b in zip(g, g[1:]):
                if a[2] != b[2]:
                    self.used_pt.setdefault((a[0], a[1]), set()).add("bend")
            self.used_port.add((e["from"], r["src_rel"]))
            self.used_port.add((e["to"], r["dst_rel"]))
        # 重なりの最終チェック
        for (key, orient), cnt in self.used_seg.items():
            if cnt > 1:
                self.warnings.append("一部の矢印どうしが同じ線上で重なっています。ノード配置の見直しを検討してください")
                break

    @staticmethod
    def _plain(label):
        return " ".join(label_lines(label))

    def lint(self):
        """構成図のベストプラクティスに沿っているかを検査し、警告として返す。"""
        w = self.warnings
        if not self.title:
            w.append("[BP] title がありません。「システム名 + 環境 + 図の観点」(例: 〇〇システム 本番環境 ネットワーク構成図)を付けてください")
        if len(self.nodes) > 25 or len(self.edges) > 20:
            w.append(f"[BP] ノード{len(self.nodes)}個・矢印{len(self.edges)}本は1枚には多すぎます。"
                     "全体図と、ネットワーク・監視・運用などの観点別の図に分けてください(1枚に描く流れは1〜2本が目安)")
        no_label = [f"{e['from']}→{e['to']}" for e in self.edges if not str(e["label"]).strip() and not e["desc"]]
        if no_label:
            w.append("[BP] ラベルのない矢印があります(プロトコル/ポートや目的を書く): " + ", ".join(no_label))
        vague = [f"{e['from']}→{e['to']}「{e['label']}」" for e in self.edges
                 if str(e["label"]).strip().lower() in VAGUE_LABELS]
        if vague:
            w.append("[BP] 矢印のラベルがあいまいです(「HTTPS 443」「ログ転送」など具体的に): " + ", ".join(vague))
        nolab = [n["id"] for n in self.nodes.values() if n["label"] == n["id"] and n["icon"] != "box"]
        if nolab:
            w.append("[BP] label が未指定のノードがあります(アイコンの近くにサービス名・リソース名を書く): " + ", ".join(nolab))
        steps = [e["step"] for e in self.edges if e["step"]]
        if steps:
            dup = sorted({s for s in steps if steps.count(s) > 1})
            gaps = sorted(set(range(1, max(steps) + 1)) - set(steps))
            if dup:
                w.append(f"[BP] step 番号が重複しています: {dup}")
            if gaps:
                w.append(f"[BP] step 番号が飛んでいます: {gaps}")
        # 白黒でも区別できるか
        used = sorted({e["kind"] for e in self.edges})
        seen = {}
        for k in used:
            kk = self.kinds[k]
            sig = (kk.get("dash") or ("6 4" if kk.get("dashed") else ""), kk.get("width", 2))
            if sig in seen:
                w.append(f"[BP] 矢印の種類 {seen[sig]} と {k} が線種・太さで区別できません(白黒印刷で見分けられない)。"
                         "edge_kinds で dash か width を変えてください")
            seen.setdefault(sig, k)
        # 配置の慣習
        has_aws = any(n["icon"].startswith("aws.") for n in self.nodes.values())
        if has_aws and not any(g["type"] in ("aws.account", "aws.cloud") for g in self.groups.values()):
            w.append("[BP] AWS のアカウント境界(aws.account または aws.cloud のグループ)を描いてください")
        icons_used = {n["icon"] for n in self.nodes.values()}
        if "aws.nat_gateway" in icons_used and "aws.internet_gateway" not in icons_used:
            w.append("[BP] NAT Gateway からインターネットへ出るには Internet Gateway が必要です。"
                     "VPC 内(サブネットの外)に aws.internet_gateway を置き、NAT Gateway → Internet Gateway の経路を描いてください")
        for n in self.nodes.values():
            types = {self.groups[g]["type"] for g in self.ancestors(n["group"])} if n["group"] else set()
            svc = n["icon"].split(".", 1)[-1]
            if n["icon"].startswith("azure.") and svc in AZ_OUTSIDE_VNET and types & VNET_TYPES:
                w.append(f"[BP] {n['id']}({n['icon']}) は VNet の外に置くサービスです。VNet/サブネットの外に移し、"
                         "閉域接続はサブネット内のプライベートエンドポイント(azure.private_endpoint)で表してください")
            if n["icon"].startswith("aws."):
                if svc in AWS_GLOBAL and types & REGION_TYPES:
                    w.append(f"[BP] {n['id']}({n['icon']}) はグローバルサービスです。リージョン/VPC の外(アカウント内)に置いてください")
                elif svc in AWS_OUTSIDE_VPC and types & VPC_TYPES:
                    w.append(f"[BP] {n['id']}({n['icon']}) は VPC の外(リージョン内)に置くサービスです。"
                             "VPC からの閉域接続は VPC エンドポイント(aws.vpc_endpoint)で表してください")

    # ---------- XML出力
    def to_xml(self, edge_style="orth"):
        cells = ['<mxCell id="0" />', '<mxCell id="1" parent="0" />']
        uid = [0]

        def nid():
            uid[0] += 1
            return f"c{uid[0]}"

        def geom(x, y, w, h):
            return f'<mxGeometry x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" as="geometry" />'

        if self.title:
            cells.append(f'<mxCell id="title" value={quoteattr(html_label(self.title))} '
                         f'style="text;html=1;fontSize=18;fontStyle=1;align=left;verticalAlign=middle;" vertex="1" parent="1">'
                         f'{geom(OUTER, OUTER - 6, max(300, text_width(str(self.title), 18) + 20), 32)}</mxCell>')

        cell_id = {}
        origin = {}
        for g in sorted(self.groups.values(), key=lambda g: self.depth(g["id"])):
            gid = "g_" + g["id"]
            cell_id[g["id"]] = gid
            parent = cell_id[g["parent"]] if g["parent"] else "1"
            ox, oy = origin.get(g["parent"], (0, 0))
            x1, y1, x2, y2 = g["rect"]
            gt = GROUP_TYPES[g["type"]]
            cells.append(f'<mxCell id={quoteattr(gid)} value={quoteattr(html_label(g["label"]))} style={quoteattr(gt["style"])} '
                         f'vertex="1" parent={quoteattr(parent)}>{geom(x1 - ox, y1 - oy, x2 - x1, y2 - y1)}</mxCell>')
            origin[g["id"]] = (x1, y1)
            if gt.get("icon"):
                st = f"image;aspect=fixed;html=1;points=[];image={gt['icon']};"
                cells.append(f'<mxCell id={quoteattr(gid + "_icon")} value="" style={quoteattr(st)} vertex="1" connectable="0" '
                             f'parent={quoteattr(gid)}>{geom(7, 5, 22, 22)}</mxCell>')

        for n in self.nodes.values():
            parent = cell_id[n["group"]] if n["group"] else "1"
            ox, oy = origin.get(n["group"], (0, 0))
            style = BOX_STYLE if n["icon"] == "box" else self.icons[n["icon"]]["style"]
            cells.append(f'<mxCell id={quoteattr(n["id"])} value={quoteattr(html_label(n["label"]))} style={quoteattr(style)} '
                         f'vertex="1" parent={quoteattr(parent)}>{geom(n["x"] - ox, n["y"] - oy, n["w"], n["h"])}</mxCell>')

        for e in self.edges:
            k = self.kinds[e["kind"]]
            base = ("edgeStyle=orthogonalEdgeStyle;" if edge_style == "orth" else "edgeStyle=none;") + \
                   "rounded=1;arcSize=6;html=1;jumpStyle=arc;jumpSize=8;fontSize=11;labelBackgroundColor=#FFFFFF;" \
                   f"endArrow=block;endFill=1;fontColor={k['color']};" + line_style(k)
            if e["both"]:
                base += "startArrow=block;startFill=1;"
            r = e.get("route")
            pts_xml = ""
            label_x = 0
            if r:
                sx, sy = r["src_rel"]
                tx, ty = r["dst_rel"]
                base += (f"exitX={sx};exitY={sy};exitDx=0;exitDy=0;exitPerimeter=0;"
                         f"entryX={tx};entryY={ty};entryDx=0;entryDy=0;entryPerimeter=0;")
                pts = self.simplify(r["pts"])
                inner = pts[1:-1]
                if inner:
                    pts_xml = '<Array as="points">' + "".join(f'<mxPoint x="{x:.1f}" y="{y:.1f}" />' for x, y in inner) + "</Array>"
                label_x = e.get("label_x", 0)
            eid = f"e{e['idx']}"
            text = self.edge_text(e)
            if e["step"]:
                base += "fontStyle=1;"
            cells.append(f'<mxCell id={quoteattr(eid)} value={quoteattr(html_label(text))} style={quoteattr(base)} '
                         f'edge="1" parent="1" source={quoteattr(e["from"])} target={quoteattr(e["to"])}>'
                         f'<mxGeometry x="{label_x}" relative="1" as="geometry">{pts_xml}</mxGeometry></mxCell>')

        # 凡例
        used = []
        for e in self.edges:
            if e["kind"] not in used:
                used.append(e["kind"])
        if self.spec.get("legend", True) and used:
            lx, ly = OUTER, self.height - OUTER + 30
            rows = len(used)
            lw = max(text_width(str(self.kinds[k].get("label", k))) for k in used) + 110
            lh = 40 + rows * 26
            cells.append(f'<mxCell id="legend" value="凡例" style="rounded=0;whiteSpace=wrap;html=1;container=1;collapsible=0;'
                         f'recursiveResize=0;fillColor=#FAFAFA;strokeColor=#BDBDBD;verticalAlign=top;align=left;spacingLeft=10;'
                         f'spacingTop=4;fontStyle=1;fontSize=12;" vertex="1" parent="1">{geom(lx, ly, lw, lh)}</mxCell>')
            for i, k in enumerate(used):
                kk = self.kinds[k]
                yy = 40 + i * 26
                st = "endArrow=block;endFill=1;html=1;" + line_style(kk)
                cells.append(f'<mxCell id="legend_e{i}" value="" style={quoteattr(st)} edge="1" parent="legend">'
                             f'<mxGeometry relative="1" as="geometry"><mxPoint x="12" y="{yy}" as="sourcePoint" />'
                             f'<mxPoint x="70" y="{yy}" as="targetPoint" /></mxGeometry></mxCell>')
                cells.append(f'<mxCell id="legend_t{i}" value={quoteattr(html_label(kk.get("label", k)))} '
                             f'style="text;html=1;align=left;verticalAlign=middle;fontSize=12;" vertex="1" parent="legend">'
                             f'{geom(80, yy - 11, lw - 86, 22)}</mxCell>')
            self.height = ly + lh + OUTER
            steps = sorted((e for e in self.edges if e["step"]), key=lambda e: e["step"])
            if steps:
                px = lx + lw + 30
                lines = []
                for e in steps:
                    desc = e["desc"] or (f"{self._plain(self.nodes[e['from']]['label'])} → "
                                         f"{self._plain(self.nodes[e['to']]['label'])}"
                                         + (f"({self._plain(e['label'])})" if e["label"] else ""))
                    lines.append(f"{step_mark(e['step'])} {self._plain(desc)}")
                pw = max(text_width(t) for t in lines) + 30
                ph = 40 + len(lines) * 22
                cells.append(f'<mxCell id="steps" value="処理の流れ" style="rounded=0;whiteSpace=wrap;html=1;container=1;'
                             f'collapsible=0;recursiveResize=0;fillColor=#FAFAFA;strokeColor=#BDBDBD;verticalAlign=top;'
                             f'align=left;spacingLeft=10;spacingTop=4;fontStyle=1;fontSize=12;" vertex="1" parent="1">'
                             f'{geom(px, ly, pw, ph)}</mxCell>')
                for i, t in enumerate(lines):
                    cells.append(f'<mxCell id="steps_t{i}" value={quoteattr(html.escape(t))} '
                                 f'style="text;html=1;align=left;verticalAlign=middle;fontSize=12;" vertex="1" parent="steps">'
                                 f'{geom(12, 30 + i * 22, pw - 18, 22)}</mxCell>')
                self.height = max(self.height, ly + ph + OUTER)

        body = "\n        ".join(cells)
        return (f'<mxfile host="drawio-architecture-skill">\n'
                f'  <diagram id="arch" name={quoteattr(str(self.title or "構成図"))}>\n'
                f'    <mxGraphModel dx="{int(self.width)}" dy="{int(self.height)}" grid="1" gridSize="10" guides="1" tooltips="1" '
                f'connect="1" arrows="1" fold="1" page="0" pageScale="1" pageWidth="{int(self.width)}" pageHeight="{int(self.height)}" '
                f'math="0" shadow="0">\n      <root>\n        {body}\n      </root>\n    </mxGraphModel>\n  </diagram>\n</mxfile>\n')


def main():
    # Windowsのコンソール(cp932など)でも文字化けや例外で止まらないようにする
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="構成図仕様(YAML/JSON) → draw.io")
    ap.add_argument("spec", nargs="?")
    ap.add_argument("-o", "--output")
    ap.add_argument("--check", action="store_true", help="検査だけ行い、ファイルは書かない")
    ap.add_argument("--find", nargs="+", metavar="KEYWORD",
                    help="アイコン名・グループtypeをキーワードで検索(例: --find postgres kubernetes)")
    ap.add_argument("--list-icons", nargs="?", const="", metavar="PREFIX", help="使えるアイコン名をすべて表示(人が確認する用)")
    ap.add_argument("--edge-style", choices=["orth", "straight"], default="orth",
                    help="orth: draw.ioで動かしても直角を保つ(既定) / straight: 生成時の経路を厳密に固定")
    a = ap.parse_args()

    icons = load_icons()
    if a.find:
        hay = {}
        for k, v in icons.items():
            st = v["style"]
            extra = ""
            for key in ("image=", "resIcon=", "shape="):
                if key in st:
                    val = st.split(key, 1)[1].split(";", 1)[0]
                    extra += " " + (val.rsplit("/", 1)[-1][:-4] if val.endswith(".svg") else val.rsplit(".", 1)[-1])
            hay[k] = (k + extra).lower().replace("_", " ")
        for k in GROUP_TYPES:
            hay["group " + k] = k.lower().replace("_", " ")
        kws = [w.lower().replace("_", " ") for w in a.find]
        hits = [k for k, h in hay.items() if any(w in h for w in kws)]
        print("\n".join(hits) if hits else "該当なし(別の英単語で検索するか icon: box を使う)")
        return
    if a.list_icons is not None:
        for k in sorted(icons):
            if k.startswith(a.list_icons):
                print(k)
        print("\n[グループ type]")
        for k in GROUP_TYPES:
            if k.startswith(a.list_icons):
                print(k)
        print("\n(icon: box で文字だけの四角も使えます)")
        return
    if not a.spec:
        ap.error("spec を指定してください")

    d = Diagram(load_spec(a.spec), icons)
    d.prepare()
    if not d.errors:
        d.layout()
        d.route_all()
        d.place_labels()
        d.lint()
    for m in d.errors:
        print("ERROR:", m)
    for m in dict.fromkeys(d.warnings):
        print("WARN :", m)
    if d.errors:
        print(f"\n{len(d.errors)}件のエラーがあるため出力しませんでした。")
        sys.exit(1)
    if a.check:
        print("OK(検査のみ)" if not d.warnings else "\n警告を確認してください(検査のみ)")
        return
    out = a.output or os.path.splitext(a.spec)[0] + ".drawio"
    xml = d.to_xml(a.edge_style)
    with open(out, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"{'OK' if not d.warnings else '警告あり'}: {out} を出力しました(ノード{len(d.nodes)} / グループ{len(d.groups)} / 矢印{len(d.edges)})")


if __name__ == "__main__":
    main()
