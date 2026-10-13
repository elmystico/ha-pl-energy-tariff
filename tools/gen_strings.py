"""Generate strings.json and translations from tariff definitions. Run from repo root."""
import json
import sys

sys.path.insert(0, ".")
from custom_components.pl_energy_tariff import tariffs as T

ZONE_EN = {"allday": "all day", "day": "day", "night": "night", "peak": "peak", "offpeak": "off-peak",
           "morning_peak": "morning peak", "afternoon_peak": "afternoon peak", "other": "other hours",
           "day_offpeak": "day off-peak", "day_peak": "day peak"}
SEASON = {"summer": ("lato", "summer"), "winter": ("zima", "winter")}
DAYT = {"workday": ("dzień roboczy", "workday"), "dayoff": ("dzień wolny", "day off")}

def rate_label(key, lang):
    i = 0 if lang == "pl" else 1
    if key.count("_") >= 2 and key.split("_")[0] in SEASON:
        s, d, *z = key.split("_")
        z = "_".join(z)
        zn = T.ZONE_NAMES_PL[z] if lang == "pl" else ZONE_EN[z]
        return f"{zn} ({SEASON[s][i]}, {DAYT[d][i]})"
    return T.ZONE_NAMES_PL[key] if lang == "pl" else ZONE_EN[key]

dist_keys = sorted({k for g in T.GROUPS.values() for k in g.dist_rates})
energy_keys = sorted({k for g in T.GROUPS.values() for k in g.energy_zones})

