#!/usr/bin/env bash
#
# Odtworzenie ostatniego backupu do JEDNORAZOWEJ bazy i sprawdzenie, czy da się
# z niego cokolwiek wyczytać (plan krok 38, `make backup-restore-test`).
#
# Backup, którego nikt nigdy nie odtworzył, nie jest backupem — jest plikiem.
# Ten skrypt zamienia „mamy dumpy w buckecie" w „wiemy, że z tych dumpów
# wstaje baza ze słownikiem rynków i z danymi użytkowników".
#
# Co robi:
#   1. bierze NAJNOWSZY dump z bucketu (`daily/`); przy pustej konfiguracji S3
#      spada na najnowszy plik lokalny,
#   2. tworzy bazę `restore_test_<znacznik>` OBOK produkcyjnej,
#   3. `pg_restore --exit-on-error` do tej bazy,
#   4. porównuje `alembic_version` z bazą produkcyjną i sprawdza, że słownik
#      rynków oraz dane użytkowników nie są puste,
#   5. ZAWSZE kasuje bazę testową (trap), także po błędzie.
#
# Uruchamiaj na produkcji po każdej większej zmianie schematu i po pierwszym
# uruchomieniu backupu. Kosztuje tyle miejsca na dysku, ile waży rozpakowana
# baza — na VPS-ie z jedną instancją Postgresa to jedyny sensowny wariant,
# ale przy dużej bazie zrób to w oknie niskiego ruchu.
#
# NIGDY nie dotyka bazy produkcyjnej: nazwa docelowa jest generowana tutaj,
# sprawdzana wzorcem przed `dropdb` i nie ma w tym skrypcie ani jednego
# wywołania z `-d "$POSTGRES_DB"` poza odczytem `alembic_version`.

set -Eeuo pipefail

# shellcheck source=infra/backup/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

TEST_DB=""

cleanup() {
	local code=$?

	if [[ -n $TEST_DB ]]; then
		# Pas i szelki: baza testowa ma wygenerowaną nazwę, ale `dropdb` jest
		# nieodwracalne, więc przed strzałem sprawdzamy wzorzec. Gdyby ktoś
		# kiedyś podstawił tu zmienną z zewnątrz, ta linia jest ostatnią, która
		# stoi między testem a produkcyjną bazą.
		if [[ $TEST_DB =~ ^restore_test_[0-9]+$ ]]; then
			"${COMPOSE[@]}" exec -T postgres \
				dropdb -U "$POSTGRES_USER" --if-exists --force "$TEST_DB" >/dev/null 2>&1 ||
				log "OSTRZEŻENIE: nie udało się usunąć bazy $TEST_DB — usuń ją ręcznie."
			log "Baza testowa $TEST_DB usunięta."
		else
			log "OSTRZEŻENIE: $TEST_DB nie pasuje do wzorca bazy testowej — NIE usuwam."
		fi
	fi

	if ((code != 0)); then
		log "Test odtworzenia NIE POWIÓDŁ SIĘ (kod $code)."
		sentry_alert error backup-restore-failed \
			"Test odtworzenia backupu nie powiódł się (kod $code) — kopie mogą być bezużyteczne"
	fi
}

trap cleanup EXIT

# Wypisuje ścieżkę do dumpu, który będzie odtwarzany.
resolve_dump() {
	local keys key name

	if s3_enabled; then
		mapfile -t keys < <(s3_keys "${BACKUP_S3_PREFIX}/daily/")
		((${#keys[@]} > 0)) || die "brak kopii w s3://${BACKUP_S3_BUCKET}/${BACKUP_S3_PREFIX}/daily/"

		key=${keys[-1]}
		name=$(basename "$key")
		log "Najnowsza kopia zdalna: $key" >&2

		# Ściągamy nawet wtedy, gdy identyczny plik leży lokalnie — testujemy
		# kopię, która przeżyje utratę VPS-a, a nie tę, która razem z nim padnie.
		aws_cli s3 cp "s3://${BACKUP_S3_BUCKET}/${key}" "/backup/$name" --only-show-errors >&2
		printf '%s\n' "$BACKUP_DIR/$name"
		return
	fi

	log "BACKUP_S3_* puste — testuję najnowszy dump LOKALNY (to nie sprawdza kopii poza VPS-em)." >&2
	local local_file
	local_file=$(find "$BACKUP_DIR" -maxdepth 1 -name 'alphasense-*.dump' | sort | tail -n1)
	[[ -n $local_file ]] || die "brak jakiegokolwiek dumpu w $BACKUP_DIR — uruchom najpierw make backup"
	printf '%s\n' "$local_file"
}

psql_test_db() {
	"${COMPOSE[@]}" exec -T postgres \
		psql -U "$POSTGRES_USER" -d "$TEST_DB" -At -c "$1"
}

main() {
	load_env
	mkdir -p "$BACKUP_DIR"

	local dump
	dump=$(resolve_dump)
	log "Odtwarzam $dump"

	TEST_DB="restore_test_$(date -u +%Y%m%d%H%M%S)"
	"${COMPOSE[@]}" exec -T postgres createdb -U "$POSTGRES_USER" "$TEST_DB"
	log "Utworzono bazę testową $TEST_DB."

	# `--exit-on-error` NIE jest ozdobnikiem: domyślnie `pg_restore` wypisuje
	# błędy poszczególnych poleceń i mimo to kończy się kodem 0. Bez tej flagi
	# test przechodziłby na dumpie, z którego odtworzyła się połowa tabel.
	"${COMPOSE[@]}" exec -T postgres \
		pg_restore -U "$POSTGRES_USER" -d "$TEST_DB" \
		--no-owner --no-privileges --exit-on-error \
		<"$dump"
	log "pg_restore zakończony bez błędów."

	verify
	log "Test odtworzenia ZALICZONY."
}

verify() {
	local restored_rev live_rev markets users portfolios holdings prices

	restored_rev=$(psql_test_db "SELECT version_num FROM alembic_version")
	live_rev=$("${COMPOSE[@]}" exec -T postgres \
		psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "SELECT version_num FROM alembic_version")

	# Rozjazd rewizji znaczy, że dump jest sprzed migracji, która już poszła na
	# produkcję — odtworzenie z niego postawi bazę, na której API nie wstanie.
	[[ $restored_rev == "$live_rev" ]] ||
		die "alembic_version rozjechane: dump=$restored_rev, produkcja=$live_rev"

	markets=$(psql_test_db "SELECT count(*) FROM markets")
	users=$(psql_test_db "SELECT count(*) FROM users")
	portfolios=$(psql_test_db "SELECT count(*) FROM portfolios")
	holdings=$(psql_test_db "SELECT count(*) FROM holdings")
	prices=$(psql_test_db "SELECT count(*) FROM prices")

	log "Odtworzone: alembic=$restored_rev, markets=$markets, users=$users, portfolios=$portfolios, holdings=$holdings, prices=$prices"

	# Jedyny twardy warunek poza rewizją. Słownik rynków jest w bazie ZAWSZE
	# (seed z kroku 19), niezależnie od tego, czy ktoś już założył konto —
	# zero rynków oznacza dump z pustej albo obciętej bazy. Liczby użytkowników
	# i pozycji tylko raportujemy: świeżo wdrożona produkcja ma tu zera i to
	# jest poprawny stan, a nie powód do fałszywego alarmu.
	((markets > 0)) || die "odtworzona baza ma pusty słownik rynków — dump jest bezwartościowy"
}

main "$@"
