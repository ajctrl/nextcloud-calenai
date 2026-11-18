# nextcloud-calenai

サポート期間中の Nextcloud の公式イメージに [CalenAI](https://github.com/ajctrl/CalenAI/releases) を同梱した linux/amd64 イメージです。

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

GitHub Packages のタグ一覧から、サポート中のメジャーと使いたい構成のタグを選び、`.env` の `IMAGE_TAG` に指定します。以下は 35 の FPM Alpine を選んだ場合の例です。[公開タグ一覧](https://github.com/ajctrl/nextcloud-calenai/pkgs/container/nextcloud-calenai)

```sh
git clone https://github.com/ajctrl/nextcloud-calenai.git
cd nextcloud-calenai
printf '%s\n' 'IMAGE_TAG=35-fpm-alpine' > .env
docker compose up -d
```

FPM Alpine または Debian FPM の場合は、それぞれ `<メジャー>-fpm-alpine` または `<メジャー>-fpm` を選びます。どちらも Nginx と一緒に起動します。Apache を使う場合は `<メジャー>-apache` を選び、同じ `.env` に `COMPOSE_FILE=compose.apache.yaml` を追加します。Apache 版は単体で HTTP を提供します。

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

GitHub Actions は main へのプッシュ時と毎時17分（UTC）に、[Nextcloud 公式サポート表](https://github.com/nextcloud/server/wiki/Maintenance-and-Release-Schedule) の各メジャーについて、対応する CalenAI の最新正式版を選びます。各構成の linux/amd64 マニフェストに記載された Nextcloud バージョンで互換性を判定します。対応範囲は、SHA-256 を照合したリリースアーカイブ内の `calenai/appinfo/info.xml` の `dependencies/nextcloud` に従います。対応版がないメジャーは次回以降に再確認します。

公式ベースイメージの linux/amd64 ダイジェスト、CalenAI の配布物、またはビルド内容が変わると、該当する構成を再ビルドします。初期セットアップ、アプリ有効化、HTTP 応答を検証してから GHCR に公開します。Nextcloud の更新候補が現在の同梱版より古い場合や、現在の本体バージョンを特定できない場合は、追従タグと CalenAI 固定タグをそれぞれ保持します。追従タグでは、CalenAI のバージョンも同様に確認します。公式表の EOL 欄に移ったメジャーは更新を終了し、追従タグ・バージョン付きタグ・ビルド別タグを削除します。GHCR の削除単位はイメージのバージョンなので、同じダイジェストにサポート中のタグや手動タグがあれば、そのバージョンは保持します。サポート表の取得や検証に失敗した場合は削除を中止します。

## Portainer で更新

スタックの `app.image` に上記のタグを指定します。`35` と `35-apache` は同じ Apache 版を指します。CalenAI やベースイメージの更新を取り込むには、スタックの再デプロイ時にイメージを再取得してください。タグを書き換えずに、同じ Nextcloud 35 系・同じ構成の更新を受け取れます。起動時に同梱の CalenAI を永続ボリュームへ同期し、必要なデータベース更新を実行します。同期前に、保存済みのアプリまたはデータベースの版が同梱版より新しいことを検出した場合は起動を中止します。

次の Nextcloud メジャーに移る前に、稼働中の `app` コンテナのコンソールに `www-data` ユーザーで接続し、保存済みの CalenAI の版を確認します。

```sh
cd /var/www/html
php occ config:app:get calenai installed_version --default-value 0
php -r 'if (is_file("apps/calenai/appinfo/info.xml")) { echo simplexml_load_file("apps/calenai/appinfo/info.xml")->version, PHP_EOL; }'
```

Docker ホストで `<公開タグ>` を移行先のタグに置き換え、そのイメージの同梱版を確認します。このコマンドはスタックのボリュームを接続せずに実行します。

```sh
docker run --rm --pull always --entrypoint php 'ghcr.io/ajctrl/nextcloud-calenai:<公開タグ>' \
  -r 'echo simplexml_load_file("/usr/src/nextcloud/apps/calenai/appinfo/info.xml")->version, PHP_EOL;'
```

移行先の同梱版が、保存済みの版のいずれかより古い場合は、対応する CalenAI が公開されるまで移行を待ちます。両方以上であることを確認してから、ボリュームとデータベースをバックアップし、スタックのタグを次のメジャーに切り替えます。

特定の CalenAI に固定する場合は、バージョン付きタグも使えます。たとえば v1.2.7 のタグは Alpine が `35-calenai-1.2.7`、Debian FPM が `35-calenai-1.2.7-fpm`、Apache が `35-calenai-1.2.7-apache` です。Compose では `.env` の `IMAGE_TAG` で指定できます。

Nginx 設定は [Nextcloud Docker の公式 Compose 例](https://github.com/nextcloud/docker/tree/master/.examples/docker-compose/insecure/mariadb/fpm/web) に基づきます。
