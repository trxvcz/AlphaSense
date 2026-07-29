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
| Bucket S3-compatible | Backblaze B2 / Wasabi | dopiero krok 38 |

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
curl -s https://<domena>/api/meta/freshness | head
```

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

## 9. Odtwarzanie z backupu

Skrypt backupu i procedura odtworzenia to **krok 38** — ta sekcja zostanie uzupełniona
razem z `infra/backup/backup.sh`. Do tego czasu produkcja **nie ma kopii zapasowej**; nie
wprowadzaj do niej danych, na których Ci zależy.

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
