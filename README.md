# Na de spits

Een privéwebapp voor een Volkswagen Passat GTE uit 2020. Sluit de laadkabel aan en plan met één knop een **eenmalige start vanaf 00:00 uur Nederlandse tijd, in de komende nacht**. De app bedient de auto via Volkswagen; een slimme laadpaal is niet nodig. De interface werkt op een telefoon en kan aan het beginscherm worden toegevoegd.

## Wat werkt

- De planner vraagt de auto het laden te pauzeren, bewaart de eenmalige opdracht in SQLite en vraagt vanaf de eerstvolgende middernacht om te starten. De startdatum staat bij de starttijd. Ook een nieuwe opdracht die na 00:00 wordt gemaakt, kiest de eerstvolgende toekomstige middernacht. Een bestaande opdracht wordt op het opgeslagen tijdstip uitgevoerd.
- De opdracht blijft bewaard bij een serverherstart. De telefoon mag dicht. De server moet blijven draaien; een slapende gratis host of een statische website voldoet niet.
- De interface onderscheidt opdracht verzonden, pauze bevestigd, start bevestigd en fouten. Bevestiging vereist een VW-meting van ná het versturen van de opdracht. Onbekende en verouderde waarden worden niet als bevestiging gebruikt.
- Annuleren schrapt de automatische start en hervat het laden niet. Er is maximaal één actieve opdracht. Een gemist venster van een uur verloopt en wordt nooit de volgende dag uitgevoerd.
- Inloggen, sessiecookies, CSRF-bescherming en een aanhoudende limiet op mislukte inlogpogingen beschermen de bediening. De browser krijgt geen VW-wachtwoord, tokens of chassisnummer.

De eerdere ZWO-generator in `index.html` en `api/generate.py` is behouden. Deze nieuwe server biedt die bestanden niet aan.

## Online op je telefoon via Render

`render.yaml` beschrijft één Python-webservice met een permanente schijf in Frankfurt. **Dit gebruikt een betaald Starter-abonnement plus schijf; er is nog niets aangemaakt of betaald.** Controleer de actuele prijs in Render voordat je de service aanmaakt. Een account en toegang tot deze GitHub-repository zijn nodig.

