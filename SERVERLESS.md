# Hosting zonder voortdurend draaiende server

Onderzocht op 30 oktober 2026 voor één Passat en één gebruiker. Er is niets gepubliceerd, geen cloudaccount aangemaakt en geen opdracht naar Volkswagen gestuurd. Dit document beschrijft de hostingkeuze. De cloudombouw is inmiddels geïmplementeerd en lokaal getest; zie [GCP.md](GCP.md). De eerste cloudinstallatie en VW-test blijven nog nodig.

## Advies

Uitgangspunt: geen vast serverabonnement; een factureringsaccount en eventuele kleine gebruikskosten zijn toegestaan. Daarmee is **Google Cloud Run + Cloud Tasks + Firestore de voorkeursroute**. De bestaande Python-koppeling kan behouden blijven, wat de noodzaak om VW-authenticatie opnieuw te bouwen beperkt. De ombouw staat nu klaar, met de lokale testgrenzen beschreven in GCP.md. De volledige actuele prijs moet vóór het aanmaken van diensten worden gecontroleerd.

## Vergelijking

Er zijn twee zinvolle routes:

1. **Bestaande Python-koppeling behouden:** Google Cloud Run met Cloud Tasks en een externe database. De webservice en laadwerker kunnen stoppen als er geen verzoeken zijn. Dit is mijn technische voorkeur wanneer een factureringsaccount en eventuele kleine gebruikskosten acceptabel zijn. De actuele totale prijs kon hier niet worden bevestigd.
2. **Uitsluitend geverifieerd gratis hosting onderzoeken:** Cloudflare Workers Free met D1 en een vaste Cron Trigger. De gratis onderdelen zijn bevestigd in de officiële documentatie. De huidige VW-koppeling en wachtwoordcontrole zijn nog niet geschikt bevonden voor deze omgeving; een werkende gratis versie is dus niet aangetoond.

Een vast abonnement van circa zeven euro is geen technische vereiste voor deze app. Een gegarandeerde prijs van nul euro voor een werkende, betrouwbaar gekoppelde app is evenmin aangetoond.

| Route | Kosten die hier zijn bevestigd | Passend bij de bestaande code | Nog nodig |
| --- | --- | --- | --- |
| Cloudflare Workers Free + D1 + Cron | Gratis binnen gepubliceerde quota; betaald Workers-plan begint volgens de bron bij $5 per maand | Python draait hier via WebAssembly; geen gewone Linux-server. Aanpassen en toetsen van VW-koppeling, opslag, planning en inloggen nodig | Voltooide compatibiliteitsproef, echte CPU-metingen en VW-test |
| Google Cloud Run + Cloud Tasks + Firestore | Actuele tariefpagina's waren vanuit deze omgeving niet bereikbaar. Geen geverifieerde maandraming | Linux-container kan de bestaande Python-bibliotheek behouden. SQLite en achtergrondthread moeten worden vervangen | Tariefcontrole, factureringsaccount, taak- en database-integratie, test met VW |
| AWS Lambda + EventBridge Scheduler + DynamoDB | Actuele tariefpagina's waren vanuit deze omgeving niet bereikbaar. Gratis quota, accountvoorwaarden en bijkomende kosten nog controleren | Python-werker past technisch. Webverzoeken moeten naar Lambda worden vertaald; SQLite en lokale tokens kunnen niet permanent blijven | Idem, plus AWS-configuratie en een Lambda-webadapter |

## Cloudflare: aantoonbaar gratis onderdelen

De officiële bronbestanden vermelden:

- Workers Free: 100.000 verzoeken per dag, met maximaal 10 ms CPU-tijd per uitvoering. Die CPU-grens geldt ook voor een Cron Trigger. Netwerk-wachttijd telt niet als CPU-tijd.
- D1 Free: 5 miljoen gelezen rijen en 100.000 geschreven rijen per dag; 5 GB opslag in totaal. Queries en indexgebruik bepalen het werkelijke rijverbruik.
- Bij overschrijding van de gratis D1-limieten worden opdrachten geweigerd tot de dagelijkse reset of totdat ruimte wordt vrijgemaakt. Dit kan een laadopdracht verhinderen; een gratis quota is geen beschikbaarheidsgarantie.
- Workers ondersteunt geheime bindings voor gevoelige waarden en geplande uitvoeringen via Cron Triggers.
- Een `workers.dev`-adres is beschikbaar voor persoonlijk gebruik. Cloudflare Access kan de toegang tot zo'n adres afschermen. Aanvullende account- en Access-voorwaarden moeten bij de inrichting worden gecontroleerd.

