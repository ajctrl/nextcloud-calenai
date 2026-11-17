# nextcloud-alpine

Nextcloud 35 の公式 PHP-FPM Alpine イメージに [CalenAI 1.2.7](https://github.com/ajctrl/CalenAI/releases/tag/v1.2.7) を同梱した linux/amd64 イメージです。

```sh
docker pull ghcr.io/ajctrl/nextcloud-alpine:35-calenai-1.2.7
```

## ローカルで起動

```sh
git clone https://github.com/ajctrl/nextcloud-alpine.git
cd nextcloud-alpine
docker compose up -d
```

http://localhost:8080 を開き、管理者アカウントを作成します。ローカルで試す場合は SQLite を選べます。セットアップ後、CalenAI を有効にします。

```sh
docker compose exec -u www-data app php occ app:enable calenai
```

管理設定の「AI」でプロバイダーを設定し、ユーザーが書き込めるカレンダーを用意してください。データと設定は Docker の名前付きボリュームに保存されます。

## ビルドと配布

```sh
docker build -t ghcr.io/ajctrl/nextcloud-alpine:35-calenai-1.2.7 .
```

リリース時は Dockerfile のリリース URL と SHA-256、Compose のイメージタグを揃え、そのタグを GitHub に push します。GitHub Actions が初期セットアップ、アプリの有効化、HTTP 応答を確認して GHCR に配布します。

Nginx 設定は [Nextcloud Docker の公式 Compose 例](https://github.com/nextcloud/docker/tree/master/.examples/docker-compose/insecure/mariadb/fpm/web) に基づきます。
