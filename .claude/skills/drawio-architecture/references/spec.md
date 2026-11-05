# Spec reference (advanced)

Read only when SKILL.md is not enough: custom arrow kinds, the long (mapping) form, or adding icons.

## Custom arrow kinds

```yaml
edge_kinds:
  private: {label: プライベートエンドポイント経由}          # rename only
  replication: {label: DB複製, color: "#D83B01", dash: "12 3 2 3", width: 2}   # new kind
```

Fields: `label` (legend text), `color` (#RRGGBB), `dash` (dash pattern "length gap …", omit for solid), `width` (default 2).
A kind must differ from the others in `dash` or `width`, not only in color (black-and-white printing); otherwise a `[BP]` warning appears.

Defaults: `main` blue solid, `private` green long dash, `mgmt` purple short dash, `log` pink dotted, `backup` orange dash-dot, `vpn` teal thick solid.

## Long form (equivalent to the one-line form)

```yaml
groups: [{id: vnet, type: azure.vnet, parent: rg, label: "vnet-prod"}]
nodes:  [{id: agw, icon: azure.application_gateway, at: [1, 0], group: snet-app, label: "App Gateway\n(WAF v2)"}]
edges:  [{from: user, to: agw, label: "HTTPS 443", kind: main, step: 1, desc: "...", both: false}]
legend: true   # default true
```

Both forms can be mixed in one file.

## Adding an icon

Add an entry to `scripts/icons.json` (edit only; do not read the whole file):

```json
"azure.example": {"style": "<draw.io style string>", "w": 48, "h": 48}
```

Get the style string in draw.io: place the icon from the Azure or AWS library, right-click → Edit Style, copy it.
Azure styles contain `image=img/lib/azure2/...svg`; AWS styles contain `shape=mxgraph.aws4....`.
