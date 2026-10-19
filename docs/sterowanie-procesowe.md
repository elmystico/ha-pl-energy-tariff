# Sterowanie procesowe ceną energii

Ten dokument opisuje podejście do sterowania odbiornikami na podstawie ceny energii.
Integracja dostarcza sygnały, a odbiorniki są funkcjami tych sygnałów i swoich parametrów
fizycznych. Zasada: **zamiast łańcucha „if … then” — złożenie funkcji ciągłych**.
Każdy nowy przypadek szczególny („przed szczytem”, „gdy bardzo drogo”, „ale nie w nocy”)
jest sygnałem, że brakuje członu w funkcji, a nie powodem do dopisania warunku.

Model obiektu nie jest konieczny. Wystarczy wiedzieć, jaką wielkość proces całkuje
(ciepło, światło, ładunek, praca do wykonania) i w jakim czasie.

## Dwie osie decyzji

### 1. Oś względna — *kiedy* zużywać

Ma sens tylko w horyzoncie τ, który proces fizycznie potrafi „wycałkować” bez szkody:
pojemność cieplna zawartości lodówki, zapas cukrów roślin w akwarium, bateria, czas do terminu.

- μ_τ(t) — średnia cen w oknie τ (ważona; przeszłość i prognoza),
- σ_τ(t) — odchylenie standardowe w tym samym oknie,
- **z_τ(t) = (p(t) − μ_τ(t)) / σ_τ(t)** — cena standaryzowana (z-score) w horyzoncie τ.

z < 0: teraz taniej niż przeciętnie w czasie, który proces i tak musi przetrwać — zużywaj,
magazynuj. z > 0: oddawaj zapas. Okno dobowe, tygodniowe czy 16-godzinne to ta sama funkcja
z innym τ. Przykład: 19.10.2026 o 15:00 cena 1,22 zł była „normalna” na tle 16 h, ale z₄ₕ było
silnie ujemne, bo w oknie siedział wieczór po 2,2 zł — lodówka powinna była się schłodzić.

### 2. Oś bezwzględna — *ile* zużywać

Koszt „po kieszeni” jest bezwzględny. W okresie drogiej energii zacieśniamy kryteria
oszczędności, w okresie taniej — wolno zużyć więcej, ale tylko tyle, ile obiekt zmagazynuje w τ.

- R — długoterminowa cena odniesienia (już liczona: `sensor.<prefiks>_reference_price`),
- **a(t) = μ_τ(t) / R** — względny poziom kosztów okresu,
- ln a — wygodna postać: „2× drożej” i „2× taniej” są symetryczne.

## Złożenie

Jeden kształt dla wszystkich odbiorników:

```
u(t) = sat( u₀(a) + K · g(z_τ) )          # u — nastawa lub szybkość pracy
u₀(a) = u_cel + c · ln a                   # przesunięcie średniej przez poziom kosztów
```

- `sat` — ograniczenia sprzętowe i bezpieczeństwa (jedyne miejsce na twarde granice),
- `g` — funkcja kształtu: liniowa (nastawy) albo sigmoida σ(−z/T) (szybkość pracy 0…1),
- wolny człon całkujący (np. średnia 24 h temperatury) koryguje u_cel — kompensuje
  niedokładność, nie zastępuje funkcji; z anti-windupem.

### Odbiorniki

| Odbiornik | Wielkość całkowana | τ | Funkcja |
|---|---|---|---|
| Lodówka (chłodziarka/zamrażarka) | ciepło zawartości | 3–4 h | T_nast = T₀ + c·ln a + K·z_τ; całka średniej 24 h → T₀ |
| Akwarium — światło, CO₂ | fotosynteza / zapas cukrów | ~1 doba | dawka dzienna D = D₀·a^(−ε); intensywność ∝ σ(−z_τ/T) w fotoperiodzie |
| Suszenie mopów | praca do wykonania | do terminu | szybkość u = σ(−z_τ/T) + człon zaległości ∝ praca/czas_do_terminu |
| Ładowanie robota | ładunek baterii | do najbliższego sprzątania | cel SoC = f(a), szybkość jak wyżej |
| CWU / akumulacja ciepła | ciepło zasobnika | 6–24 h | jak lodówka, z odwrotnym znakiem |

ε — elastyczność dawki względem kosztów (0 = dawka stała, 1 = stały wydatek).
c, K, T — wzmocnienia; dobiera się je jak w regulatorze, obserwując przebiegi.

## Sygnały do dodania w integracji

- `z_τ`, `μ_τ`, `σ_τ` i `a` dla zadanych τ (lista τ w opcjach wpisu, np. 4 h, 24 h),
- wagi okna jak w cenie odniesienia (filtry pierwszego rzędu: prognoza z e^(−t/τ),
  historia z inercją), żeby sygnały były gładkie w czasie, bez skoków na granicy okna.

Obecne wskaźniki pozostają: „odchylenie ceny” to z liczone względem R (długi horyzont),
„ranking okna” i „poziom ceny” to dyskretne przybliżenie z₁₆ₕ — nowe sterowania powinny
korzystać z sygnałów ciągłych.

## Gdzie co liczyć

| Warstwa | Co | Dlaczego |
|---|---|---|
| Integracja (Python) | sygnały z_τ, μ_τ, σ_τ, a | wspólne dla wszystkich, testowalne, jedno źródło prawdy |
| Node-RED | funkcje odbiorników (u = …), strojenie c, K, T, ε | czytelne dla człowieka: przepływ widać, parametry są węzłami, przebiegi na żywo w debug/wykresach; zmiana bez restartu |
| HA | wykonanie: zapis nastaw, limity szybkości zapisu (np. HomeWhiz), nadzór | integracje urządzeń są w HA |
| ESPHome | szybkie pętle lokalne (sekundy), zabezpieczenia, praca bez sieci | pompy P1/P2, falownik, zawory, strażnik stycznika — nie mogą zależeć od HA |

Do Node-RED najlepiej nadają się: funkcja lodówki, dawka i rozkład światła akwarium,
szybkość suszenia i cel ładowania robota — wolne (minuty), wymagające strojenia, takie,
które człowiek chce obejrzeć i zrozumieć. W automatyzacjach HA zostaje tylko wykonanie.

### Kierunek docelowy: Node-RED → ESPHome dynamicznie

Projekt `esphome-lua-runtime` (Lua 5.4 w ESPHome, skrypty przez MQTT, węzły Node-RED
z generacją `toLua()`) pozwala przenieść tę samą funkcję z Node-RED na sterownik bez
przeflashowania. Podział:

- funkcja odbiornika projektowana i strojona w Node-RED (te same węzły),
- gdy ma działać lokalnie (np. światło akwarium także przy awarii HA), węzeł generuje Lua
  i wysyła na sterownik; sygnały ceny (z_τ, a albo tablica cen na dobę) trafiają na
  sterownik przez MQTT jako wejścia,
- sterownik trzyma ostatnią tablicę cen i liczy u(t) sam, z ograniczeniami `sat` po swojej stronie.

## Migracja istniejących automatyzacji

1. Dodać sygnały z_τ i a do integracji.
2. Lodówka: zastąpić poziomy ceny, max(poziom, odniesienie) i regułę „ładowania przed
   szczytem” funkcją T₀ + c·ln a + K·z₄ₕ; całka średniej 24 h zostaje.
3. Suszenie i ładowanie robota: zastąpić próg „najtańsze N godzin” funkcją szybkości
   z członem zaległości.
4. Przenieść funkcje do Node-RED; w HA zostawić wykonanie.
