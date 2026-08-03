#!/usr/bin/env bash
#
# Weryfikacja bucketu i klucza aplikacyjnego PRZED pierwszym backupem
# (plan krok 38, `docs/wdrozenie.md` §9.1).
#
# Powód istnienia: `aws s3 ls` sprawdza jedną operację z pięciu, których
# potrzebują `backup.sh` i `restore-test.sh`. Klucz z prawem odczytu, ale bez
# kasowania, przechodzi `s3 ls` i wywala się dopiero przy retencji — czyli
# ósmej nocy, w logu crona, którego nikt nie czyta. Ten skrypt wykonuje pełny
# obieg na obiekcie próbnym i sprząta po sobie.
#
# Sprawdza:
#   1. PutObject   — wysyłka dumpu,
#   2. ListBucket  — retencja i wybór najnowszej kopii przy odtwarzaniu,
#   3. CopyObject  — awans kopii dziennej na tygodniową (kopia SERWEROWA),
#   4. GetObject   — ściągnięcie kopii przez `restore-test.sh`, z porównaniem
#                    treści (kod 0 nie dowodzi, że wróciły te same bajty),
#   5. DeleteObject — retencja 7/4,
#   6. czy bucket nie jest publiczny,
#   7. czy jest reguła cyklu życia (bez niej `s3 rm` tylko UKRYWA plik, stare
#      dumpy zostają i naliczają się do rachunku — retencja jest pozorna).
#
# Bazy danych ani istniejących dumpów NIE dotyka. Można uruchamiać na żywej
# produkcji. Sprząta też wersje i znaczniki ukrycia po własnych obiektach —
# inaczej sam test zostawiałby w buckecie śmieci, o których ostrzega w pkt 7.

set -Eeuo pipefail

# shellcheck source=infra/backup/common.sh
. "$(dirname "${BASH_SOURCE[0]}")/common.sh"

WORK_DIR=""
REMOTE_KEY=""

# Sprzątanie bezwarunkowe: obiekt próbny nie ma prawa przeżyć nieudanego
# przebiegu, bo `restore-test.sh` wybiera „najnowszą kopię" leksykograficznie
# i śmieć pod tym samym prefiksem mógłby zostać wybrany jako dump.
cleanup() {
	if [[ -n $REMOTE_KEY ]]; then
		purge_versions "$REMOTE_KEY" || true
		purge_versions "$REMOTE_KEY.copy" || true
	fi
	[[ -n $WORK_DIR && -d $WORK_DIR ]] && rm -rf "$WORK_DIR"
	return 0
}

# Kasuje WSZYSTKIE wersje i znaczniki ukrycia danego klucza. Zwykłe `s3 rm`
# przy „keep all versions" (domyślka B2) zostawia ukrytą wersję, która dalej
# zajmuje miejsce i psuje wynik pkt 7 przy kolejnym przebiegu.
purge_versions() {
	local key=$1 k v

	while read -r k v; do
		[[ -n $k && $k != None ]] || continue
		aws_cli s3api delete-object \
			--bucket "$BACKUP_S3_BUCKET" --key "$k" --version-id "$v" >/dev/null 2>&1 || true
	done < <(aws_cli s3api list-object-versions \
		--bucket "$BACKUP_S3_BUCKET" --prefix "$key" \
		--query '[Versions[].[Key,VersionId], DeleteMarkers[].[Key,VersionId]][]' \
		--output text 2>/dev/null || true)
}

