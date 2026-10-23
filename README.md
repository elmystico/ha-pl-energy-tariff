# Taryfy energii PL dla Home Assistant

Cena prądu **brutto za każdą godzinę**: energia (stała z cennika albo dynamiczna z giełdy)
plus dystrybucja według grupy taryfowej. Do tego akcja wyznaczająca **najtańszy lub
najdroższy okres o zadanej długości**, do użycia w automatyzacjach.

Dlaczego cena całkowita, a nie sama giełda: dla G13 13.10.2026 najtańsze 3 godziny na RDN
to 11:00–14:00, ale 11–13 to szczyt przedpołudniowy dystrybucji. Po doliczeniu dystrybucji
najtańsze 3 godziny to 21:00–24:00.

## Obsługiwane taryfy

| Operator (OSD) | Grupy | Domyślne stawki |
|---|---|---|
| TAURON Dystrybucja | G11, G12, G12w, G12as, G13, G13s | taryfa 2026, sprawdzone |
| ENEA Operator | G11, G12, G12w, G12as | taryfa 2026, sprawdzone |
| Energa-Operator | G11, G12, G12w, G12r, G12as | taryfa 2026, sprawdzone |
| PGE Dystrybucja | G11, G12, G12w, G12n, G12as | **orientacyjne**, porównaj z fakturą |
| Stoen Operator | G11, G12, G12w, G12as | **orientacyjne**, porównaj z fakturą |
| inny | G11, G12, G12w, G12as, G13 | stawki TAURON, wpisz własne |

Każdą stawkę, **godziny każdej strefy** oraz nazwy operatora i sprzedawcy można zmienić
w opcjach integracji. Godziny wpisuje się jako `13-15, 22-6`; dla grup z podziałem na
lato i zimę osobno dla obu okresów.

Domyślne godziny stref:

| Operator · grupa | Strefy (czas lokalny) |
|---|---|
| PGE G12 | nocna: zima 13–15, 22–6 · lato 15–17, 22–6 |
| PGE G12w | jak PGE G12 w dni robocze, weekendy i święta całą dobę w strefie pozaszczytowej |
| PGE G12n | nocna 1–5 · niedziele i święta całą dobę (sobota jak dzień roboczy) |
| Enea G12 | nocna 13–15, 22–6 (Enea ustala godziny indywidualnie: 8 h z 22–7 i 2 h z 13–17 – sprawdź na liczniku) |
| Enea G12w | szczytowa pn–pt 6–21 |
| Energa G12, G12w | nocna 13–15, 22–6 (G12w: weekendy i święta całą dobę) |
| Energa G12r | pozaszczytowa 13–16, 22–7 |
| Stoen G12 | nocna 13–15, 22–6 |
| Stoen G12w | szczytowa pn–pt 6–22 |
| G12as (wszyscy) | nocna 22–6 |

TAURON:

| Grupa | Strefy (czas lokalny) |
|---|---|
| G11 | całodobowa |
| G12 | dzienna 6–13, 15–22 · nocna 22–6, 13–15 |
| G12w | szczytowa pn–pt 6–13, 15–22 · pozaszczytowa: pozostałe godziny, weekendy i święta |
| G12as | dzienna 6–22 · nocna 22–6 |
| G13 | szczyt przedpołudniowy 7–13 · szczyt popołudniowy lato 19–22, zima 16–21 · pozostałe godziny; weekendy i święta całą dobę w strefie pozostałej |
| G13s | lato: pozaszczytowa 9–17, szczytowa 7–9 i 17–21, nocna 21–7 · zima: pozaszczytowa 10–15, szczytowa 7–10 i 15–21 · stawki różne w dni robocze i wolne |

Lato: 1.04–30.09, zima: 1.10–31.03. Święta ustawowe liczone wewnętrznie, łącznie
z Wielkanocą, Bożym Ciałem i Wigilią (dzień wolny od 2025).

### Cena energii

