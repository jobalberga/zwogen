# Smartcar: eerst de gekoppelde auto en rechten controleren

De eigenaar heeft de Volkswagen via Smartcar succesvol gekoppeld met VIN en kilometerstand. Het huidige account is volgens de laatste controle **Free**; er is geen betaalde upgrade bevestigd. De verbinding heeft nog geen laadrechten en het publiceren van de eerdere signaalselectie wordt door het pakket geweigerd. De verleende voertuigrechten en het daadwerkelijk uitvoeren van laadcommando's moeten nog worden gecontroleerd.

De eigenaar wil geen maandabonnement voor deze laadbediening. Een betaalde upgrade past daarom niet bij de huidige voorkeur. Zie [de afweging met Home Assistant](HOME-ASSISTANT.md). De leescontrole hieronder blijft beschikbaar voor onderzoek; de website heeft nog geen Smartcar-voertuigadapter.

## Sleutels

Een **Application management token** is geheim. Als dit in een chat of screenshot zichtbaar is geweest, regenereer het token in Smartcar en bewaar het nieuwe token privé. De hieronder beschreven controle gebruikt dit token niet. Het **Client ID** is een identificatie; het **Client Secret** is geheim. Deel geen nieuwe geheimen in de chat of screenshots.

De nieuwe M2M-aanmelding gebruikt `POST https://iam.smartcar.com/oauth2/token` met Client ID, Client Secret en `grant_type=client_credentials`. Een voertuig moet al aan de toepassing zijn gekoppeld. De aanvraagstructuur en de v3-verbindingen/signalen zijn gecontroleerd aan de hand van de actuele openbare [Smartcar Home Assistant-integratie](https://github.com/wbyoung/smartcar); er is nog geen live test vanuit onze omgeving gedaan.

## Toestemmingen in het dashboard

Controleer **Configuration → Vehicle access** op toegang tot batterijgegevens (`read_battery`), laadstatus (`read_charge`) en laadbediening (`control_charge`). De exacte schermteksten kunnen verschillen. Als je de gevraagde rechten wijzigt, is een nieuwe toestemmingsronde via de Connect-link nodig voordat de bestaande voertuigverbinding die rechten heeft. Het inschakelen in de appconfiguratie alleen bewijst nog geen toestemming van de bestuurder.

Het getoonde scherm bevat een nog uitgeschakelde **Commands → Control EV Charge**. Schakel die optie in. Beperk **Signals** eerst tot **Charge.IsCharging** en **Charge.IsChargingCableConnected**. Publiceer de wijziging en doorloop de **Share Connect link** opnieuw om de extra toegang te verlenen. De Tesla in **Connect Preview** is een voorbeeld, geen geselecteerd voertuig.

Bij het publiceren van de eerdere selectie verscheen **Your plan does not include all of the selected signals. Please upgrade to enable access.** Dit bevestigt een beperking van het huidige pakket voor minstens één van de geselecteerde signalen. Welke precies is nog niet vastgesteld. Accupercentage is voor de planning optioneel, en de eenvoudige ja/nee-laadstatus kan de uitgebreidere laadstatus vervangen. Of de minimale twee signalen in het huidige pakket zitten, moet nog worden vastgesteld; schaf daarvoor niet op basis van een aanname een tweede upgrade aan. Als ook deze selectie wordt geweigerd, controleer het actuele pakket en voeg de signalen afzonderlijk toe om de beperking te identificeren.

Een verleend `control_charge`-recht bewijst evenmin dat het accountplan en dit specifieke voertuig daadwerkelijk een commando uitvoeren. De eerste fysieke stop/start-proef blijft nodig wanneer de auto beschikbaar is en eventuele commandokosten zijn bevestigd.

## Veilige leescontrole in Cloud Shell

Maak in Smartcar bij **Configuration → API credentials → Generate new secret** een Client Secret aan. Bewaar het privé. Gebruik de nieuwe Client ID die met `client_` begint.

Voer in de bestaande Cloud Shell-checkout uit:

```sh
cd ~/zwogen
git pull --ff-only
python3 tools/diagnose_smartcar.py
```

Het script vraagt alleen in de terminal om Client ID en verborgen Client Secret. Het bewaart de sleutels of het toegangstoken niet op schijf en gebruikt ze niet als commandoargument. Er zijn geen extra Python-pakketten nodig.

De controle doet één tokenaanvraag, leest de live autokoppelingen en selecteert uitsluitend precies één echte auto. Zij toont de twee vereiste toestemmingen **read_charge** en **control_charge** en de optionele toestemming **read_battery**. Als de leesrechten ontbreken, worden bijbehorende signalen niet opgevraagd. Anders leest zij alleen laden ja/nee en kabel aangesloten ja/nee, inclusief eventuele meet- en ophaaltijden. Met `python3 tools/diagnose_smartcar.py --battery` kan ook het accupercentage expliciet worden getest, nadat toegang tot dat extra signaal is bevestigd. Er worden geen locatiegegevens of VIN opgevraagd en geen start-/stopopdrachten verstuurd. De leesaanvragen kunnen meetellen in het API-verbruik. Er zijn geen automatische retries.

De uitvoer tussen **SMARTCAR-CONTROLE** en **EINDE SMARTCAR-CONTROLE** bevat geen sleutels, voertuig-ID's, gebruikers-ID's of ruwe foutantwoorden en kan worden gebruikt om het vervolg te bepalen. Een ontbrekende toestemming, pakketbeperking en technische incompatibiliteit worden niet automatisch gelijkgesteld.

## Kosteninformatie uit het getoonde prijsblad

Het gedeelde Smartcar-prijsblad vermeldt **Free: $0, één verbonden voertuig, geen betaalkaart nodig**. Voor **Build** staat **vanaf $1,99 per voertuig/toepassing/maand**, met **100 voertuigcommando's per maand**, gedeeld over alle voertuigen van die toepassing. De voetnoot onderscheidt Build Basic, Advanced en Premium, en noemt eventuele extra kosten voor signalen en meer commando's.

Een succesvolle pauze en hervatting zijn normaal twee commando's; bij één sessie per dag is dat 60–62 per maand, vóór retries of extra pauzes. Dit is geen totaalprijsgarantie. Het benodigde pakket, signaalverbruik, eventuele belastingen en de aparte Google Cloud-kosten moeten worden vastgesteld voordat de planner op Smartcar gaat draaien. Alleen een gratis voertuigverbinding bevestigen is daarvoor onvoldoende.

Het huidige pakket is **Free**. Het getoonde prijsblad vermeldt de voertuigcommando's bij **Build**. Voordat een betaald pakket wordt gekozen, moet worden bevestigd welke Build-variant de benodigde laadcommando's én de minimale twee statussignalen bevat en welke uiteindelijke prijs daarbij hoort. Koppelen op Free is geen bevestiging dat laadbediening in dat pakket beschikbaar is.