def build(lang):
    pl = lang == "pl"
    L = (lambda p, e: p if pl else e)
    dist = {f"dist_{k}": L(f"Dystrybucja – {rate_label(k,'pl')} [zł/kWh netto]", f"Distribution – {rate_label(k,'en')} [zł/kWh net]") for k in dist_keys}
    energy = {f"energy_{k}": L(f"Energia – {rate_label(k,'pl')} [zł/kWh netto]", f"Energy – {rate_label(k,'en')} [zł/kWh net]") for k in energy_keys}
    common_dist = {
        "quality_fee": L("Opłata jakościowa [zł/kWh netto]", "Quality fee [zł/kWh net]"),
        "oze_fee": L("Opłata OZE [zł/kWh netto]", "RES (OZE) fee [zł/kWh net]"),
        "cogeneration_fee": L("Opłata kogeneracyjna [zł/kWh netto]", "Cogeneration fee [zł/kWh net]"),
        "vat": L("VAT (ułamek, 0,23 = 23%)", "VAT (fraction, 0.23 = 23%)"),
        "phases": L("Liczba faz przyłącza", "Number of phases"),
        "billing_months": L("Okres rozliczeniowy [mies.]", "Billing period [months]"),
        "capacity_bracket": L("Roczne zużycie (opłata mocowa)", "Yearly consumption (capacity fee)"),
    }
    dyn = {
        "price_entity": L("Encja z cenami giełdowymi (RDN / RCE)", "Exchange price entity (RDN / RCE)"),
        "source_includes_vat": L("Ceny w encji zawierają VAT", "Entity prices include VAT"),
        "margin": L("Składnik cenotwórczy / marża [zł/kWh netto]", "Seller margin [zł/kWh net]"),
        "excise": L("Akcyza [zł/kWh] (0 jeśli zawarta w marży)", "Excise [zł/kWh] (0 if included in margin)"),
    }
    fixed = dict(energy)
    fixed.update({
        "excise": L("Akcyza [zł/kWh]", "Excise [zł/kWh]"),
        "trade_fee": L("Opłata handlowa [zł/mies. netto]", "Trade fee [zł/month net]"),
    })
    dyn_desc = L("Cena energii = (cena z encji netto + marża + akcyza) × (1 + VAT). Domyślnie TAURON „Prąd z Ceną Dynamiczną” (SC 0,0892 zł/kWh netto). Encja musi mieć atrybuty `prices_today`/`prices_tomorrow` lub `prices` z listą elementów `time` + `price`, np. `sensor.tge_rdn_fixing_1`.",
                 "Energy price = (entity price net + margin + excise) × (1 + VAT). Defaults: TAURON dynamic price (SC 0.0892 zł/kWh net). The entity must expose `prices_today`/`prices_tomorrow` or `prices` lists of `time` + `price` items, e.g. `sensor.tge_rdn_fixing_1`.")
    fixed_desc = L("Ceny energii netto bez akcyzy. Domyślnie taryfa TAURON Sprzedaż 2026 (decyzja URE z 17.12.2025). Dla G12as i G13s sprzedawca nie publikuje osobnych cen – wpisz ceny ze swojej umowy.",
                   "Net energy prices excluding excise. Defaults: TAURON Sprzedaż 2026 tariff. For G12as and G13s enter prices from your contract.")
    dist_desc = L("Stawki TAURON Dystrybucja dla {group}, netto, ważne od 01.02.2026. Dla G12as stawka nocna 0,0246 dotyczy tylko nadwyżki zużycia nocnego ponad analogiczny okres poprzedniego roku.",
                  "TAURON Dystrybucja rates for {group}, net, valid from 2026-02-01.")
    errors = {
        "entity_not_found": L("Nie znaleziono encji.", "Entity not found."),
        "unsupported_unit": L("Nieobsługiwana jednostka ceny (obsługiwane: zł/MWh, zł/kWh, gr/kWh, PLN/MWh, PLN/kWh).", "Unsupported unit (zł/MWh, zł/kWh, gr/kWh, PLN/MWh, PLN/kWh)."),
        "no_price_list": L("Encja nie ma listy cen w atrybutach (prices_today / prices).", "Entity has no price list in its attributes."),
    }
    zone_states = {k: (T.ZONE_NAMES_PL[k] if pl else ZONE_EN[k]) for k in energy_keys}
    ind = {
        "window_hours": L("Okno rankingu cen [h do przodu]", "Ranking window [h ahead]"),
        "cheap_fraction": L("Część tanich / drogich godzin w oknie (0,25 = 1/4)", "Share of cheap / expensive slots in the window (0.25 = 1/4)"),
        "extreme_fraction": L("Część bardzo tanich / bardzo drogich (0,1667 = 1/6)", "Share of very cheap / very expensive (0.1667 = 1/6)"),
        "reference_days": L("Okres ceny odniesienia [dni]", "Reference price period [days]"),
        "charge_very_cheap": L("Ładowanie przy bardzo tanim prądzie (%)", "Charge target when very cheap (%)"),
        "charge_cheap": L("Ładowanie na progu taniego (%)", "Charge target at the cheap threshold (%)"),
        "charge_average": L("Ładowanie przy cenie odniesienia (%)", "Charge target at the reference price (%)"),
        "charge_expensive": L("Ładowanie tuż poniżej progu drogiego (%) (powyżej: 0)", "Charge target just below the expensive threshold (%) (above: 0)"),
    }
    ind_desc = L("Cena odniesienia = ważona średnia inercji prognozy (τ = długość prognozy) i inercji historii (τ = okres − długość prognozy). Ranking: tanie/drogie godziny w oknie od teraz.",
                 "Reference price = weighted mean of the forecast inertia (τ = forecast length) and the history inertia (τ = period − forecast length). Ranking: cheap/expensive slots in the window starting now.")
    levels = {"very_cheap": L("bardzo tanio", "very cheap"), "cheap": L("tanio", "cheap"), "normal": L("normalnie", "normal"),
              "expensive": L("drogo", "expensive"), "very_expensive": L("bardzo drogo", "very expensive")}
    return {
        "config": {
            "step": {
                "user": {"title": L("Taryfa energii", "Electricity tariff"),
                         "description": L("Operator: TAURON Dystrybucja. Wybierz grupę taryfową i sposób rozliczania energii.", "Operator: TAURON Dystrybucja. Choose the tariff group and energy pricing."),
                         "data": {"group": L("Grupa taryfowa", "Tariff group"), "energy_mode": L("Cena energii", "Energy price")}},
                "energy_dynamic": {"title": L("Cena dynamiczna", "Dynamic price"), "description": dyn_desc, "data": dyn},
                "energy_fixed": {"title": L("Cena stała", "Fixed price"), "description": fixed_desc, "data": fixed},
                "distribution": {"title": L("Dystrybucja i opłaty", "Distribution and fees"), "description": dist_desc, "data": {**dist, **common_dist}},
            },
            "error": errors,
        },
        "options": {
            "step": {
                "init": {"title": L("Cena energii", "Energy price"), "data": {**dyn, **fixed}},
                "distribution": {"title": L("Dystrybucja i opłaty", "Distribution and fees"), "description": dist_desc, "data": {**dist, **common_dist}},
                "indicators": {"title": L("Wskaźniki ceny", "Price indicators"), "description": ind_desc, "data": ind},
            },
            "error": errors,
        },
        "selector": {
            "group": {"options": {k.lower(): k for k in T.GROUPS}},
            "energy_mode": {"options": {"dynamic": L("dynamiczna (giełda RDN/RCE)", "dynamic (exchange)"), "fixed": L("stała (cennik sprzedawcy)", "fixed (seller tariff)")}},
            "phases": {"options": {"1": L("1-fazowe", "single-phase"), "3": L("3-fazowe", "three-phase")}},
            "billing": {"options": {"1": "1", "2": "2", "6": "6", "12": "12"}},
            "capacity": {"options": {"lt500": L("poniżej 500 kWh", "below 500 kWh"), "500_1200": "500–1200 kWh", "1200_2800": "1200–2800 kWh", "gt2800": L("powyżej 2800 kWh", "above 2800 kWh")}},
            "mode": {"options": {"cheapest": L("najtańszy", "cheapest"), "most_expensive": L("najdroższy", "most expensive")}},
            "period": {"options": {"upcoming": L("od teraz", "from now"), "today": L("dziś", "today"), "tomorrow": L("jutro", "tomorrow")}},
            "price": {"options": {"total": L("cena całkowita", "total price"), "energy": L("tylko energia", "energy only"), "distribution": L("tylko dystrybucja", "distribution only")}},
        },
        "entity": {"sensor": {
            "total_price": {"name": L("Cena całkowita", "Total price")},
            "energy_price": {"name": L("Cena energii", "Energy price")},
            "distribution_price": {"name": L("Cena dystrybucji", "Distribution price")},
            "next_total_price": {"name": L("Cena całkowita – następny okres", "Next total price")},
            "zone": {"name": L("Strefa taryfowa", "Tariff zone"), "state": zone_states},
            "fixed_monthly_cost": {"name": L("Opłaty stałe miesięcznie", "Fixed monthly charges")},
            "reference_price": {"name": L("Cena odniesienia", "Reference price")},
            "price_score": {"name": L("Odchylenie ceny", "Price deviation")},
            "window_median": {"name": L("Mediana ceny w oknie", "Window median price")},
            "price_level": {"name": L("Poziom ceny", "Price level"), "state": levels},
            "charge_target": {"name": L("Docelowe naładowanie", "Charge target")},
        },
        "binary_sensor": {
            "cheap_now": {"name": L("Tani prąd teraz", "Cheap now")},
            "expensive_now": {"name": L("Drogi prąd teraz", "Expensive now")},
        }},
        "services": {"find_window": {
            "name": L("Znajdź okres cenowy", "Find price window"),
            "description": L("Zwraca początek i koniec najtańszego (lub najdroższego) okresu o zadanej długości. Użyj z response_variable.", "Returns start and end of the cheapest (or most expensive) window of the given length. Use with response_variable."),
            "fields": {
                "config_entry_id": {"name": L("Taryfa", "Tariff"), "description": L("Wymagane, gdy skonfigurowano kilka taryf.", "Required when several tariffs are configured.")},
                "duration": {"name": L("Długość [h]", "Duration [h]"), "description": L("Zaokrąglana w górę do pełnych slotów cenowych.", "Rounded up to whole price slots.")},
                "mode": {"name": L("Tryb", "Mode"), "description": L("Najtańszy lub najdroższy.", "Cheapest or most expensive.")},
                "period": {"name": L("Zakres", "Range"), "description": L("Od teraz (do końca znanych cen), dziś albo jutro.", "From now, today or tomorrow.")},
                "contiguous": {"name": L("Ciągły", "Contiguous"), "description": L("Wyłączone: N najlepszych godzin w dowolnych miejscach.", "Off: the N best slots anywhere.")},
                "price": {"name": L("Cena", "Price"), "description": L("Która cena decyduje.", "Which price to rank.")},
                "start_after": {"name": L("Nie wcześniej niż", "Not before"), "description": L("Okres nie może zacząć się wcześniej.", "Window may not start earlier.")},
                "end_before": {"name": L("Zakończ przed", "End before"), "description": L("Okres musi się skończyć do tej chwili.", "Window must end by then.")},
            },
        }},
    }

en, pl = build("en"), build("pl")
base = "custom_components/pl_energy_tariff/"
for path, d in ((base + "strings.json", en), (base + "translations/en.json", en), (base + "translations/pl.json", pl)):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2); f.write("\n")
print("ok", len(dist_keys), len(energy_keys))
