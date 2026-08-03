#!/usr/bin/env bash
#
# Nocny `pg_dump` produkcyjnej bazy poza VPS (plan krok 38).
#
# Uruchamiany z HOSTA przez cron (`infra/backup/alphasense-backup.cron`) albo
# ręcznie przez `make backup`. Świadomie NIE jest jobem w APScheduler: worker
# to kontener tego samego stacku, więc awaria, po której backup jest najbardziej
# potrzebny (padnięta aplikacja, wypełniony dysk, zapętlony restart), zabrałaby
# ze sobą także backup. Cron na hoście przeżywa padnięty stack.
#
# Co robi:
#   1. `pg_dump -Fc` z kontenera `postgres` na dysk hosta,
#   2. weryfikuje dump `pg_restore --list` (plik, którego nie da się odczytać,
#      nie jest backupem, a rozmiar > 0 tego nie gwarantuje),
#   3. wysyła do bucketu S3-compatible pod `daily/`, w niedzielę dodatkowo
#      kopiuje serwerowo do `weekly/`,
#   4. przycina retencję: 7 dziennych, 4 tygodniowe (zdalnie) i
#      `BACKUP_KEEP_LOCAL` lokalnie,
#   5. każde niepowodzenie → alert do Sentry + niezerowy kod wyjścia.
#
# Konfiguracja: sekcja „backup" w `.env.prod` (wzorzec w `.env.prod.example`).
# Odtwarzanie i test odtworzenia: `docs/wdrozenie.md` §9, `restore-test.sh`.

set -Eeuo pipefail

# shellcheck source=infra/backup/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

DUMP_PATH=""

on_failure() {
	local code=$1 line=$2

	# Niedokończony dump kasujemy od razu. Zostawiony wyglądałby w katalogu
	# dokładnie jak zdrowy i mógłby zostać wybrany przy odtwarzaniu jako
	# „najnowszy".
	if [[ -n $DUMP_PATH && -e $DUMP_PATH ]]; then
		rm -f "$DUMP_PATH"
		log "Usunięto niedokończony dump $DUMP_PATH."
	fi

	log "Backup przerwany (kod $code, linia $line)."
	sentry_alert error backup-failed \
		"Backup produkcyjny nie powiódł się (kod $code, linia $line w backup.sh)"
	exit "$code"
}

trap 'on_failure $? $LINENO' ERR

main() {
	load_env

	mkdir -p "$BACKUP_DIR"
	# Dump to pełna kopia bazy — hasła (hashe), tokeny odświeżające i pozycje
	# użytkowników. Katalog nie ma prawa być czytelny dla innych kont.
	chmod 700 "$BACKUP_DIR"

	local stamp name
	stamp=$(date -u +%Y%m%dT%H%M%SZ)
	name="alphasense-${stamp}.dump"
	DUMP_PATH="$BACKUP_DIR/$name"

	log "Start. Baza=$POSTGRES_DB, plik=$DUMP_PATH"

	# `-Fc` (custom) zamiast zwykłego SQL-a: format jest SKOMPRESOWANY z
	# definicji (osobny `gzip` byłby podwójną pracą), pozwala na selektywne
	# odtwarzanie i na `pg_restore -j`. `--no-owner`/`--no-privileges`, bo
	# odtwarzamy do bazy, w której rolę tworzy obraz Postgresa z `.env.prod` —
	# nazwa roli po odtworzeniu na nowym VPS-ie nie musi być ta sama.
	#
	# `exec -T` — cron nie ma TTY, bez tego `docker compose exec` odmawia.
	# Przekierowanie do pliku jest na HOŚCIE, więc dump nie zajmuje miejsca
	# wewnątrz kontenera bazy.
	"${COMPOSE[@]}" exec -T postgres \
		pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-privileges \
		>"$DUMP_PATH"

	# Sam plik też, nie tylko katalog: dump niesie hashe haseł, tokeny
	# odświeżające i pozycje użytkowników, a domyślna umask dałaby tu 644.
	chmod 600 "$DUMP_PATH"

	local size
	size=$(stat -c %s "$DUMP_PATH")
	[[ $size -gt 0 ]] || die "pg_dump zwrócił pusty plik"

	# Weryfikacja, że archiwum daje się w ogóle przeczytać. Bez tego backup jest
	# sprawdzony dopiero w dniu, w którym jest potrzebny. `-i` — pg_restore
	# czyta format custom ze standardowego wejścia.
	docker run --rm -i "$BACKUP_POSTGRES_IMAGE" pg_restore --list >/dev/null <"$DUMP_PATH"
	log "Dump gotowy i czytelny ($((size / 1024)) KiB)."

	if s3_enabled; then
		upload_and_prune "$name"
	else
		log "OSTRZEŻENIE: BACKUP_S3_* nieuzupełnione — dump zostaje WYŁĄCZNIE na tym VPS-ie."
		# Fingerprint stały, więc powtarzalny brak konfiguracji to jeden
		# problem z licznikiem, a nie nowe zdarzenie co dobę (ta sama zasada,
		# co przy alertach ingestii w kroku 37). Ostrzeżenie, nie błąd: dump
		# powstał, ale ochrona przed utratą VPS-a nie działa — a cicha wersja
		# tego stanu to dokładnie ten backup, którego nie ma w dniu awarii.
		sentry_alert warning backup-s3-not-configured \
			"Backup produkcyjny działa, ale BACKUP_S3_* są puste — kopia leży tylko na VPS-ie"
	fi

	prune_local

	date -u +%Y-%m-%dT%H:%M:%SZ >"$BACKUP_DIR/last-success"
	log "Gotowe."
}

