# Taryfy energii PL dla Home Assistant

Cena prądu **brutto za każdą godzinę**: energia (stała z cennika albo dynamiczna z giełdy)
plus dystrybucja według grupy taryfowej. Do tego akcja wyznaczająca **najtańszy lub
najdroższy okres o zadanej długości**, do użycia w automatyzacjach.

Dlaczego cena całkowita, a nie sama giełda: dla G13 13.10.2026 najtańsze 3 godziny na RDN
to 11:00–14:00, ale 11–13 to szczyt przedpołudniowy dystrybucji. Po doliczeniu dystrybucji
najtańsze 3 godziny to 21:00–24:00.

## Obsługiwane taryfy

Operator: **TAURON Dystrybucja**, grupy **G11, G12, G12w, G12as, G13, G13s**.
Każdą stawkę można zmienić w opcjach integracji.

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
3. Wybierz grupę i rodzaj ceny energii. Sprawdź podpowiedziane stawki.

Możesz dodać kilka taryf naraz, np. G13 dynamiczną i G11 stałą, i porównywać je na wykresie.

## Encje

Prefiks encji pochodzi z nazwy wpisu, np. `taryfa_g13_dynamiczna`.

| Encja | Stan | Atrybuty |
|---|---|---|
| `sensor.<prefiks>_total_price` | cena całkowita teraz [zł/kWh brutto] | `prices_today`, `prices_tomorrow`, `prices` (`{time, price}`), `zone`, `energy`, `distribution`, `exchange_netto`, `tomorrow_available` |
| `sensor.<prefiks>_energy_price` | część za energię [zł/kWh brutto] | listy jak wyżej |
| `sensor.<prefiks>_distribution_price` | część za dystrybucję [zł/kWh brutto] | listy jak wyżej |
| `sensor.<prefiks>_next_total_price` | cena całkowita w następnym okresie | `start`, `zone` |
| `sensor.<prefiks>_zone` | strefa taryfowa (`morning_peak`, `other`, …) | `zone_name`, `rate_key` |
| `sensor.<prefiks>_fixed_monthly_cost` | opłaty stałe [zł/mies. brutto] | rozbicie na składniki |

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
- Energia, cena stała: [decyzja Prezesa URE z 17.12.2025, taryfa TAURON Sprzedaż](https://bip.ure.gov.pl/download/3/20340/TauronSprzedaz.pdf), 01.01–31.12.2026.
- Energia, cena dynamiczna: [Cennik „Prąd z Ceną Dynamiczną”](https://www.tauron.pl/-/media/offer-documents/produkty/2024/08-2024/dynamiczne/ts/EE-GD-CDzcb-Bezpieczny-TS-0.ashx), od 01.04.2026.

## Ograniczenia

- **G12as:** stawka nocna 0,0246 zł/kWh dotyczy tylko nadwyżki zużycia nocnego ponad
  analogiczny okres poprzedniego roku. Domyślnie przyjęta jest stawka podstawowa 0,2464.
- **G12as, G13s, cena stała:** sprzedawca nie publikuje dla nich osobnych cen energii.
  Domyślnie wstawiona jest cena G11, wpisz ceny ze swojej umowy.
- **Akcyza przy cenie dynamicznej:** cennik TAURON jej nie wymienia, domyślnie 0.
  Sprawdź na fakturze.
- **G14dynamic** (strefy z Energetycznego Kompasu PSE) i inni operatorzy: planowane.
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

MIT. Integracja nie jest powiązana z TAURON Polska Energia S.A.
