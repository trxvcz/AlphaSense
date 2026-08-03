# Wdrożenie produkcyjne (runbook)

Plan krok 36. Dotyczy pojedynczego VPS-a z Dockerem, na którym stoi cały stack:
Caddy (TLS), frontend, API, worker, Postgres, Redis.

**Zasada nadrzędna:** wszystkie polecenia produkcyjne uruchamiasz przez cele `prod-*`
z `Makefile`, nigdy gołym `docker compose -f docker-compose.prod.yml`. Cele mają zaszyte
`--env-file .env.prod` i bez niego konfiguracja cicho rozjeżdża się z tym, czego oczekujesz
(szczegóły w nagłówku `docker-compose.prod.yml`).

---

## 0. Czego potrzebujesz przed startem

| Rzecz | Skąd | Kiedy potrzebna |
|---|---|---|
| Domena z rekordem **A** wskazującym na IP VPS-a | rejestrator/DNS | **przed** pierwszym startem Caddy |
| `SECRET_KEY` (nowy, nie z deva) | `openssl rand -hex 32` | krok 2 |
| Hasło Postgresa (nowe, nie z deva) | `openssl rand -base64 24` | krok 2 |
| `GOOGLE_CLIENT_ID` / `SECRET` + dopisany redirect URI | Google Cloud Console | krok 2 |
| Klucze `FINNHUB` / `ALPHAVANTAGE` | panele dostawców | krok 2 |
| DSN-y Sentry | Sentry | dopiero krok 37 |
| Bucket S3-compatible + klucz aplikacyjny do niego | Backblaze B2 / Wasabi | krok 38 (sekcja 9) |

**Rekord A musi propagować się PRZED startem Caddy.** Caddy próbuje wystawić certyfikat
natychmiast po starcie, a produkcyjne Let's Encrypt ma ostry limit **błędów** — źle
ustawiony DNS potrafi zablokować wystawianie dla domeny na około tydzień. Stąd krok 4
poniżej (staging) jest obowiązkowy przy pierwszym uruchomieniu na nowej domenie.

**W Google Cloud Console** dopisz do „Authorized redirect URIs" dokładnie:
`https://<domena>/api/auth/google/callback`. Google odrzuca logowanie przy niezgodności
choćby o ukośnik.

---

## 1. Kod na VPS-ie

```bash
git clone <repo> /opt/alphasense
cd /opt/alphasense
```

Katalog roboczy dla wszystkich dalszych poleceń to korzeń repo (tam, gdzie `Makefile`).

## 2. Konfiguracja

```bash
cp .env.prod.example .env.prod
chmod 600 .env.prod
$EDITOR .env.prod
```

Uzupełnij wszystkie puste wartości. Trzy pułapki:

- `SECRET_KEY` musi mieć **co najmniej 32 znaki** i nie być wartością domyślną — aplikacja
  odmówi startu przy `ENV != dev` (`app/core/config.py`).
- Hasło Postgresa występuje **dwa razy**: jako `POSTGRES_PASSWORD` i wewnątrz
  `DATABASE_URL`. Muszą być identyczne.
- `.env.prod` nigdy nie trafia do repo (jest w `.gitignore`). Jego kopię trzymaj w
  menedżerze haseł — po utracie VPS-a odtworzenie backupu bez `SECRET_KEY` unieważni
  wszystkie sesje użytkowników.

Obserwowalność (krok 37) jest opcjonalna — z pustymi DSN-ami wszystko działa, tylko bez
alertów. Jeśli ją włączasz, załóż w Sentry **dwa projekty**: backendowy (`python-fastapi`,
DSN → `SENTRY_DSN`, czytany przez `api` i `worker` w runtime) i frontendowy (`nextjs`,
DSN → `NEXT_PUBLIC_SENTRY_DSN`, **wypiekany w bundle**, więc jego zmiana wymaga
`make prod-build`, nie restartu). `APP_VERSION` ustaw na skrót commita
(`git rev-parse --short HEAD`) — bez tego każdy błąd w Sentry wygląda tak samo niezależnie
od wdrożenia i nie widać, czy poprawka pomogła.

## 3. Budowa obrazów

```bash
make prod-build
```

`NEXT_PUBLIC_API_URL` jest **wypiekane w bundle na tym etapie**, nie czytane przy starcie
kontenera. Domyślne `/api` (adres względny) jest poprawne: Caddy serwuje frontend i API z
tego samego origin, więc przeglądarka nie robi żądań cross-origin i CORS w ogóle nie
wchodzi w grę. Zmiana tej wartości wymaga `make prod-build`, nie restartu.

## 4. Pierwsze uruchomienie — najpierw staging Let's Encrypt

W `.env.prod` odkomentuj:

```
ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory
```

```bash
make prod-up
make prod-logs s=caddy
```

