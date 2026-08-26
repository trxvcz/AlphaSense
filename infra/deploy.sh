#!/usr/bin/env bash
#
# Wdrożenie produkcyjne wywoływane przez CD (ADR-103).
#
# Ten skrypt jest JEDYNYM poleceniem, które klucz wdrożeniowy z GitHub Actions
# może uruchomić na VPS-ie. Wpis w `~/.ssh/authorized_keys` konta wdrożeniowego:
#
#   restrict,command="/opt/alphasense/Alphasense/infra/deploy.sh" ssh-ed25519 AAAA... deploy@github
#
# `command=` sprawia, że treść polecenia przysłana przez klienta NIE jest
# wykonywana — ląduje w `SSH_ORIGINAL_COMMAND` jako zwykły string, a co z nim
# zrobić, decyduje ten plik. Bez tego klucz w sekretach GitHuba byłby zdalnym
# wykonaniem dowolnego kodu jako root: konto zdolne wołać `docker compose`
# należy do grupy `docker`, a na tej maszynie leży `.env.prod` (SECRET_KEY,
# hasło Postgresa, `GOOGLE_CLIENT_SECRET`, klucz do bucketu z kopiami).
# `restrict` dokłada wyłączenie forwardowania portów, agenta, X11 i PTY.
#
# Wejściem jest DOKŁADNIE jeden argument — pełny SHA commita do wdrożenia.
# Skrypt sam sprawdza, że taki commit jest w `origin/main` i że jest nowszy niż
# wdrożony; nie ufa temu, że wołający przysłał coś sensownego.
#
# Ręcznie (na VPS-ie, jako użytkownik wdrożeniowy):
#   ./infra/deploy.sh 1a2b3c...            # pełny SHA
#   ./infra/deploy.sh "$(git rev-parse origin/main)"
#
# Procedura ręczna bez tego skryptu nadal działa — patrz `docs/wdrozenie.md` §8.

set -Eeuo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

ENV_FILE="$REPO_ROOT/.env.prod"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$REPO_ROOT/docker-compose.prod.yml")

# Ile czekamy, aż kontener `api` zgłosi się jako zdrowy. Healthcheck ma
# `start_period: 20s` i `interval: 15s` × 5 prób, więc 180 s daje zapas na
# migracje i pierwsze połączenie z bazą po `prod-up`.
HEALTH_TIMEOUT_SECONDS="${DEPLOY_HEALTH_TIMEOUT:-180}"

PREVIOUS_SHA=""
ROLLBACK_ARMED=0

