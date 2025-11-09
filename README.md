# auto_notification — 高千穂峡予約監視プロトタイプ

これは指定ページの予約状況を取得して、独自UIで表示するための最小プロトタイプです。

目的
- 指定サイト（https://eipro.jp/takachiho1/eventCalendars/index）から週次の予約状況を取得
- 独自UIに表示する（将来的に〇が出たらメール通知を送る仕組みに拡張）

セットアップ（開発環境）
1. 仮想環境作成

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Playwright を使う場合（推奨、JSレンダリング対応）

```bash
pip install playwright
python -m playwright install
```

動かし方

```bash
uvicorn app:app --reload --host 127.0.0.1 --port 8000
# ブラウザで http://127.0.0.1:8000 を開く
```

注意
- サイトはクライアント側でカレンダーを描画する実装のため、単純な requests だけでは情報が取れないケースがあります。
- 本リポジトリはプロトタイプです。Playwright を使う場合はブラウザバイナリをインストールする必要があります。

次のステップ
- 差分検知（◯が出たらメール送信）機能の追加
- UI で通知先メールアドレスを登録できるようにする
# メール送信（SMTP / API）について

このプロジェクトは通知送信に複数の方法をサポートしています。優先順は以下の通りです。

1. SendGrid HTTP API（環境変数 `SENDGRID_API_KEY`）
2. Mailgun HTTP API（環境変数 `MAILGUN_API_KEY` と `MAILGUN_DOMAIN`）
3. SMTP（環境変数 `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`）
4. どれも無い場合は dry-run（`notification.log` に書き出し）

以下に各プロバイダの設定例とテスト方法を示します。

1) SendGrid（推奨）

- 環境変数（bash 例）:

```bash
export SENDGRID_API_KEY="SG.xxxxx..."
export FROM_EMAIL="alerts@example.com"  # 任意
```

- テスト: サーバーを再起動後、以下を実行してください。

```bash
# 起動中のサーバーに対して通知実行（現在週と次週をチェックして通知）
curl 'http://127.0.0.1:8000/api/notify_now'
```

SendGrid は API キーを一度発行すれば使いやすく、配信も安定しています。

2) Mailgun

- 環境変数（bash 例）:

```bash
export MAILGUN_API_KEY="key-xxxxxxxx"
export MAILGUN_DOMAIN="mg.example.com"
export FROM_EMAIL="notify@mg.example.com"
```

- テスト: サーバー再起動後、`/api/notify_now` を呼んでください。

※ Mailgun の無料アカウントでは送信ドメインの検証やサンドボックス制限があるため、ドメイン設定を確認してください。

3) Gmail SMTP（既存の SMTP ロジック）

- Gmail を SMTP で使う場合は通常のパスワードではなく「アプリパスワード」を使う必要があります。
	1) Google アカウントで 2 段階認証（2FA）を有効にする
	2) アプリパスワードを生成する（アプリ: Other 等で名前を付ける）

- 環境変数（bash 例）:

```bash
export SMTP_HOST="smtp.gmail.com"
export SMTP_PORT="587"
export SMTP_USER="your@gmail.com"
export SMTP_PASS="<アプリパスワード>"
export FROM_EMAIL="your@gmail.com"
```

- 再起動後、`/api/notify_now` を呼んでテストしてください。

よくあるエラー
- 535 BadCredentials: Gmail 側で認証が拒否されています。多くはパスワードが間違っているか、アプリパスワードを使っていないことが原因です。
- SendGrid/Mailgun で 4xx/5xx が返る場合は API キー／ドメイン設定を確認してください。詳細は `notification.log` に出力されます。

ログ確認
- 送信の結果やエラーは `notification.log` に追記されます。問題が起きたらまずここを確認してください。

例:

```bash
sed -n '1,200p' notification.log
```

もし README の文面や手順で補足してほしい箇所があれば教えてください。

4) LINE Notify を使う（パスワード不要で比較的簡単）

このアプリケーションでは `line_tokens.txt` に LINE Notify のアクセストークンを1行に1つずつ置くと、そのトークン宛に通知を送信します。ユーザ側は LINE Notify のトークンを発行するだけで、アプリ側にパスワードを入れる必要はありません。

- トークンの取得手順（個人の LINE アカウント向け）:
	1) ブラウザで https://notify-bot.line.me/ にアクセスしてログイン
	2) メニューの「発行」→「アクセストークンを発行する」を選ぶ
	3) トークン名を入力し、通知先（1:1 トーク）を選択して発行
	4) 表示される長いトークン文字列をコピーする（この画面でしか見えません）

- `line_tokens.txt` の配置例（プロジェクトルート）:

```text
# 1行に1つのアクセストークン
YOUR_LINE_NOTIFY_TOKEN_1
# 別のトークン（複数ユーザへ同報したい場合）
YOUR_LINE_NOTIFY_TOKEN_2
```

- テスト方法:
	- トークンを `line_tokens.txt` に保存後、サーバーを再起動してから以下を実行:
		```bash
		curl 'http://127.0.0.1:8000/api/notify_now'
		```
	- 成否は `notification.log` に出力されます。成功時は LINE 側にメッセージが届きます。

注意点:
	- LINE Notify のトークンはユーザ単位（またはグループ）なので、各受信者が自分でトークンを発行してあなたに渡す必要があります。
	- トークンは秘匿情報です。絶対に公開リポジトリにコミットしないでください。

LINE 通知を試してみたい場合、トークンを `line_tokens.txt` に追加してサーバーを再起動したら教えてください。こちらで再テストして送信結果を報告します。
# auto_notification