Een vaste trigger elke minuut geeft 1.440 controlemomenten per dag. Dat is weinig naast de genoemde verzoekquota, maar zegt niets over CPU-verbruik, VW-authenticatie of de werkelijke timing. De geselecteerde datum en tijd moeten in de database staan als een UTC-tijdstip. Een opdracht wordt alleen uitgevoerd nadat dat tijdstip is bereikt.

De trigger wordt eenmaal ingesteld. Het is niet verstandig de Cron-configuratie bij elke klik aan te passen: wijzigingen kunnen volgens Cloudflare tot vijftien minuten nodig hebben om actief te worden. Tijdens elke uitvoering wordt gecontroleerd of een eenmalige opdracht klaarstaat. Dit is geen garantie dat laden op de exacte seconde begint; ook Volkswagen kan vertraagd reageren.

## Proef met de bestaande VW-bibliotheek

Er is buiten de app een tijdelijke Python Workers-proef gemaakt met `carconnectivity==0.11.11` en `carconnectivity-connector-volkswagen==0.10.6`. De proef probeert alleen imports en bundeling; hij bevat geen VW-gegevens en verstuurt geen auto-opdrachten.

Het gebruikte commando was `pywrangler deploy --dry-run`. Na het oplossen van een lokale toolversie-eis stopte de proef bij het ophalen van pakketten van `index.pyodide.org`, een bestemming die deze werkomgeving blokkeert. Daardoor is noch compatibiliteit noch incompatibiliteit van de VW-bibliotheek met Workers bewezen. Er is geen Worker uitgerold.

Los daarvan kunnen de huidige Waitress-server, SQLite-bestanden en voortdurend draaiende thread niet ongewijzigd als een Worker functioneren. De wachtwoordcontrole gebruikt scrypt en vergt bewust rekentijd. Dat moet apart worden getoetst aan de grens van 10 ms; alleen het aantal gratis verzoeken bekijken is onvoldoende. Een ander inlogsysteem mag de bescherming niet verzwakken. Een externe identiteitstoegang zoals Access is een mogelijke route, maar is nog niet geconfigureerd of getest.

Een meting van drie controles met het bestaande wachtwoordalgoritme gaf lokaal een mediaan van 82,7 ms CPU-tijd per controle. Dit is een Linux/CPython-meting, geen Workers-meting en geen bewijs van de precieze prestaties daar. Het onderstreept wel dat de inlogroute apart onderzocht moet worden voordat de gratis CPU-grens als haalbaar wordt beschouwd.

## Voorkeursontwerp bij behoud van Python

Google Cloud Run kan de website als HTTPS-service aanbieden. Een afzonderlijke private Cloud Run-werker voert de VW-opdrachten uit. Cloud Tasks kan die werker later aanroepen met een opgeslagen `schedule_time` en een identiteitstoken. Beide services moeten op nul minimuminstanties worden ingesteld; de werker draait alleen bij een opdracht of controle.

1. Na inloggen kiest de gebruiker een tijd. De server berekent de eerstvolgende startdatum in `Europe/Amsterdam`.
2. Een externe database bewaart de opdracht, versie, status en uiterste uitvoertijd. Een nieuwe taak vraagt de auto te pauzeren.
3. Een vervolgstap controleert of de auto een nieuwe bevestigende meting geeft. Daarna blijft een duurzame taak voor het gekozen startmoment bewaard. Monitoring tijdens de wachttijd en eventuele bevestigingscontroles zijn afzonderlijke korte taken.
4. De startwerker controleert vlak vóór de VW-opdracht opnieuw de tijd, opdrachtversie, annulering en uiterste uitvoertijd.
5. Dubbele afleveringen mogen geen tweede logische opdracht maken. Opslag en taakaanmaak vereisen foutafhandeling en herstel; alleen een timer in het geheugen is onvoldoende.

Cloud Tasks heeft in de actuele officiële SDK velden voor de uitvoertijd en OIDC-identiteit. Dit bevestigt de technische bouwstenen. Het bewijst geen prijs, gegarandeerde exacte afleverminuut of succesvolle VW-koppeling.

Bij AWS is hetzelfde model mogelijk: EventBridge Scheduler ondersteunt eenmalige `at(...)`-opdrachten, een tijdzone, retries en opruimen na uitvoering. De werker wordt met een beperkte IAM-rol aangeroepen. Ook hier blijven annulering, duplicaten en een uitvoerdeadline verantwoordelijkheid van de app.

