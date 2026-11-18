# nextcloud-calenai

Nextcloud 35 の公式イメージに [CalenAI](https://github.com/ajctrl/CalenAI/releases) を同梱した linux/amd64 イメージです。

[GitHub Packages で公開イメージとタグ一覧を見る](https://github.com/ajctrl/nextcloud-calenai/pkgs/container/nextcloud-calenai)

```sh
# FPM Alpine
docker pull ghcr.io/ajctrl/nextcloud-calenai:35-fpm-alpine
# FPM (Debian)
docker pull ghcr.io/ajctrl/nextcloud-calenai:35-fpm
# Apache (Debian)
docker pull ghcr.io/ajctrl/nextcloud-calenai:35
```

## ローカルで起動

```sh
git clone https://github.com/ajctrl/nextcloud-calenai.git
cd nextcloud-calenai
docker compose up -d
```

既定は FPM Alpine と Nginx の構成です。Debian FPM を使う場合は起動前に `.env` に `IMAGE_TAG=35-fpm`、Apache を使う場合は `COMPOSE_FILE=compose.apache.yaml` を設定します。Apache 版は単体で HTTP を提供します。

http://localhost:8080 を開き、管理者アカウントを作成します。ローカルで試す場合は SQLite を選べます。セットアップ後、CalenAI を有効にします。

```sh
docker compose exec -u www-data app php occ app:enable calenai
```

管理設定の「AI」でプロバイダーを設定し、ユーザーが書き込めるカレンダーを用意してください。データと設定は Docker の名前付きボリュームに保存されます。

## ビルドと配布

```sh
docker build -t ghcr.io/ajctrl/nextcloud-calenai:35-calenai-1.2.7 .
```

ベースイメージは `--build-arg NEXTCLOUD_VARIANT=fpm` または `--build-arg NEXTCLOUD_VARIANT=apache` で変更できます。既定は `fpm-alpine` です。

GitHub Actions は main へのプッシュ時と毎時17分（UTC）に CalenAI の正式リリース（v1.2.7 以降の vX.Y.Z）を確認し、GHCR に認証してタグとダイジェストを照合して、ビルドまたはタグの更新が必要な組み合わせを、新しいリリースから1回につき最大256件処理します。リリースに添付された tar.gz の SHA-256 を GitHub が提供する値と照合し、初期セットアップ、アプリの有効化、HTTP 応答の確認に成功したイメージを上記の形式のタグで公開します。旧形式のイメージは初回に再ビルドします。検証済みのパッケージ改訂タグ（`-r3`）からバージョン付きタグと追従タグを設定し、不足したタグは次の実行で補います。追従タグの公開直前に最新の正式版を再確認し、過去のジョブを再実行しても旧版への付け替えを防ぎます。Actions の「Publish image」から手動でも実行できます。

## Portainer で更新

スタックの `app.image` に上記のタグを指定します。`35` と `35-apache` は同じ Apache 版を指します。新しい CalenAI が公開されたら、スタックの再デプロイ時にイメージを再取得してください。タグを書き換えずに、同じ Nextcloud 35 系・同じ構成の次の CalenAI に更新できます。起動時に同梱の CalenAI を永続ボリュームへ同期し、必要なデータベース更新を実行します。同期前に、保存済みのアプリまたはデータベースの版が同梱版より新しいことを検出した場合は起動を中止します。

特定の CalenAI に固定する場合は、バージョン付きタグも使えます。たとえば v1.2.7 のタグは Alpine が `35-calenai-1.2.7`、Debian FPM が `35-calenai-1.2.7-fpm`、Apache が `35-calenai-1.2.7-apache` です。Compose では `.env` の `IMAGE_TAG` で指定できます。

Nginx 設定は [Nextcloud Docker の公式 Compose 例](https://github.com/nextcloud/docker/tree/master/.examples/docker-compose/insecure/mariadb/fpm/web) に基づきます。