1. Sla de appwijzigingen op in je GitHub-repository. Maak in [Render](https://dashboard.render.com/) een Blueprint aan vanuit die repository en kies de branch met deze bestanden.
2. Stel de vier gevraagde waarden **in de beveiligde hostinginstellingen** in:

   | Instelling | Betekenis |
   | --- | --- |
   | `APP_PASSWORD` | Een apart, sterk wachtwoord voor deze site, minimaal 12 tekens. |
   | `VW_USERNAME` | Het e-mailadres van het VW-account waarmee laden in de VW-app werkt. |
   | `VW_PASSWORD` | Het bijbehorende VW-wachtwoord. |
   | `VW_VIN` | Het chassisnummer van uitsluitend jouw Passat. |

3. Laat Render de service starten. Gebruik de HTTPS-URL die Render aanmaakt op je telefoon en log in met het **app-wachtwoord**. Een eigen domein is niet nodig. Op iPhone kun je via Delen → Zet op beginscherm een snelkoppeling toevoegen; op Android via het browsermenu.
4. Controleer eerst of echte accustatus, aangesloten kabel en een recente VW-meettijd worden getoond. Test daarna onder toezicht één pauze- en startcyclus terwijl je bij de auto bent. Pas na die controle is de koppeling met jouw auto bewezen.

De permanente schijf bevat de opdrachten, sessiesleutel en VW-tokens. Houd hem privé en bewaar hem bij herdeploys. Verwijderen van die schijf verwijdert ook openstaande opdrachten. Gebruik één service-instantie; de procesvergrendeling voorkomt twee planners op dezelfde schijf. `PORT` wordt door Render aangeleverd. Publiceer deze app uitsluitend achter HTTPS en laat `COOKIE_SECURE=1` staan.

### Volkswagen-koppeling

De integratie gebruikt de **onofficiële** [CarConnectivity Volkswagen-connector](https://github.com/tillsteinbach/CarConnectivity-connector-volkswagen). Dat laden in de VW-app werkt is een goed uitgangspunt, maar bewijst nog niet dat deze bibliotheek jouw account ondersteunt. Extra verificatie, verlopen toestemmingen of wijzigingen bij Volkswagen kunnen een koppeling verhinderen. De app accepteert geen toestemmingen of nieuwe voorwaarden namens je.

Een VW-wachtwoord in een proxy-placeholder is geen algemeen bruikbaar lokaal geheim: deze bibliotheek moet zelf de volledige authenticatiestroom kunnen uitvoeren. Gebruik op de uiteindelijke host de gewone beveiligde runtime-secretinstellingen. Zet wachtwoorden nooit in de repository, chat of logs. De bibliotheek slaat authenticatietokens op in de privédatamap; de ingebouwde versleuteling vervangt toegangsbeperking van die map niet.

Benodigde verbindingen zijn onder andere HTTPS naar `identity.vwgroup.io`, `emea.bff.cariad.digital` en de Volkswagen-loginomleidingen, en tijdens installatie naar PyPI. De volledige loginroute en eventuele extra bestemmingen kunnen pas met een gekoppeld account worden vastgesteld. TLS-controle blijft ingeschakeld. De app logt geen ruwe providerfouten of debug-antwoorden.

## Lokaal ontwikkelen

Python 3.12 en een Linux- of macOS-systeem zijn nodig (`fcntl` bewaakt de enkele planner). Het project gebruikt geen Node-build of database buiten SQLite.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# Maak je eigen .env op basis van .env.example; overschrijf geen bestaande .env.
set -a
. ./.env
set +a
.venv/bin/python -m passat_charge
```

`python -m passat_charge` start zowel de Waitress-webserver als de planner. Gebruik dit startcommando ook bij hosting; alleen `flask run` of een WSGI-import start de planner niet. De app start zonder VW-gegevens, maar toont dan duidelijk dat de auto niet gekoppeld is en weigert laadopdrachten. Een app-wachtwoord blijft verplicht. Alleen voor lokale HTTP-ontwikkeling mag `COOKIE_SECURE=0` worden gebruikt.

```sh
.venv/bin/python -m unittest discover -v
.venv/bin/python -m pip check
```

De tests gebruiken een vervangende auto en testen onder meer tijdzones, zomer- en wintertijd, uitblijvende bevestiging, offline herstel, begrensde retries, annuleren, dubbele opdrachten, serverherstart en toegangsbeveiliging. Adaptertests gebruiken ook de echte typen en laadcommando's uit de vastgezette CarConnectivity-versie zonder netwerk of echt account. Dit zijn geen tests op een fysieke auto.

## Grenzen van de planning

De server controleert VW-status ongeveer elke drie minuten; een startaanvraag gaat vanaf 00:00 uit. Het tijdstip volgt de Nederlandse kalender en houdt rekening met zomer- en wintertijd. VW en de auto kunnen die aanvraag vertraagd verwerken. Zonder netwerk of werkende VW-dienst kan de app de auto niet fysiek tegenhouden of inschakelen. Schakel concurrerende laad-/vertrektimers uit. De planner probeert een mislukte opdracht maximaal drie keer met drie minuten tussenruimte. Na tien minuten zonder nieuwe bevestigende meting wordt de opdracht als mislukt getoond; dat betekent niet dat een eerder verzonden commando onmogelijk nog aankomt.

Als laden vóór de geplande middernacht opnieuw wordt waargenomen, bijvoorbeeld na opnieuw inpluggen, vraagt de actieve planner opnieuw een pauze aan. Als pauzeren niet bevestigd wordt, controleer de VW-app: de website kan niet garanderen dat er vóór de starttijd geen stroom wordt afgenomen. Een stilgevallen server voert geen opdrachten uit; de website waarschuwt bij een ontbrekende planner of verbinding.

## Huidige verificatie

Lokale planning, webbediening en de adapter met bibliotheekobjecten worden geautomatiseerd getest. Een echt VW-account is nog niet gekoppeld, er zijn geen opdrachten naar jouw auto gestuurd en er is nog geen publieke hosting aangemaakt. De eerste echte laadtest en de productie-HTTPS-koppeling blijven onderdeel van ingebruikname.
