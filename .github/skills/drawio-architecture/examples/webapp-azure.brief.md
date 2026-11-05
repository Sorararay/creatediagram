# 作図指示書: 社内向けWebアプリ(Azure App Service)

## 目的・読み手
- 目的: 社内向けWebアプリの利用者アクセス経路と、データ・シークレットが閉域で扱われることを示す
- 読み手: 基盤チーム・セキュリティ審査担当 / 掲載先: 基本設計書

## 図の分け方
| No | タイトル | 主要な流れ |
|---|---|---|
| ① | 社内Webアプリ 本番環境 構成図①(利用者アクセスとデータ経路) | 利用者 → Application Gateway → App Service → SQL Database |

## 前提
- クラウド/リージョン/AZ: Azure 東日本リージョン
- 境界: サブスクリプション(sub-app-prod) → リソースグループ(rg-webapp-prod) → VNet(vnet-webapp 10.1.0.0/16) → サブネット(snet-agw: Application Gateway / snet-app: App Service VNet統合の送信用(ノードがないため図には描かない) / snet-pe: プライベートエンドポイント)
- 利用者・接続方式: 社内利用者が社内ネットワークからHTTPSで接続。サインインはEntra ID

## コンポーネント
| 名前 | 種類(サービス) | 配置場所 | 載せる図 | 備考 |
|---|---|---|---|---|
| 社内利用者 | 利用者 | 社内 | ① | |
| Application Gateway(WAF v2) | Application Gateway | snet-agw | ① | |
| App Service | App Service | rg(PaaS) | ① | 受信はプライベートエンドポイント経由。送信はVNet統合(snet-app)経由 |
| PE(App Service) | Private Endpoint | snet-pe | ① | |
| PE(SQL Database) | Private Endpoint | snet-pe | ① | |
| SQL Database | SQL Database | rg(PaaS) | ① | |
| PE(Key Vault) | Private Endpoint | snet-pe | ① | |
| Key Vault | Key Vault | rg(PaaS) | ① | 接続文字列などのシークレット |
| Application Insights | Application Insights | rg | ① | (提案) アプリの監視 |
| Entra ID | Entra ID | グローバル | ① | |

## つながり
| 図 | 番号 | From → To | プロトコル/ポート・目的 | 種類 |
|---|---|---|---|---|
| ① | 1 | 社内利用者 → Application Gateway | HTTPS 443 | main |
| ① | 2 | Application Gateway → PE(App Service) | HTTPS 443 | main |
| ① | 3 | PE(App Service) → App Service | Private Link | main |
| ① | 4 | App Service → PE(SQL Database) | TDS 1433(VNet統合経由) | main |
| ① | 5 | PE(SQL Database) → SQL Database | Private Link | main |
| ① | | App Service → PE(Key Vault) | シークレット取得 HTTPS 443(VNet統合経由) | private |
| ① | | PE(Key Vault) → Key Vault | Private Link | private |
| ① | | App Service → Application Insights | テレメトリ | log |
| ① | | 社内利用者 → Entra ID | サインイン(OIDC) | mgmt |

## 未確定事項・仮定
- 社内ネットワークとAzureの接続方式(VPN/ExpressRoute)は本図の対象外とし、矢印は直接つなぐ
- Application Insights の送信経路(パブリック/AMPLS)は未定