main() {
	# `load_env` wymaga POSTGRES_USER i POSTGRES_DB, bo `backup.sh` bez nich nie
	# zrobi dumpu. Ten skrypt Postgresa nie dotyka i ma działać na `.env.prod`
	# uzupełnionym najpierw o samą sekcję backupu — a wartości z pliku i tak
	# nadpiszą te zaślepki.
	POSTGRES_USER="${POSTGRES_USER:-nieużywane-w-tym-skrypcie}"
	POSTGRES_DB="${POSTGRES_DB:-nieużywane-w-tym-skrypcie}"

	load_env

	s3_enabled || die "BACKUP_S3_* są puste — nie ma czego sprawdzać (patrz docs/wdrozenie.md §9.1)"

	# Własny katalog roboczy zamiast $BACKUP_DIR: `aws_cli` montuje go jako
	# /backup, a ten skrypt nie ma prawa niczego dołożyć do katalogu z dumpami.
	WORK_DIR=$(mktemp -d)
	trap cleanup EXIT
	BACKUP_DIR="$WORK_DIR"

	local stamp
	stamp=$(date -u +%Y%m%dT%H%M%SZ)
	REMOTE_KEY="${BACKUP_S3_PREFIX}/_check-${stamp}.tmp"
	printf 'alphasense bucket check %s\n' "$stamp" >"$WORK_DIR/probe"

	log "Bucket: $BACKUP_S3_BUCKET  region: ${BACKUP_S3_REGION:-us-east-1}"
	log "Endpoint: $BACKUP_S3_ENDPOINT"

	log "[1/7] zapis (PutObject)"
	aws_cli s3 cp /backup/probe "s3://${BACKUP_S3_BUCKET}/${REMOTE_KEY}" --only-show-errors ||
		die "zapis odrzucony — klucz bez prawa zapisu, zła nazwa bucketu albo endpoint z innego regionu"

	log "[2/7] listowanie (ListBucket)"
	local -a keys
	mapfile -t keys < <(s3_keys "$REMOTE_KEY")
	((${#keys[@]} > 0)) || die "listowanie nie zwróciło właśnie wysłanego obiektu — klucz bez prawa listowania"

	log "[3/7] kopia serwerowa dzienna→tygodniowa (CopyObject)"
	aws_cli s3 cp \
		"s3://${BACKUP_S3_BUCKET}/${REMOTE_KEY}" \
		"s3://${BACKUP_S3_BUCKET}/${REMOTE_KEY}.copy" --only-show-errors ||
		die "kopia serwerowa odrzucona — niedzielny awans kopii do weekly/ by nie zadziałał"

	log "[4/7] odczyt i porównanie treści (GetObject)"
	aws_cli s3 cp "s3://${BACKUP_S3_BUCKET}/${REMOTE_KEY}.copy" /backup/probe.back --only-show-errors ||
		die "odczyt odrzucony — restore-test.sh nie ściągnąłby kopii"
	cmp -s "$WORK_DIR/probe" "$WORK_DIR/probe.back" ||
		die "pobrana treść różni się od wysłanej"

	log "[5/7] kasowanie (DeleteObject)"
	aws_cli s3 rm "s3://${BACKUP_S3_BUCKET}/${REMOTE_KEY}" --only-show-errors ||
		die "kasowanie odrzucone — retencja 7/4 by nie działała, bucket rósłby bez końca"

	# Od tego miejsca tylko ostrzeżenia: to ustawienia bucketu, nie uprawnienia
	# klucza. Backup będzie działał, ale gorzej, niż zakłada runbook.
	local warnings=0

	log "[6/7] czy bucket jest prywatny"
	local code
	code=$(curl -s -o /dev/null -w '%{http_code}' \
		"${BACKUP_S3_ENDPOINT%/}/${BACKUP_S3_BUCKET}/${REMOTE_KEY}.copy" || echo 000)
	if [[ $code == 200 ]]; then
		log "  OSTRZEŻENIE: obiekt czytelny BEZ uwierzytelnienia (HTTP 200) — bucket jest publiczny."
		log "  Dumpy zawierają całą bazę użytkowników. Ustaw bucket jako prywatny."
		warnings=$((warnings + 1))
	else
		log "  OK (HTTP $code bez klucza)"
	fi

	log "[7/7] reguła cyklu życia"
	if aws_cli s3api get-bucket-lifecycle-configuration \
		--bucket "$BACKUP_S3_BUCKET" >/dev/null 2>&1; then
		log "  OK"
	else
		log "  OSTRZEŻENIE: brak reguły cyklu życia. Przy „keep all versions\" kasowanie"
		log "  z retencji tylko UKRYWA plik — stare dumpy zostają i naliczają się do"
		log "  rachunku. B2: Lifecycle Settings → „Keep only the last version of the file\"."
		warnings=$((warnings + 1))
	fi

	if ((warnings > 0)); then
		log "Uprawnienia klucza OK, ale ustawienia bucketu wymagają poprawy ($warnings)."
		return 0
	fi

	log "Gotowe. Klucz i bucket sprawdzone — można uruchomić make backup."
}

main "$@"
