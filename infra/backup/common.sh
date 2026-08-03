# shellcheck shell=bash
#
# Wspólna warstwa dla `backup.sh` i `restore-test.sh` (plan krok 38).
# Plik jest SOURCE'OWANY, nie uruchamiany — stąd brak sheldze i `set -e`
# (ustawia je skrypt wołający, żeby nie zmieniać zachowania powłoki komuś,
# kto zechce te funkcje wywołać ręcznie).
#
# Założenie o środowisku: skrypty jadą Z HOSTA (cron), a jedyną twardą
# zależnością jest Docker. `pg_dump`, `pg_restore` i `aws` biorą się z obrazów
# (`postgres:16` — ten sam, co produkcyjna baza, oraz `amazon/aws-cli`), więc
# na VPS-ie nie trzeba nic instalować ani pilnować zgodności wersji klienta
# z serwerem. `pg_dump` starszy niż serwer odmawia pracy, a to jest dokładnie
# ten rodzaj awarii, który wychodzi dopiero przy odtwarzaniu.

# Korzeń repo liczony od położenia TEGO pliku, nie od `pwd` — cron uruchamia
# skrypt z katalogu domowego użytkownika, nie z `/opt/alphasense`.
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
ENV_FILE="${ENV_FILE:-$REPO_ROOT/.env.prod}"

# Ta sama inwokacja, co cele `prod-*` w `Makefile`. `--env-file` NIE jest
# opcjonalny (patrz nagłówek `docker-compose.prod.yml`).
#
# `BACKUP_COMPOSE_FILE` istnieje po to, by dało się przepuścić te skrypty przez
# stack DEV podczas ich weryfikacji (`BACKUP_COMPOSE_FILE=docker-compose.yml
# ENV_FILE=.env ./infra/backup/backup.sh`) — bez tego jedynym środowiskiem, w
# którym da się je sprawdzić, byłaby produkcja. Na VPS-ie zostaw domyślne.
BACKUP_COMPOSE_FILE="${BACKUP_COMPOSE_FILE:-$REPO_ROOT/docker-compose.prod.yml}"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$BACKUP_COMPOSE_FILE")

