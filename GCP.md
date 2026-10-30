# Website op Google Cloud

Deze versie gebruikt Cloud Run voor de website en een aparte private laadwerker, Cloud Tasks voor korte taken en Firestore voor de planning. De website blijft op je telefoon werken. Er draait geen Python-planner op de achtergrond. Beide Cloud Run-services mogen naar nul instanties schalen.

De installatie is voorbereid en lokaal getest. Er is nog geen Google Cloud-project gebruikt, geen publieke website aangemaakt en geen echt VW-account gekoppeld. De eerste cloudinstallatie, echte taakaflevering met Google-identiteit en een fysieke pauze/start-test blijven nodig.

## Wat je eerst zelf aanmaakt

1. Open [Google Cloud Console](https://console.cloud.google.com/) met je eigen Google-account.
2. Maak een **nieuw, leeg project** aan, bijvoorbeeld met de naam `Na de spits`. Noteer de **project-ID**; die is vaak langer dan de naam.
3. Koppel een factureringsaccount. De diensten hebben gebruikstarieven. Dit is geen garantie op nul euro of een vast laag maandbedrag.
4. Controleer de actuele tarieven en maak bij **Billing → Budgets & alerts** een kleine budgetmelding aan, bijvoorbeeld voor een paar euro per maand. Een melding stopt de facturering niet automatisch.
5. Open **Cloud Shell** via het terminalpictogram bovenaan de console. Dit gebruikt jouw eigen cloudtoegang. Deel geen wachtwoorden, sleutelbestanden of tokens in de chat.

Gebruik een apart project voor deze app. Het installatiescript gaat uit van een nog niet bestaande standaard-Firestore-database. Het overschrijft geen andere database, maar zal bij een bestaande database om handmatige configuratie/import vragen.

## Bestanden ophalen en installeren

Voer dit uit in je eigen Cloud Shell:

```sh
git clone --branch codex/passat-midnight https://github.com/jobalberga/zwogen.git
cd zwogen
python3 tools/deploy_gcp.py JOUW-PROJECT-ID
```

Vervang `JOUW-PROJECT-ID` door de echte project-ID. Dit laatste commando maakt nog niets aan. Lees de uitleg en controleer of `gcloud` en Terraform (minimaal 1.6) aanwezig zijn. Voor de offline infrastructuurtests is Terraform 1.7 of nieuwer nodig. Het script schakelt bij installatie de benodigde API's in; de gebruiker heeft projectbeheerrechten en toegang tot het gekoppelde factureringsaccount nodig.

Om de gebruiksafhankelijke diensten daadwerkelijk aan te maken:

```sh
python3 tools/deploy_gcp.py JOUW-PROJECT-ID --apply
```

Het script bereidt eerst accounts, opslag, queue en lege Secret Manager-items voor. Daarna vraagt het in de terminal om een apart app-wachtwoord, VW-e-mailadres, VW-wachtwoord en VIN. Wachtwoorden verschijnen niet tijdens het typen. Deze waarden gaan via standaardinvoer naar Secret Manager: niet naar GitHub, Terraform-state, commandoargumenten of een lokaal configuratiebestand. Bestaande geheime configuraties worden behouden.

Daarna wordt de container in jouw project gebouwd en worden de services gestart met het exacte image-digest. De scriptuitvoer eindigt met het HTTPS-adres van je website. Google kan vragen om toegang tot je GitHub-repository tijdens het klonen; gebruik de gebruikelijke GitHub-toegang, geen token in deze chat.

De standaardregio is `europe-west1` (België). De database, buckets en geheime configuratie worden in die regio geplaatst. De website gebruikt de Nederlandse tijdzone voor de tijdkeuze. Een regio kies je bij de eerste installatie; wijzig die niet achteraf zonder een migratieplan.

## Eerste controle

1. Open het HTTPS-adres op je telefoon en log in met het app-wachtwoord.
2. De eerste statusaanvraag zet een veilige achtergrondtaak klaar om de echte auto op te halen. Wacht op accustand, kabelstatus en een recente meettijd van VW.
3. Sluit de kabel aan, kies bij **Starten om** de gewenste tijd en druk op de planningsknop.
4. Controleer ook in de VW-app dat het laden is gepauzeerd. Een verzonden opdracht is nog geen bevestiging.
5. Controleer de eerste geplande start en de status daarna. Pas na deze proef is de koppeling met jouw auto bewezen. Extra verificatie of gewijzigde voorwaarden bij Volkswagen kunnen de onofficiële koppeling verhinderen.

De telefoon mag dicht. Een start kan iets later zijn door koude starts, wachtrijaflevering of verwerking door Volkswagen; dit is geen realtime garantie op de exacte seconde.

## Wat er op de achtergrond gebeurt

- Elke taak bevat alleen een willekeurig taak-ID. De server leest de bewaarde planning en controleert tijdstip, annulering, laatste uitvoertijd en een tijdelijke uitvoervergrendeling.
- De opdracht en het volgende taakbericht worden samen in één Firestore-document bewaard met een atomische versievergelijking. Een bericht wordt pas na die opslag naar Cloud Tasks gestuurd. Mislukt die verzending, dan blijft de intentie bewaard.
- Een afgeschermde Cloud Scheduler-herstelcontrole draait elke drie minuten. Die leest alleen de planning en herstelt ontbrekende of vastgelopen taken. Zonder actieve planning haalt deze controle geen VW-status op.
- Bij een actieve planning controleert een korte taak de auto ongeveer elke drie minuten. Dit bewaart de eerdere controle op onverwacht hervatten vóór de geplande tijd. Deze taken veroorzaken meer uitvoeringen dan alleen één nachtelijke start; ze tellen mee in de gebruikskosten.
- Dubbele of oude berichten mogen geen nieuwe logische opdracht uitvoeren. Na een onduidelijk netwerkresultaat kan dezelfde expliciete start- of stopopdracht worden herhaald; het is nooit een toggle.
- Een uitvoervergrendeling duurt vijf minuten. De daadwerkelijke VW-stap draait in een apart proces dat zelf na 190 seconden afbreekt en door het bovenliggende proces na maximaal 200 seconden wordt beëindigd. Hierdoor kan lokale Python-code niet na het verlopen van zijn vergrendeling alsnog een nieuwe opdracht verzenden. Een al door VW ontvangen opdracht kan bij VW wel later worden verwerkt.
- Bij annuleren wordt het huidige taak-ID ongeldig. Een al begonnen opdracht kan niet worden teruggehaald; tijdens verwerking weigert de app annuleren en vraagt later opnieuw te proberen. Annuleren hervat het laden niet.
- De oorspronkelijke grenzen blijven: drie pogingen voor een mislukte laadopdracht, tien minuten voor bevestiging en een startvenster van één uur. Daarna wordt geen volgende dag geprobeerd.

## Beveiliging

De website is publiek bereikbaar, maar bediening en status vereisen het app-wachtwoord. Sessiecookies zijn `Secure`, `HttpOnly` en `SameSite=Strict`. CSRF-bescherming en een opgeslagen limiet op inlogpogingen blijven actief. Deze bescherming is lokaal getest; er is geen onafhankelijke penetratietest uitgevoerd.

De laadwerker is afgeschermd met Cloud Run IAM. Alleen de taakidentiteit krijgt invoke-rechten. Daarnaast controleert de toepassing het door Google ondertekende identiteitstoken, het audience en de verwachte serviceaccountidentiteit. De herstelcontrole gebruikt dezelfde identiteit. Een openbaar gemaakte worker zou daardoor nog steeds geen anonieme laadopdrachten accepteren, maar de IAM-afscherming moet behouden blijven.

De website heeft geen leesrechten op het VW-geheim of de tokenbucket. Alleen de laadwerker heeft die rechten. VW-tokens staan in een bucket die publieke toegang verbiedt; tijdens uitvoering worden ze kort in een privémap geladen. De sleutel in de oorspronkelijke bibliotheek is geen vervanging voor deze toegangsbeperking. Cloudbeheerders met voldoende rechten kunnen de gegevens nog steeds lezen; beveilig dus ook je Google-account.

Er worden geen serviceaccountsleutels gedownload. De services gebruiken hun eigen Google-identiteit. Geheime waarden staan niet in Terraform; alleen resourceverwijzingen. Bewaar Terraform-state en het deploymentbestand toch privé en commit ze niet.

## Kosten en grenzen

Er is geen voortdurend betaalde minimuminstantie. Er zijn wel gebruikskosten mogelijk voor Cloud Run, Cloud Tasks, Firestore, Cloud Scheduler, Secret Manager, Storage, Artifact Registry en builds/logs. Gratis quota kunnen een deel opvangen; de volledige actuele prijs en accountvoorwaarden zijn hier niet bevestigd. Neem geen bedrag van nul of één euro als garantie.

Beide services zijn beperkt tot maximaal één instantie, de queue verstuurt maximaal één taak tegelijk en de app begrenst retries. Dit beperkt verbruik, maar is geen harde eurogrens. Ook misbruik van een openbaar webadres kan kosten veroorzaken. Cloud Build-bronbestanden en buildlogs worden na zeven dagen opgeruimd; recente images worden bewaard. Oude ingeschakelde secretversies kunnen na wachtwoordrotatie blijven meetellen in de kosten.

## Bijwerken, stoppen en gegevens bewaren

Haal de nieuwe code op en voer hetzelfde `--apply`-commando vanuit dezelfde checkout uit. De bestaande services blijven in de bootstrapfase behouden; geheimen worden niet overschreven. Bewaar `infra/gcp/terraform.tfstate` en `deployment.auto.tfvars.json` in je eigen Cloud Shell. Bij verlies ervan zijn handmatige imports nodig voordat je opnieuw Terraform toepast.

Voor nieuwe wachtwoorden gebruik je Secret Manager. Herstart/implementeer daarna de webservice opnieuw zodat alle instanties de nieuwe sessieconfiguratie gebruiken. Schakel oude versies pas uit nadat geen actieve instantie ze meer nodig heeft.

Om de app buiten gebruik te stellen: annuleer eerst de laadopdracht, pauzeer de hersteljob en de Cloud Tasks-queue en verwijder vervolgens de Cloud Run-services. De auto hervat daardoor niet automatisch; controleer de VW-app. Verwijderen van alleen de website stopt bewaarde achtergrondtaken niet. Database en tokenbucket worden niet stilzwijgend vernietigd. Opgeslagen resources kunnen blijven meetellen totdat je ze bewust opruimt.

## Lokale verificatie

```sh
.venv/bin/python -m unittest discover -v
terraform -chdir=infra/gcp init -backend=false
terraform -chdir=infra/gcp validate
terraform -chdir=infra/gcp test
```

De Terraform-tests gebruiken mock-providers en maken niets aan. De emulator-integratietests draaien alleen als `FIRESTORE_EMULATOR_HOST` expliciet is ingesteld. Zij controleren echte atomische databasebewerkingen met een testauto en een vervangende takenwachtrij. Beheerde taakaflevering, echte Google-identiteiten en de fysieke auto moeten na installatie nog worden getest.

Bij deze ombouw zijn 70 Python-tests met de echte lokale Firestore-emulator uitgevoerd zonder skips of fouten. De infrastructuur valideert tegen de vastgezette officiële Google-providers; de mock-beveiligingstest slaagt. Een gebouwde container is gestart in beide cloudmodi, met echte HTTP-inlogcontrole en een Firestore-emulator; de managed queue was in die opstarttest vervangen. Publieke Cloud Run-TLS, echte Google-identiteitstokens en de fysieke auto zijn daarmee niet gevalideerd.