log() {
	printf '%s [deploy] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

die() {
	log "BŁĄD: $*"
	exit 1
}

# Alert do Sentry przez CLI aplikacji — ten sam mechanizm i ten sam tag
# `component=infra`, co skrypty backupu (`infra/backup/common.sh`). DSN,
# `environment` i `release` są konfiguracją aplikacji; składanie koperty
# w bashu byłoby drugim, rozjeżdżającym się miejscem z tą wiedzą.
sentry_alert() {
	local level=$1 fingerprint=$2 message=$3

	if "${COMPOSE[@]}" run --rm --no-deps -T api \
		python -m app.cli alert \
		--level "$level" \
		--fingerprint "$fingerprint" \
		--message "$message" >&2; then
		log "Alert przekazany do app.cli (poziom $level, fingerprint $fingerprint)."
	else
		log "OSTRZEŻENIE: nie udało się wysłać alertu — zostaje kod wyjścia i log."
	fi
}

# Wycofanie na poprzedni commit. Uzbrajane dopiero po `git reset --hard`:
# wcześniej nie ma czego cofać, a próba „wycofania" przy błędzie walidacji
# tylko zaciemniłaby log.
#
# `trap ... EXIT`, nie `ERR`: `die` kończy skrypt przez `exit`, którego pułapka
# na `ERR` nie widzi — tak samo jak w `infra/backup/backup.sh`, gdzie ta różnica
# potrafiła zostawić niedokończony plik.
on_exit() {
	local code=$?
	[[ $code -eq 0 ]] && return 0

	if [[ $ROLLBACK_ARMED -eq 1 && -n $PREVIOUS_SHA ]]; then
		log "Wdrożenie nieudane (kod $code) — wracam na $PREVIOUS_SHA."
		if git reset --hard "$PREVIOUS_SHA" >/dev/null &&
			write_app_version "$PREVIOUS_SHA" &&
			make prod-build && make prod-up; then
			log "Wycofano na $PREVIOUS_SHA."
			sentry_alert error deploy-failed \
				"Wdrożenie nie powiodło się (kod $code); produkcja wycofana na $PREVIOUS_SHA"
		else
			# Gorszy z dwóch złych stanów: nie działa ani nowy kod, ani powrót.
			# Poziom `fatal`, bo to wymaga człowieka na maszynie.
			log "WYCOFANIE TAKŻE SIĘ NIE POWIODŁO — produkcja wymaga ręcznej interwencji."
			sentry_alert fatal deploy-rollback-failed \
				"Wdrożenie i wycofanie nie powiodły się; produkcja w stanie nieokreślonym"
		fi
	else
		log "Wdrożenie przerwane (kod $code) przed zmianą kodu produkcji."
	fi

	exit "$code"
}
trap on_exit EXIT

# `APP_VERSION` w `.env.prod` — bez tego `release` w Sentry i pole `version`
# w `/api/health` zostają na `0.1.0` na zawsze, bo CD nie dotyka tego pliku
# w żaden inny sposób. Wtedy nie da się powiedzieć, z którego wdrożenia
# przyszedł błąd ani czy poprawka faktycznie poszła na produkcję.
write_app_version() {
	local sha=$1 short=${1:0:12}

	[[ -w $ENV_FILE ]] || die "brak zapisywalnego $ENV_FILE"

	if grep -q '^APP_VERSION=' "$ENV_FILE"; then
		sed -i "s/^APP_VERSION=.*/APP_VERSION=$short/" "$ENV_FILE"
	else
		printf 'APP_VERSION=%s\n' "$short" >>"$ENV_FILE"
	fi
	log "APP_VERSION=$short (commit $sha)."
}

# Czeka, aż kontener `api` zgłosi się jako `healthy`.
#
# Świadomie NIE `curl --fail` na `/api/health`: ta trasa z założenia zawsze
# oddaje `200`, a o stanie mówi ciało (krok 37), więc kod HTTP przeszedłby
# także przy `db: down`. Healthcheck w `docker-compose.prod.yml` parsuje pole
# `db` — używamy jego werdyktu zamiast pisać drugą, rozjeżdżającą się kopię
# tej samej logiki.
wait_for_healthy_api() {
	local container deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS)) status=""

	container=$("${COMPOSE[@]}" ps -q api) ||
		die "nie udało się odczytać kontenera api"
	# shellcheck disable=SC2016  # w komunikacie są dosłowne odwrotne apostrofy
	[[ -n $container ]] || die 'kontener api nie istnieje po `make prod-up`'

	while ((SECONDS < deadline)); do
		status=$(docker inspect --format '{{.State.Health.Status}}' "$container" 2>/dev/null || echo "brak")
		case "$status" in
		healthy)
			log "API zdrowe (healthcheck widzi bazę)."
			return 0
			;;
		unhealthy)
			# Nie czekamy do końca limitu: healthcheck ma własne `retries`,
			# więc `unhealthy` to już werdykt po kilku próbach.
			"${COMPOSE[@]}" logs --tail 50 api >&2 || true
			die "API zgłasza się jako unhealthy (najczęściej: baza nie odpowiada)"
			;;
		esac
		sleep 5
	done

	"${COMPOSE[@]}" logs --tail 50 api >&2 || true
	die "API nie zgłosiło się jako zdrowe w ciągu ${HEALTH_TIMEOUT_SECONDS}s (ostatni stan: $status)"
}

# --- 1. Wejście: dokładnie jeden pełny SHA -----------------------------------