- **Dynamiczna:** (cena z encji netto + składnik cenotwórczy + akcyza) × (1 + VAT).
  Encja źródłowa z listą cen w atrybutach, np. `sensor.tge_rdn_fixing_1` z integracji
  [TGE RDN](https://github.com/elmystico/ha-tge-rdn). Domyślnie TAURON „Prąd z Ceną
  Dynamiczną”: SC 0,0892 zł/kWh netto.
- **Stała:** ceny netto ze strefami, domyślnie taryfa TAURON Sprzedaż 2026, plus akcyza
  0,005 zł/kWh.

### Dystrybucja

(stawka strefy + opłata jakościowa + OZE + kogeneracyjna) × (1 + VAT).
Opłaty stałe (składnik stały sieciowy, abonament, opłata mocowa, handlowa) są w osobnym
sensorze miesięcznym. Nie wpływają na to, która godzina jest tańsza.

## Instalacja

1. HACS → ⋮ → *Custom repositories* → `https://github.com/elmystico/ha-pl-energy-tariff`,
   kategoria **Integration**. Zainstaluj, zrestartuj HA.
2. Ustawienia → Urządzenia i usługi → Dodaj integrację → **Taryfy energii PL**.
3. Podaj nazwę (opcjonalnie), operatora i rodzaj ceny energii, potem grupę. Sprawdź
   podpowiedziane stawki i godziny stref.

### Kilka liczników, kilka taryf

Jeden wpis integracji odpowiada jednemu licznikowi. Wpisów może być dowolnie wiele, każdy
z innym operatorem, grupą, źródłem ceny i stawkami, np. „Dom” (TAURON G13 dynamiczna)
i „Garaż” (PGE G12 stała). Wpisy liczą się niezależnie, łącznie z ceną odniesienia
i wskaźnikami.

- **Panel Energia:** przy każdym liczniku wybierz *Użyj encji z aktualną ceną* i wskaż
  `sensor.<prefiks>_total_price` jego wpisu.
- **Akcja `find_window`:** przy kilku wpisach podaj `config_entry_id`.

Kilka wpisów przydaje się też do porównania taryf na tym samym zużyciu.

## Encje

Prefiks encji pochodzi z nazwy podanej przy dodawaniu wpisu („Dom” → `dom`), a bez nazwy
z automatycznej, np. `taryfa_g13_dynamiczna`. Późniejsza zmiana nazwy wpisu nie zmienia
identyfikatorów encji. Dwa wpisy o tej samej nazwie dostaną końcówkę `_2`.

Jednostki encji to `PLN/kWh` i `PLN/d` — kod waluty wg ISO 4217, jakiego HA wymaga dla
kwot (`monetary`) i cen w panelu Energia; z nich korzystają też np. sensory kosztu
Powercalc. Do wersji 0.3.0 było `zł/kWh` i `zł`. Od 0.4.0 opłaty stałe są dobowe
(`fixed_daily_cost`, wcześniej `fixed_monthly_cost` w zł/mies.) — encja jest przemianowywana
automatycznie, a składnik dobowy da się wprost dodać do dziennych kosztów zużycia.

| Encja | Stan | Atrybuty |
|---|---|---|
| `sensor.<prefiks>_total_price` | cena całkowita teraz [zł/kWh brutto] | `prices_today`, `prices_tomorrow`, `prices` (`{time, price}`), `zone`, `energy`, `distribution`, `exchange_netto`, `tomorrow_available` |
| `sensor.<prefiks>_energy_price` | część za energię [zł/kWh brutto] | listy jak wyżej |
| `sensor.<prefiks>_distribution_price` | część za dystrybucję [zł/kWh brutto] | listy jak wyżej |
| `sensor.<prefiks>_next_total_price` | cena całkowita w następnym okresie | `start`, `zone` |
| `sensor.<prefiks>_zone` | strefa taryfowa (`morning_peak`, `other`, …) | `zone_name`, `rate_key`, `group`, `operator` |
| `sensor.<prefiks>_fixed_daily_cost` | opłaty stałe na dobę [PLN/d brutto] — składniki miesięczne podzielone przez liczbę dni bieżącego miesiąca (suma z dni miesiąca = kwota miesięczna, niezależnie od taryfy) | składniki na dobę, `days_in_month`, kwoty miesięczne `monthly_*` |
| `sensor.<prefiks>_reference_price` | cena odniesienia [zł/kWh] | `forecast_inertia`, `history_inertia`, `forecast_hours`, `tau_*_h`, `sigma` |
| `sensor.<prefiks>_price_score` | odchylenie ceny od odniesienia [%] | – |
| `sensor.<prefiks>_window_median` | mediana ceny w oknie (domyślnie 16 h) | progi `very_cheap_max`, `cheap_max`, `expensive_min`, `very_expensive_min` |
| `sensor.<prefiks>_price_level` | `very_cheap` / `cheap` / `normal` / `expensive` / `very_expensive` | – |
| `sensor.<prefiks>_charge_target` | docelowe naładowanie baterii [%] | – |
| `binary_sensor.<prefiks>_cheap_now` / `_expensive_now` | teraz tania / droga część okna | progi |

## Wskaźniki ceny

**Cena odniesienia** (zastępuje „średnią cenę prądu”). Prognoza sięga najwyżej ~35 h, więc
średnia składa się z dwóch inercji (filtrów pierwszego rzędu):

- inercja prognozy F: średnia cen od teraz do końca prognozy z wagą e^(−t/τf),
  τf = H = długość pozostałej prognozy;
- inercja historii P: filtr cen z przeszłości, τh = tydzień − H. Przy starcie liczona
  z historii recordera (28 dni), potem na bieżąco;
- R = (τf·F + τh·P) / tydzień.

Tymi samymi wagami liczone jest odchylenie σ, a z niego **odchylenie ceny**
100·(cena − R)/(σ·R), w tej samej skali co dawna „standaryzowana cena prądu”.

Jak z tych wskaźników budować sterowanie odbiornikami funkcjami ciągłymi zamiast
progów — [docs/sterowanie-procesowe.md](docs/sterowanie-procesowe.md).

**Okno rankingu**: sloty od bieżącego do 16 h naprzód. 1/4 najtańszych to „tanio”,
1/6 to „bardzo tanio”, symetrycznie drogo. Gdy do końca prognozy zostało mniej niż 4 h,
ranking jest niedostępny.

**Docelowe naładowanie** (np. limit ładowania robota): ≤ próg bardzo tani → 100 %,
próg tani → 81 %, cena odniesienia → 66 %, tuż poniżej progu drogiego → 20 %, drogo → 0 %,
liniowo pomiędzy. Wszystkie progi i poziomy zmienisz w opcjach integracji.

## Wykres prognozy cen

Atrybuty `prices_today` / `prices_tomorrow` mają ten sam format co w integracji TGE RDN,
więc cenę całkowitą można dołożyć do istniejącego wykresu
[ApexCharts](https://github.com/RomRider/apexcharts-card) jako drugi słupek z własną osią
(giełda w zł/MWh netto po lewej, cena całkowita w zł/kWh brutto po prawej):

```yaml
type: custom:apexcharts-card
graph_span: 24h
span:
  start: day          # dla jutra dodaj: offset: +1d
header:
  show: true
  title: Ceny prądu – dziś
yaxis:
  - id: rdn
    decimals: 0
  - id: total
    opposite: true
    decimals: 2
    min: 0
series:
  - entity: sensor.tge_rdn_fixing_1
    name: Fixing I [zł/MWh netto]
    type: column
    yaxis_id: rdn
    data_generator: |
      return entity.attributes.prices_today.map(p => [new Date(p.time), p.price]);
  - entity: sensor.taryfa_g13_dynamiczna_total_price
    name: Cena całkowita [zł/kWh brutto]
    type: column
    color: '#ff7043'
    yaxis_id: total
    data_generator: |
      return entity.attributes.prices_today.map(p => [new Date(p.time), p.price]);
```

Dla jutra zamień `prices_today` na `prices_tomorrow` i dodaj `offset: +1d` w `span`.

## Akcja `pl_energy_tariff.find_window`

Zwraca początek i koniec najtańszego (lub najdroższego) okresu.

| Pole | Domyślnie | Znaczenie |
|---|---|---|
| `duration` | – | długość w godzinach, zaokrąglana w górę do pełnych slotów |
| `mode` | `cheapest` | `cheapest` / `most_expensive` |
| `period` | `upcoming` | `upcoming` (od bieżącego slotu do końca znanych cen), `today`, `tomorrow` |
| `contiguous` | `true` | `false` = N najlepszych godzin w dowolnych miejscach |
| `price` | `total` | `total` / `energy` / `distribution` |
| `start_after`, `end_before` | – | ograniczenie okna, np. termin zakończenia |
| `config_entry_id` | – | wymagane przy kilku taryfach |

Odpowiedź: `found`, `start`, `end`, `hours`, `average`, `min`, `max`, `unit`, `ranges`,
`slots`. Gdy nie ma danych: `found: false`, `reason`, `available_from`, `available_to`.

**Uruchom zmywarkę w najtańszych 3 godzinach, które skończą się przed 7:00:**

```yaml
actions:
  - action: pl_energy_tariff.find_window
    data:
      duration: 3
      end_before: "{{ (today_at('07:00') + timedelta(days=1)).isoformat() }}"
    response_variable: okno
  - if: "{{ okno.found }}"
    then:
      - delay:
          seconds: "{{ [(as_datetime(okno.start) - now()).total_seconds(), 0] | max | int }}"
      - action: switch.turn_on
        target:
          entity_id: switch.zmywarka
```

**Czy teraz jest jedna z 8 najtańszych godzin dziś** (np. suszenie po sprzątaniu):

```yaml
actions:
  - action: pl_energy_tariff.find_window
    data: {duration: 8, period: today, contiguous: false}
    response_variable: tanie
  - if: >
      {% set t = now() %}
      {{ tanie.found and tanie.ranges
         | selectattr('start', 'le', t.isoformat())
         | selectattr('end', 'gt', t.isoformat()) | list | count > 0 }}
    then:
      - action: button.press
        target: {entity_id: button.odkurzacz_manual_drying}
```

## Źródła stawek (stan na 13.10.2026)

- Dystrybucja: [Wyciąg z Taryfy TAURON Dystrybucja S.A. na rok 2026 dla grup G](https://www.tauron-dystrybucja.pl/-/media/offer-documents/dystrybucja/aktualna-taryfa/wyciag-z-taryfy-td-sa-na-rok-2026-dla-odbiorcow-grup-g.ashx),
  stawki od 01.02.2026. Sprawdzone ze [stawkami brutto](https://www.tauron-dystrybucja.pl/-/media/offer-documents/dystrybucja/aktualna-taryfa/stawki-brutto-w-grupach-g-na-rok-2026.ashx).
- ENEA Operator: wyciąg z taryfy na 2026 r. (01.01–31.12.2026), opłata jakościowa
  0,0332 od 01.02.2026.
- Energa-Operator: wyciąg z taryfy na 2026 r. (aktualizacja 01.02.2026).
- PGE Dystrybucja, Stoen Operator: godziny stref z taryf na 2026 r.; stawki ze źródeł
  pośrednich, **niesprawdzone** z taryfą.
- Energia, cena stała (domyślnie dla każdego operatora): [decyzja Prezesa URE z 17.12.2025, taryfa TAURON Sprzedaż](https://bip.ure.gov.pl/download/3/20340/TauronSprzedaz.pdf), 01.01–31.12.2026.
- Energia, cena dynamiczna: [Cennik „Prąd z Ceną Dynamiczną”](https://www.tauron.pl/-/media/offer-documents/produkty/2024/08-2024/dynamiczne/ts/EE-GD-CDzcb-Bezpieczny-TS-0.ashx), od 01.04.2026.

## Ograniczenia

- **G12as:** stawka nocna 0,0246 zł/kWh dotyczy tylko nadwyżki zużycia nocnego ponad
  analogiczny okres poprzedniego roku. Domyślnie przyjęta jest stawka podstawowa 0,2464.
- **G12as (Enea 0,0246, Energa 0,0337):** jak wyżej, stawka nocna tylko dla nadwyżki.
- **Ceny energii przy cenie stałej** są domyślnie z taryfy TAURON Sprzedaż niezależnie od
  operatora. Przy innym sprzedawcy oraz dla G12as, G12n, G12r i G13s wpisz ceny z umowy.
- **PGE i Stoen:** domyślne stawki dystrybucji są orientacyjne; dla PGE G12w i G12n
  przyjęto stawki G12. Porównaj z fakturą.
- **Energa – abonament** przy zdalnym odczycie jest niższy (0,74 / 0,70 zł netto) niż
  domyślny; okresy 6 i 12 mies. nie występują w taryfie.
- **Enea G12sezON, G13active, Stoen G12eko, PGE G12e:** nieobsługiwane (strefy zależne
  od miesiąca lub publikowane osobno).
- **Akcyza przy cenie dynamicznej:** cennik TAURON jej nie wymienia, domyślnie 0.
  Sprawdź na fakturze.
- **G14dynamic** (strefy z Energetycznego Kompasu PSE): planowane.
- Próg 0,005 zł/kWh netto z cennika dynamicznego dotyczy średniej w okresie
  rozliczeniowym, nie pojedynczej godziny, więc nie jest stosowany do cen godzinowych.

## Podziękowania

Format atrybutów `prices_today` / `prices_tomorrow` / `prices` pochodzi z integracji
[TGE](https://github.com/PiotrMachowski/Home-Assistant-custom-components-TGE) i
[PGE-TGE](https://github.com/PiotrMachowski/Home-Assistant-custom-components-PGE-TGE)
[Piotra Machowskiego](https://github.com/PiotrMachowski), dzięki czemu istniejące
wykresy działają bez zmian.

## Wsparcie AI

Kod, testy i dokumentację przygotowano przy wsparciu asystenta AI, pod nadzorem i z weryfikacją
autora. Stawki sprawdzono w dokumentach źródłowych, a obliczenia porównano z wartościami
z działającej instalacji Home Assistant.

## Licencja

MIT. Integracja nie jest powiązana z żadnym operatorem ani sprzedawcą energii.