log() {
	printf '%s [backup] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

die() {
	log "BŁĄD: $*"
	exit 1
}

# Wczytuje `.env.prod` i ustawia wartości domyślne backupu.
#
# `set -a` + `.` zamiast parsowania grepem: plik i tak jest wykonywany przez
# compose'a i Dockera, ma uprawnienia 600 i tego samego właściciela co ten
# skrypt — nie ma tu granicy zaufania do bronienia. Parser napisany ręcznie
# rozjechałby się z compose'em przy pierwszej wartości w cudzysłowie.
load_env() {
	[[ -r $ENV_FILE ]] || die "brak pliku $ENV_FILE (patrz docs/wdrozenie.md §2)"

	set -a
	# shellcheck disable=SC1090
	. "$ENV_FILE"
	set +a

	: "${POSTGRES_USER:?brak POSTGRES_USER w $ENV_FILE}"
	: "${POSTGRES_DB:?brak POSTGRES_DB w $ENV_FILE}"

	# Katalog na dumpy. Domyślnie POZA repo — plik z bazą produkcyjną nie ma
	# prawa wylądować w katalogu, który ktoś kiedyś `git add -A`.
	BACKUP_DIR="${BACKUP_DIR:-/var/backups/alphasense}"
	BACKUP_RETENTION_DAILY="${BACKUP_RETENTION_DAILY:-7}"
	BACKUP_RETENTION_WEEKLY="${BACKUP_RETENTION_WEEKLY:-4}"
	# Ile dumpów zostaje NA VPS-ie. Lokalna kopia jest wygodna (odtworzenie bez
	# ściągania), ale nie jest backupem — leży na tym samym dysku, który może
	# paść razem z bazą.
	BACKUP_KEEP_LOCAL="${BACKUP_KEEP_LOCAL:-2}"
	BACKUP_S3_PREFIX="${BACKUP_S3_PREFIX:-alphasense}"
	# Wersja PRZYPIĘTA, nie `:2` ani `:latest`. `amazon/aws-cli` nie publikuje
	# pływającego tagu `2` (są tylko `latest`, `amd64`, `arm64` i pełne `2.x.y`)
	# — `:2` daje „not found" przy pierwszej wysyłce. A `:latest` w ścieżce
	# backupu oznaczałby, że wydanie u dostawcy obrazu może zepsuć odtwarzanie
	# w dniu, w którym jest ono potrzebne.
	BACKUP_AWSCLI_IMAGE="${BACKUP_AWSCLI_IMAGE:-amazon/aws-cli:2.36.14}"
	BACKUP_POSTGRES_IMAGE="${BACKUP_POSTGRES_IMAGE:-postgres:16}"
}

# Czy wysyłka poza VPS jest w ogóle skonfigurowana.
s3_enabled() {
	[[ -n ${BACKUP_S3_BUCKET:-} &&
		-n ${BACKUP_S3_ENDPOINT:-} &&
		-n ${BACKUP_S3_ACCESS_KEY:-} &&
		-n ${BACKUP_S3_SECRET_KEY:-} ]]
}

# `aws` z obrazu Dockera, z kluczami podanymi przez ŚRODOWISKO, nie argumenty.
#
# `-e NAZWA` (bez `=wartość`) przenosi zmienną z otoczenia procesu `docker` do
# kontenera. Dzięki temu klucz do bucketu nie pojawia się w `ps aux` ani w
# `docker inspect` — a na współdzielonym VPS-ie `ps` widzi każdy użytkownik.
#
# `$BACKUP_DIR` montowany jako `/backup` (zapisywalnie — `restore-test.sh`
# ściąga tu dump). Pliki utworzone przez ten kontener należą do roota; skrypty
# i tak jadą z crona roota, ale warto o tym pamiętać przy ręcznym przebiegu.
aws_cli() {
	AWS_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY" \
		AWS_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_KEY" \
		AWS_DEFAULT_REGION="${BACKUP_S3_REGION:-us-east-1}" \
		docker run --rm \
		-e AWS_ACCESS_KEY_ID \
		-e AWS_SECRET_ACCESS_KEY \
		-e AWS_DEFAULT_REGION \
		-v "$BACKUP_DIR:/backup" \
		"$BACKUP_AWSCLI_IMAGE" \
		--endpoint-url "$BACKUP_S3_ENDPOINT" \
		"$@"
}

# Klucze obiektów pod danym prefiksem, posortowane rosnąco.
#
# Nazwy plików niosą znacznik czasu w ISO 8601 (`...20260803T053000Z.dump`),
# więc porządek leksykograficzny JEST porządkiem chronologicznym — nie
# opieramy się na dacie modyfikacji obiektu w buckecie, która zmienia się przy
# kopiowaniu dzienny→tygodniowy i przy migracji między dostawcami.
s3_keys() {
	local prefix=$1
	aws_cli s3api list-objects-v2 \
		--bucket "$BACKUP_S3_BUCKET" \
		--prefix "$prefix" \
		--query 'Contents[].Key' \
		--output text 2>/dev/null |
		tr '\t' '\n' |
		grep -v '^None$' |
		grep -v '^$' |
		sort || true
}

# Wysyła zdarzenie do Sentry przez CLI aplikacji (`python -m app.cli alert`).
#
# Przez kontener, a nie `curl`-em na API Sentry, z trzech powodów: DSN,
# `environment` i `release` są już skonfigurowane w jednym miejscu
# (`app/core/observability.py`), zdarzenie dostaje ten sam tag `component` co
# reszta backendu, a w bashu nie trzeba parsować DSN-a ani składać koperty.
# `--no-deps`, bo alert musi wyjść RÓWNIEŻ wtedy, gdy Postgres leży — a to
# zwykle właśnie wtedy backup pada.
#
# Twarda zależność: działający Docker. Ta sama, którą ma reszta skryptu (dump
# leci przez `docker compose exec`), więc alert nie jest mniej niezawodny niż
# to, co miałby raportować. Gdy i to zawiedzie, zostaje kod wyjścia i poczta
# od crona — stąd `|| log`, nigdy `|| die`.
sentry_alert() {
	local level=$1 fingerprint=$2 message=$3

	if "${COMPOSE[@]}" run --rm --no-deps -T api \
		python -m app.cli alert \
		--level "$level" \
		--fingerprint "$fingerprint" \
		--message "$message" >&2; then
		# Świadomie „przekazany", nie „wysłany": komenda kończy się zerem także
		# przy pustym `SENTRY_DSN` (to poprawna konfiguracja), więc z kodu
		# wyjścia nie da się orzec, czy zdarzenie poleciało. Który wariant
		# zaszedł, mówi linia wypisana przez `app.cli` bezpośrednio wyżej.
		log "Alert przekazany do app.cli (poziom $level, fingerprint $fingerprint)."
	else
		log "OSTRZEŻENIE: nie udało się wysłać alertu do Sentry — zostaje kod wyjścia i log."
	fi
}