TARGET_SHA="${1:-${SSH_ORIGINAL_COMMAND:-}}"
# Obcięcie białych znaków: `SSH_ORIGINAL_COMMAND` bywa z końcowym znakiem
# nowej linii, a wtedy poniższe dopasowanie odrzuciłoby poprawny SHA
# komunikatem, który niczego nie tłumaczy.
TARGET_SHA="${TARGET_SHA#"${TARGET_SHA%%[![:space:]]*}"}"
TARGET_SHA="${TARGET_SHA%"${TARGET_SHA##*[![:space:]]}"}"
[[ -n $TARGET_SHA ]] || die "brak SHA commita do wdrożenia"

# Walidacja PRZED jakimkolwiek użyciem: to jedyna wartość, która przychodzi
# z zewnątrz, i jedyne miejsce, gdzie ktoś mógłby próbować dokleić własne
# polecenie. Pełne 40 znaków, nie skrót — skrót bywa niejednoznaczny.
[[ $TARGET_SHA =~ ^[0-9a-f]{40}$ ]] ||
	die "argument nie jest pełnym SHA commita: $(printf '%q' "$TARGET_SHA")"

[[ -r $ENV_FILE ]] || die "brak $ENV_FILE (patrz docs/wdrozenie.md §2)"

# --- 2. Blokada: dwa wdrożenia naraz zostawiłyby repo w stanie pośrednim -----

# Plik blokady w katalogu domowym konta wdrożeniowego, nie w `/tmp`: `/tmp`
# jest zapisywalny dla wszystkich, więc dowolny użytkownik maszyny mógłby
# zająć tę nazwę i zablokować wdrożenia.
DEPLOY_LOCK="${HOME:-$REPO_ROOT}/.alphasense-deploy.lock"

if [[ -z ${DEPLOY_LOCK_HELD:-} ]]; then
	export DEPLOY_LOCK_HELD=1
	exec flock -n "$DEPLOY_LOCK" "$0" "$TARGET_SHA"
fi

log "Wdrażam $TARGET_SHA."

# --- 3. Czy ten commit wolno wdrożyć ----------------------------------------

git fetch --no-tags --quiet origin main
git cat-file -e "${TARGET_SHA}^{commit}" 2>/dev/null ||
	die "commit $TARGET_SHA nie istnieje w origin"

# Musi leżeć na linii `main`. Bez tego dałoby się wdrożyć dowolny commit
# z dowolnej gałęzi albo PR-a, który nigdy nie przeszedł review.
git merge-base --is-ancestor "$TARGET_SHA" origin/main ||
	die "commit $TARGET_SHA nie jest przodkiem origin/main"

PREVIOUS_SHA=$(git rev-parse HEAD)

if [[ $PREVIOUS_SHA == "$TARGET_SHA" ]]; then
	log "Produkcja jest już na $TARGET_SHA — nic do zrobienia."
	exit 0
fi

# I musi być NOWSZY niż wdrożony. Inaczej „Re-run jobs" na przebiegu sprzed
# tygodnia cofnąłby produkcję o kilka commitów — po cichu, z zielonym jobem,
# na bazie, na której nowsze migracje już poszły.
if git merge-base --is-ancestor "$TARGET_SHA" "$PREVIOUS_SHA"; then
	die "commit $TARGET_SHA jest starszy niż wdrożony $PREVIOUS_SHA (ponowne uruchomienie starego przebiegu?); świadome cofnięcie zrób ręcznie wg docs/wdrozenie.md §11"
fi

# --- 4. Podmiana kodu -------------------------------------------------------

# `checkout main` + `reset --hard`, nie `checkout --detach`: repo ma zostać na
# gałęzi, żeby ręczne `git pull` z runbooka §8 nadal działało. `reset --hard`
# kasuje lokalne zmiany w katalogu roboczym — na produkcji ich nie ma i być
# nie powinno, konfiguracja siedzi w `.env.prod` (nietrackowany).
git checkout --quiet main
git reset --hard --quiet "$TARGET_SHA"
ROLLBACK_ARMED=1

write_app_version "$TARGET_SHA"

# --- 5. Budowa i start ------------------------------------------------------

make prod-build
make prod-up # `migrate` wykonuje migracje przed startem API

# Rola aplikacji (krok 44, ADR-002 warstwa 3). Idempotentne `ALTER ROLE`,
# więc leci przy każdym wdrożeniu — pierwsze po migracji `8d1f2a6c40b7`
# nadaje hasło nowo utworzonej roli, kolejne tylko je potwierdzają.
# Bez `DATABASE_URL_APP` w `.env.prod` krok jest pomijany, a API łączy się
# rolą właściciela: aplikacja DZIAŁA, ale RLS jej nie obowiązuje.
if grep -q '^DATABASE_URL_APP=' .env.prod; then
	log "Nadaję hasło roli aplikacji (RLS)."
	make prod-db-roles
else
	log "OSTRZEŻENIE: brak DATABASE_URL_APP w .env.prod — API działa bez RLS (ADR-002 warstwa 3)."
fi

# Seed tylko wtedy, gdy realnie zmienił się słownik rynków. `make prod-seed`
# restartuje workera, a bezwarunkowy restart przy każdym pushu potrafiłby
# trafić w okno ingestii EOD i sam wygenerować alert `failed` z kroku 37.
if ! git diff --quiet "$PREVIOUS_SHA" "$TARGET_SHA" -- backend/app/db/seed.py; then
	log "Zmienił się app/db/seed.py — odświeżam słownik rynków."
	make prod-seed
fi

# --- 6. Weryfikacja ---------------------------------------------------------

wait_for_healthy_api

log "Wdrożono $TARGET_SHA (poprzednio $PREVIOUS_SHA)."