## Beveiliging en kostenbeheersing voor de ombouw

- VW-inloggegevens en herbruikbare tokens blijven buiten HTML, JavaScript voor de browser, GitHub en taakberichten. Gebruik een beheerde geheime opslag en beperk welke serveridentiteit toegang heeft.
- De website gebruikt HTTPS. De laadwerker krijgt geen publiek bruikbare opdracht-URL; alleen de taakdienst mag hem aanroepen.
- Permanente gegevens horen in de database, niet op de tijdelijke schijf van een serverloze instantie. Bewaar alleen noodzakelijke autogegevens en voorkom tokens of ruwe providerantwoorden in logs.
- Behouw inlogbeveiliging, CSRF-bescherming, begrensde retries en het onderscheid tussen een verzonden en een door de auto bevestigde opdracht.
- Beperk instanties, taakfrequentie, retries en logbewaring. Een budgetmelding waarschuwt; het is geen harde bestedingslimiet. Controleer de kosten van de hele keten, inclusief database, geheimen, image-opslag, bouwen en netwerkverkeer.
- Ook deze oplossing gebruikt de onofficiële VW-koppeling. Authenticatie, eventuele extra verificatie en echt starten/stoppen moeten met het eigen account worden getest voordat erop wordt vertrouwd.

## Kostenraming die nog moet worden bevestigd

Voor het ontwerp kan worden gerekend met circa dertig planningen per maand, enkele duizenden korte achtergrondstappen en een beperkt aantal websitebezoeken. Het werkelijke VW-verkeer, de benodigde rekentijd, accountvoorwaarden, regio en bijkomende diensten bepalen of dat binnen gratis quota valt. Zonder actuele tariefcontrole en een gekoppelde proef is een bedrag van €0 of €1 per maand niet onderbouwd.

## Bronnen en grenzen van de controle

De Cloudflare-informatie is gelezen uit de officiële documentatiebron op GitHub. De AWS- en Google-functionaliteit is gecontroleerd in hun actuele officiële SDK-bronnen. De prijswebsites van AWS en Google werden door de netwerkproxy van deze werkomgeving geblokkeerd; dat is geen fout van de diensten en geen uitspraak over hun prijs.

- [Workers-prijzen, officiële bron](https://github.com/cloudflare/cloudflare-docs/blob/production/src/content/docs/workers/platform/pricing.mdx)
- [Workers-limieten, officiële bron](https://github.com/cloudflare/cloudflare-docs/blob/production/src/content/docs/workers/platform/limits.mdx)
- [D1-prijzen, officiële bron](https://github.com/cloudflare/cloudflare-docs/blob/production/src/content/partials/workers/d1-pricing.mdx)
- [D1-limieten en overschrijding, officiële bron](https://github.com/cloudflare/cloudflare-docs/blob/production/src/content/partials/d1/faq-pricing.mdx)
- [Cron Triggers](https://github.com/cloudflare/cloudflare-docs/blob/production/src/content/docs/workers/configuration/cron-triggers.mdx)
- [Workers Secrets](https://github.com/cloudflare/cloudflare-docs/blob/production/src/content/docs/workers/configuration/secrets.mdx)
- [Python-pakketten](https://github.com/cloudflare/cloudflare-docs/blob/production/src/content/docs/workers/languages/python/packages/index.mdx)
- [workers.dev en toegangsbeveiliging](https://github.com/cloudflare/cloudflare-docs/blob/production/src/content/docs/workers/configuration/routing/workers-dev.mdx)
- [Cloud Tasks-taaktijd, officiële SDK](https://github.com/googleapis/google-cloud-python/blob/main/packages/google-cloud-tasks/google/cloud/tasks_v2/types/task.py)
- [Cloud Tasks-authenticatie, officiële SDK](https://github.com/googleapis/google-cloud-python/blob/main/packages/google-cloud-tasks/google/cloud/tasks_v2/types/target.py)
- [EventBridge Scheduler, officiële SDK](https://github.com/boto/botocore/blob/develop/botocore/data/scheduler/2021-06-30/service-2.json)
- Te controleren vóór installatie: [Cloud Run-tarieven](https://cloud.google.com/run/pricing), [Cloud Tasks-tarieven](https://cloud.google.com/tasks/pricing), [Firestore-tarieven](https://cloud.google.com/firestore/pricing), [AWS Lambda-tarieven](https://aws.amazon.com/lambda/pricing/) en [EventBridge-tarieven](https://aws.amazon.com/eventbridge/pricing/).
