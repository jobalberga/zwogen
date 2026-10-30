# Volkswagen-koppeling geblokkeerd

Gecontroleerd op 30 oktober 2026. De website draait op Google Cloud en kan de achtergrondtaak uitvoeren. De gebruikte onofficiële Volkswagen-connector kan bij de eerste aanmelding geen aanmeldadres ophalen. Er is nog geen werkende voertuigkoppeling of fysieke laadtest bevestigd. Gebruik deze app momenteel niet om op een uitgestelde laadstart te vertrouwen.

## Vastgesteld

De controle vanuit Cloud Shell, met dezelfde connectorversie als de website, gaf:

```text
VW-aanmeldadres: HTTP 403; doorverwijzing=nee
AuthenticationError; bron=we_connect_session.py:125
```

Dit gebeurt bij `GET /user-login/v1/authorize`, voordat het e-mailadres of wachtwoord wordt verzonden. De fout bewijst dus niet dat de opgeslagen gegevens verkeerd zijn. De eigenaar kan met dezelfde gegevens in de browser bij myVolkswagen inloggen. De locatie en laadkabel van de auto spelen bij deze eerste aanmeldstap geen rol.

De actuele openbare broncode gebruikt nog dezelfde route als de vastgezette connector 0.10.6. Andere gebruikers melden dezelfde 403 buiten Google Cloud. Dit wijst op een beperking van deze Volkswagen-aanmeldroute; een overstap naar een NAS of andere hosting is geen aangetoonde oplossing. Er is geen werkende reparatie vastgesteld. De precieze serverconfiguratie van Volkswagen hebben we niet zelf kunnen inspecteren.

Bronnen:

- [Dezelfde aanmeldfout bij de Volkswagen-connector, issue 107](https://github.com/tillsteinbach/CarConnectivity-connector-volkswagen/issues/107).
- [Discussie over de gewijzigde Volkswagen-toegang](https://github.com/tillsteinbach/CarConnectivity/discussions/154).
- [Actuele aanmeldcode van de connector](https://github.com/tillsteinbach/CarConnectivity-connector-volkswagen/blob/main/src/carconnectivity_connectors/volkswagen/auth/we_connect_session.py).
- [VW EU Data Act-connector](https://github.com/mikrohard/CarConnectivity-connector-vw-eu-data-act#why-this-connector-exists): alleen gegevens lezen; geen laadstart of laadstop.

Een Data Act-koppeling vervangt daarom de gewenste laadbediening niet. Opnieuw installeren of steeds dezelfde aanmelding herhalen lost de vastgestelde blokkade niet op.

## Vattenfall als andere route

De eigenaar meldt dat Vattenfall de Passat zelf op afstand kan aansturen terwijl die met een gewone stopcontactlader laadt. Voor de Vattenfall-koppeling moest de eigenaar bij de ontgrendelde auto staan en onder meer het VIN opgeven. Dit is niet door ons op de auto getest. Het is wel reden om andere voertuigkoppelingen te onderzoeken voordat laadapparatuur wordt vervangen. De 403 hierboven bewijst uitsluitend dat de route van onze huidige connector wordt geweigerd, niet dat elke externe voertuigkoppeling onmogelijk is.

De fysieke controle lijkt bedoeld om het eigenaarschap vast te stellen. Daarmee is nog niet bekend welke technische leverancier, API of toegangsrechten Vattenfall vervolgens gebruikt. Het opnieuw ontgrendelen van de auto verandert de eerste aanvraag van onze connector niet: die aanvraag bevat geen VIN of gebruikersgegevens. Een aansluiting op de Vattenfall-route vereist eerst identificatie van de leverancier en een beschikbare interface voor voertuigbediening.

De volgende openbare InCharge-integraties zijn gecontroleerd, maar bieden geen aangetoonde oplossing voor deze directe voertuigbediening:

- [tgriek/incharge](https://github.com/tgriek/incharge): laadstations en verbruik uitlezen.
- [QuadNL/Vattenfall-InCharge-integration](https://github.com/QuadNL/Vattenfall-InCharge-integration): openbare laadpunten, accountgegevens en laadgeschiedenis.
- [Swopper050/py-incharge](https://github.com/Swopper050/py-incharge): Vattenfall-laadstations bedienen via een station-ID en laadpas; dit is geen bediening van een auto met een losse stopcontactlader.

De naam van de leverancier of de privacy-/toestemmingstekst bij de autokoppeling kan de juiste route identificeren. De leverancier, beschikbaarheid voor persoonlijk gebruik, kosten en ondersteuning voor een eenmalige gekozen starttijd zijn nog niet vastgesteld. De Vattenfall-voertuigkoppeling is nog niet in deze website geïntegreerd.

## Achtergrondtaken pauzeren

Voer in je eigen Cloud Shell uit, met de project-ID van de installatie:

```sh
gcloud scheduler jobs pause passat-recovery --location=europe-west1 --project=JOUW-PROJECT-ID
gcloud tasks queues pause passat-charging --location=europe-west1 --project=JOUW-PROJECT-ID
```

Dit pauzeert de herstelcontrole en de aflevering van laad- en statustaken. Een al begonnen taak kan nog afronden. De pauze zelf hervat of stopt het laden niet; controleer de auto in de officiële VW-app. Houd de laadwebsite gesloten terwijl de taken gepauzeerd zijn, zodat die geen nieuwe statusaanvragen opslaat. De cloudopslag en andere resources blijven bestaan en kunnen nog kosten veroorzaken. Deze pauze is geen beëindiging van de facturering.

Er is vanuit deze ontwikkelomgeving geen toegang tot het Google Cloud-project. De bovenstaande pauze is voorbereid, maar niet namens de eigenaar uitgevoerd.

## Vervolg

De webplanner is pas weer bruikbaar als een werkende, toegestane VW-koppeling is gevonden en de daadwerkelijke laadbediening is getest. Een alternatief is de ingebouwde laadtimer van de auto of geschikte laadapparatuur met tijdregeling. Daarmee ontstaat niet vanzelf de gewenste eenmalige bediening via deze website; controleer eerst de mogelijkheden en het gedrag van de gekozen oplossing.