upload_and_prune() {
	local name=$1
	local daily="${BACKUP_S3_PREFIX}/daily/${name}"

	log "Wysyłka do s3://${BACKUP_S3_BUCKET}/${daily}"
	aws_cli s3 cp "/backup/$name" "s3://${BACKUP_S3_BUCKET}/${daily}" --only-show-errors

	# Niedziela (`%u` = 7) awansuje dzisiejszy dump na kopię tygodniową.
	# Kopia SERWEROWA (`s3 cp` między kluczami) — bucket kopiuje obiekt u
	# siebie, drugiej wysyłki przez łącze VPS-a nie ma.
	if [[ $(date -u +%u) == 7 ]]; then
		local weekly="${BACKUP_S3_PREFIX}/weekly/${name}"
		log "Niedziela — kopia tygodniowa: $weekly"
		aws_cli s3 cp \
			"s3://${BACKUP_S3_BUCKET}/${daily}" \
			"s3://${BACKUP_S3_BUCKET}/${weekly}" --only-show-errors
	fi

	prune_remote "${BACKUP_S3_PREFIX}/daily/" "$BACKUP_RETENTION_DAILY"
	prune_remote "${BACKUP_S3_PREFIX}/weekly/" "$BACKUP_RETENTION_WEEKLY"
}

# Kasuje najstarsze obiekty pod prefiksem, zostawiając `keep` najnowszych.
#
# Retencja liczona po LICZBIE kopii, nie po wieku pliku: przy zatrzymanym
# backupie reguła wiekowa („starsze niż 7 dni") wykasowałaby po tygodniu
# wszystko, łącznie z ostatnią zdrową kopią. Licząc sztuki, zepsuty harmonogram
# co najwyżej zostawia stare dumpy — a to jest ten błąd, który wolimy popełnić.
prune_remote() {
	local prefix=$1 keep=$2
	local keys count key

	mapfile -t keys < <(s3_keys "$prefix")
	count=${#keys[@]}

	if ((count <= keep)); then
		log "Retencja $prefix: $count kopii, limit $keep — nic do usunięcia."
		return
	fi

	log "Retencja $prefix: $count kopii, limit $keep — usuwam $((count - keep)) najstarszych."
	for key in "${keys[@]:0:count-keep}"; do
		aws_cli s3 rm "s3://${BACKUP_S3_BUCKET}/${key}" --only-show-errors
		log "  usunięto $key"
	done
}

prune_local() {
	local files count

	mapfile -t files < <(find "$BACKUP_DIR" -maxdepth 1 -name 'alphasense-*.dump' -printf '%f\n' | sort)
	count=${#files[@]}

	((count > BACKUP_KEEP_LOCAL)) || return 0

	log "Lokalnie: $count dumpów, limit $BACKUP_KEEP_LOCAL — usuwam najstarsze."
	local f
	for f in "${files[@]:0:count-BACKUP_KEEP_LOCAL}"; do
		rm -f "$BACKUP_DIR/$f"
		log "  usunięto $f"
	done
}

main "$@"