W logach szukasz `certificate obtained successfully`. Przeglądarka pokaże ostrzeżenie o
niezaufanym certyfikacie — **tak ma być**, staging używa własnego CA. Sprawdzasz tylko, czy
cała ścieżka (DNS → Caddy → ACME) działa.

Gdy jest zielono: zakomentuj `ACME_CA` z powrotem i przełącz na produkcyjny certyfikat:

```bash
make prod-up          # podniesie zmienioną konfigurację
docker exec -it alphasense-prod-caddy-1 rm -rf /data/caddy/certificates
make prod-logs s=caddy
```

(Usunięcie katalogu certyfikatów zmusza Caddy do ponownego wystawienia — bez tego zostałby
przy certyfikacie stagingowym z wolumenu.)

## 5. Migracje i seed słownika rynków

Migracje wykonuje usługa `migrate` przy każdym `make prod-up` — `api` startuje dopiero po
jej pomyślnym zakończeniu (`service_completed_successfully`), więc po kroku 4 baza ma już
schemat. Zostaje **seed słownikowy**:

```bash
make prod-seed
```

**To nie jest opcjonalne.** `worker/scheduler.py` czyta tabelę `markets` **raz, przy
starcie** i rejestruje po jednym jobie EOD na rynek (ADR-102). Na pustej tabeli worker
wstaje z zerem jobów, loguje `scheduler.no_markets_found` i **nigdy nie pobierze żadnej
ceny** — aplikacja wygląda na działającą, tylko wszystkie wyceny są puste. Dlatego
`make prod-seed` po zasianiu sam restartuje workera.

`prod-seed` woła `python -m app.cli seed --reference-only`: rynki, indeksy referencyjne i
ich mapowania na dostawców. **Bez** demo użytkownika (którego hasło CLI wypisuje na
konsolę), demo portfela i demo pozycji — na produkcji to byłoby konto do przejęcia i cudze
dane w bazie użytkownika. Deweloperski `make seed` (pełny) zostaje bez zmian.

## 6. Weryfikacja

```bash
make prod-ps          # wszystkie usługi Up/healthy, `migrate` w stanie Exited (0)
curl -I https://<domena>/
curl -s https://<domena>/api/health        # {"status":"ok","db":"up","redis":"up","version":"..."}
curl -s https://<domena>/api/meta/freshness | head
```

`GET /api/health` zawsze zwraca `200` — stan czytasz z ciała. `status: "degraded"` z
`redis: "down"` znaczy „działa, wolniej" (cache można wyczyścić w każdej chwili,
CLAUDE.md §3.7) i kontener celowo **zostaje zdrowy**; `db: "down"` to realna awaria i
healthcheck Dockera oznacza wtedy `api` jako `unhealthy`. `version` to `APP_VERSION` — szybki
sposób sprawdzenia, czy wdrożenie faktycznie podmieniło kod.

Jeśli włączyłeś Sentry: sprawdź, czy w logach `api` i `worker` jest `sentry.enabled`
(`make prod-logs s=api`). `sentry.disabled` znaczy pusty `SENTRY_DSN`. Alerty z jobów EOD
przychodzą jako `Ingestia rynku <KOD> zakończona statusem failed|partial` — `failed` to
brak jakichkolwiek świeżych danych rynku, `partial` to część aktywów.

Ręcznie w przeglądarce, na telefonie i na desktopie: rejestracja → utworzenie portfela →
dodanie pozycji → wartość w PLN, struktura procentowa, ranking rynków. Formalny smoke test
(Playwright, 375 px + desktop) to krok 39.

Po pierwszym przebiegu jobów EOD (godziny w `docs/slownik-rynkow.md`) sprawdź, czy w bazie
pojawiły się ceny:

```bash
make prod-logs s=worker
```

## 7. Przetrwanie restartu VPS-a — jednostka systemd

`docker compose up` uruchamia usługi w kolejności z `depends_on`. **Restart demona Dockera
po reboocie hosta tej kolejności nie zna** — startuje kontenery z polityką restartu
niezależnie od siebie, a `migrate` (`restart: "no"`) nie wykona się w ogóle. W efekcie po
aktualizacji, która dokłada migrację, API mogłoby wstać na niezmigrowanej bazie.

Dlatego stack podnosi systemd, jednym `compose up`, a nie polityka restartu kontenerów:

```ini
# /etc/systemd/system/alphasense.service
[Unit]
Description=AlphaSense (docker compose)
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/alphasense
ExecStart=/usr/bin/docker compose --env-file .env.prod -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker compose --env-file .env.prod -f docker-compose.prod.yml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now alphasense
sudo reboot          # i sprawdź `make prod-ps` po powrocie
```

`restart: unless-stopped` na usługach zostaje — łapie pojedynczy kontener, który padł
między restartami hosta. Systemd odpowiada za start całości w poprawnej kolejności.

## 8. Aktualizacja wdrożenia

```bash
cd /opt/alphasense
git pull
make prod-build
make prod-up          # `migrate` wykona nowe migracje przed startem API
make prod-ps
```

Jeżeli zmienił się słownik rynków (`app/db/seed.py`), powtórz `make prod-seed` — seed jest
idempotentny, a restart workera jest konieczny, żeby zobaczył nowe rynki.

## 9. Kopia zapasowa i odtwarzanie

Nocny `pg_dump` z VPS-a do bucketu S3-compatible (krok 38). Skrypty:
`infra/backup/backup.sh` (kopia) i `infra/backup/restore-test.sh` (odtworzenie próbne).

### 9.1. Konfiguracja

Załóż bucket u dostawcy S3-compatible (Backblaze B2 lub Wasabi) i **klucz aplikacyjny
ograniczony do tego jednego bucketu**, z prawem zapisu i kasowania. Klucz leży na VPS-ie —
czyli dokładnie na maszynie, przed której utratą się zabezpieczasz — więc nie może być
kluczem do całego konta.

Ustawienia bucketu, obowiązkowe oba:

- **prywatny** (B2: *Files in Bucket are: Private*) — sprawdzalne żądaniem bez
  uwierzytelnienia, ma wrócić `401`, nie `200`;
- **reguła cyklu życia „zachowaj tylko ostatnią wersję"** (B2: *Lifecycle Settings → Keep
  only the last version of the file*). Bez niej `s3 rm` z retencji jedynie **ukrywa** plik,
  a stare dumpy leżą dalej i naliczają się do rachunku — retencja 7/4 jest wtedy pozorna.
  B2 domyślnie trzyma wszystkie wersje, więc to trzeba włączyć ręcznie.

Klucz aplikacyjny: dostęp do **tego jednego bucketu**, `Read and Write`, bez „Allow List All
Bucket Names" (skrypty nigdy nie listują kont, a wyłączone listowanie ogranicza szkody po
wycieku klucza). `keyID` → `BACKUP_S3_ACCESS_KEY`, `applicationKey` → `BACKUP_S3_SECRET_KEY`;
ten drugi B2 pokazuje **jeden jedyny raz**.

Uzupełnij w `.env.prod` sekcję „backup" (`BACKUP_S3_BUCKET`, `_ENDPOINT`, `_REGION`,
`_ACCESS_KEY`, `_SECRET_KEY`; przykładowe endpointy obu dostawców są w komentarzu
`.env.prod.example`) i nadaj plikowi `chmod 600`. Endpoint i region muszą pasować do
regionu bucketu — przy niezgodności B2 odpowiada `NoSuchBucket`, tak samo jak przy literówce
w nazwie. Przy pustych wartościach skrypt **nadal robi dump**, ale zostawia go na VPS-ie
i raportuje to jako ostrzeżenie do Sentry.

Zanim uruchomisz `make backup`, sprawdź sam klucz — skrypt potrzebuje zapisu, listowania,
kopii serwerowej (dzienna→tygodniowa), odczytu i kasowania, a `s3 ls` weryfikuje tylko jedno
z tych pięciu:

```bash
./infra/backup/check-bucket.sh
```

Skrypt zapisuje obiekt próbny, listuje, kopiuje, ściąga i porównuje treść, kasuje po sobie
(razem ze starymi wersjami) i ostrzega, jeśli bucket jest publiczny albo nie ma reguły
cyklu życia. Bazy ani dumpów nie dotyka.

```bash
make backup            # pierwszy przebieg — ręcznie, żeby zobaczyć log
```

W logu szukasz `Dump gotowy i czytelny`, `Wysyłka do s3://…` i `Gotowe.`.

### 9.2. Harmonogram

```bash
sudo cp infra/backup/alphasense-backup.cron /etc/cron.d/alphasense-backup
sudo chmod 644 /etc/cron.d/alphasense-backup
sudo systemctl restart cron
```

Backup o **05:30 czasu hosta** (po ostatniej ingestii EOD — rynek US o 23:15 czasu Nowego
Jorku, czyli ok. 04:15 UTC — i po snapshotach portfeli) oraz test odtworzenia w
poniedziałki o 06:30. Harmonogram jest w cronie **hosta**, nie w APSchedulerze workera:
worker to kontener tego samego stacku, więc awaria, po której backup jest najbardziej
potrzebny, zabrałaby ze sobą także backup.

Retencja: **7 kopii dziennych** (`daily/`) i **4 tygodniowe** (`weekly/`, awansowana kopia
niedzielna). Liczona w sztukach, nie w dniach — przy zatrzymanym cronie reguła wiekowa
skasowałaby po tygodniu również ostatnią zdrową kopię.

Awaria backupu idzie do Sentry (`python -m app.cli alert`, tag `component=infra`,
fingerprint `backup-failed`, czyli jeden problem z licznikiem zamiast nowej sprawy co noc)
**oraz** pocztą crona do roota. Dwie drogi celowo: przy pustym `SENTRY_DSN` zostaje poczta,
a przy padniętym MTA zostaje Sentry.

### 9.3. Test odtworzenia — obowiązkowy

```bash
make backup-restore-test
```

Ściąga **najnowszą kopię z bucketu** (nie lokalną — testujemy tę, która przeżyje utratę
VPS-a), odtwarza ją do jednorazowej bazy `restore_test_<znacznik>` obok produkcyjnej,
porównuje `alembic_version` z bazą produkcyjną, sprawdza, że słownik rynków nie jest pusty,
i **zawsze** kasuje bazę testową. Bazy produkcyjnej nie dotyka.

Uruchom go po pierwszym backupie i po każdej większej zmianie schematu. Backup, którego
nikt nie odtworzył, nie jest backupem.

### 9.4. Odtworzenie produkcji z kopii

Sytuacja: VPS stracony albo baza uszkodzona. Na czystej maszynie wykonaj kroki 1–4 tego
runbooka (kod, `.env.prod`, obrazy, start stacku) — z **tym samym `SECRET_KEY`**, inaczej
wszystkie sesje i tokeny odświeżające użytkowników przestaną działać.

```bash
# 1. Stack stoi, migracje przeszły — zatrzymaj to, co pisze do bazy.
make prod-down
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d postgres

# 2. Pobierz kopię (najnowszy klucz z `daily/` lub wybrany z `weekly/`).
aws s3 ls s3://<bucket>/alphasense/daily/ --endpoint-url <endpoint>
aws s3 cp s3://<bucket>/alphasense/daily/<plik>.dump . --endpoint-url <endpoint>

# 3. Odtwórz do PUSTEJ bazy. `--clean --if-exists` kasuje istniejące obiekty —
#    uruchamiaj to wyłącznie świadomie, na bazie, którą chcesz nadpisać.
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T postgres \
  pg_restore -U portfel -d portfel --clean --if-exists --no-owner --no-privileges --exit-on-error \
  < <plik>.dump

# 4. Podnieś resztę i sprawdź.
make prod-up
curl -s https://<domena>/api/health
```

Jeżeli nie masz na hoście `aws`, użyj tego samego obrazu, co skrypty:
`docker run --rm -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -e AWS_DEFAULT_REGION -v "$PWD:/backup" amazon/aws-cli:2.36.14 --endpoint-url <endpoint> s3 cp <źródło> /backup/`.
Tag musi być pełny (`2.36.14`) — `amazon/aws-cli:2` nie istnieje w rejestrze.

**Czego dump NIE zawiera:** `.env.prod` (sekrety — trzymaj jego kopię w menedżerze haseł),
certyfikatów Caddy'ego (wystawią się same) i danych Redisa (cache, odtwarza się sam).
Notowania i kursy walut worker dociągnie przy najbliższych jobach EOD, ale **historia
snapshotów portfeli jest nieodtwarzalna z zewnątrz** (ADR-101: append-only, bez
przeliczania wstecz) — to ona jest realnym powodem, dla którego ten backup istnieje.

---

## Rozwiązywanie problemów

**`make prod-up` kończy się błędem Postgresa o pustym haśle**
Uruchamiasz compose bez `--env-file .env.prod` (czyli nie przez `make`), albo `.env.prod`
nie istnieje / nie ma `POSTGRES_PASSWORD`.

**Strona nie odpowiada, `make prod-ps` pokazuje `caddy` jako nieuruchomiony**
Caddy czeka na `api` i `frontend` w stanie `healthy`. Sprawdź `make prod-logs s=api` —
najczęstsza przyczyna to błąd konfiguracji zatrzymujący uvicorna przy starcie
(`SECRET_KEY`, `DATABASE_URL`).

**`migrate` w stanie Exited z kodem innym niż 0**
`make prod-logs s=migrate`. API świadomie nie wstanie, dopóki migracje nie przejdą — to
zabezpieczenie, nie awaria.

**Wyceny są puste, `/api/meta/freshness` pokazuje wszystko jako nieświeże**
Prawie na pewno brak seeda słownika (`make prod-seed`) albo worker wystartował przed
seedem i ma zero jobów. Zajrzyj w `make prod-logs s=worker` po `scheduler.no_markets_found`.

**Certyfikat się nie wystawia**
Sprawdź, czy rekord A wskazuje na ten VPS i czy port 80 jest otwarty (ACME HTTP-01 go
potrzebuje). Przy powtarzających się błędach wróć na staging ACME, zanim wyczerpiesz limit
produkcyjny.
