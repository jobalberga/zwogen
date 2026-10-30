# Onderzoek naar andere Volkswagen-toegang

Onderzocht op 30 oktober 2026 voor één Nederlandse Volkswagen Passat GTE uit 2020, met een gewone stopcontactlader. Doel: via een telefoon een eenmalige laadstart kiezen, standaard 00:00, zonder een vaste serverhuur of nieuwe laadpaal.

**Actuele budgetkeuze:** geen maandabonnement voor laadbediening. De betaalde Smartcar-route is daarmee geen voorkeursoplossing. Het account staat op Free. Het [Home Assistant-onderzoek](HOME-ASSISTANT.md) beschrijft waarom een andere planner de ontbrekende VW-toegang niet opheft en welke gratis routes nog niet zijn bewezen. Het onderstaande commerciële onderzoek blijft achtergrondinformatie.

## Resultaat

Er zijn commerciële voertuig-API's waarmee een eigen planner technisch mogelijk kan zijn. Smartcar is een concrete kandidaat met een beschreven ontwikkelaarsroute. Enode is eveneens een kandidaat, maar toegang tot echte voertuigen moet eerst worden goedgekeurd. De eigenaar heeft inmiddels een geslaagde Volkswagen-koppeling bij Smartcar laten zien. Het dashboard meldt nog **No permissions** voor laadgegevens en **Control EV Charge** staat uit. Zie [de Smartcar-instructies en veilige leescontrole](SMARTCAR.md) voor het vervolg. Er is nog geen laadstart/stop voor deze auto bevestigd, geen nieuwe voertuigadapter in de website geactiveerd en geen fysieke laadproef uitgevoerd. Het getoonde prijsblad biedt nieuwe kosteninformatie; ook die staat in de Smartcar-instructies.

De leverancier van Vattenfalls directe autokoppeling is nog niet geïdentificeerd. De eigenaar bevestigt dat Vattenfall de Passat zelf kan aansturen en beschrijft een koppelprocedure bij de ontgrendelde auto met VIN. Dat is bewijs van een andere werkende toegang voor zijn gebruik, maar het identificeert geen API-leverancier en bewijst niet dat dezelfde toegang beschikbaar is voor een particuliere ontwikkelaar.

Vattenfalls eigen detailpagina's en de detailpagina's van Enode en Smartcar konden vanuit deze onderzoeksomgeving niet worden geopend: de netwerkproxy weigert die bestemmingen. De onderstaande bevindingen komen uit de genoemde openbare SDK's en integraties. Daardoor zijn een actuele prijsofferte, de volledige compatibiliteitstabel en Vattenfalls leveranciersverklaring nog open punten.

Om de exacte Vattenfall-route te identificeren is de leveranciersnaam uit de privacy-/toestemmingstekst of een antwoord van Vattenfall nodig. Conceptvraag; niet verstuurd:

> Uw Slim Laden-functie kan mijn Passat GTE uit 2020 rechtstreeks bedienen, ook met een gewone stopcontactlader. Bij koppeling moest ik bij de ontgrendelde auto staan en het VIN opgeven. Welke technische partij verzorgt deze voertuigkoppeling? Biedt u of die partij een interface voor persoonlijk gebruik waarmee ik een eenmalige laadpauze en hervatting om een gekozen tijd kan instellen? Als dat alleen via uw app kan: kan ik daarin laden vóór 00:00 uitsluiten zonder een dagelijks terugkerend uitstel?

| Route | Wat is aangetoond | Wat ontbreekt voor deze planner |
| --- | --- | --- |
| Huidige CarConnectivity VW-connector | De eerste VW-aanmeldstap geeft in Cloud Shell HTTP 403 vóór het versturen van gebruikersgegevens. | Werkende aanmelding; deze route is nu onbruikbaar. |
| Vattenfall | De eigenaar meldt directe bediening van zijn Passat met een stopcontactlader. | Leverancier, externe interface, voorwaarden en mogelijkheid van een gekozen eenmalige starttijd. |
| Smartcar | Officiële SDK beschrijft registratie van een eigen app en toestemming per voertuig. Een onderhouden Home Assistant-integratie implementeert start/stop; er is een gebruikersmelding van werkende laadbediening op een betaald account. | Expliciete bevestiging van `control_charge`/laadstart en laadstop voor Passat GTE 2020, Nederland, plus actuele prijs en productierechten. |
| Enode | Officiële LinkKit-SDK bestaat. Openbare persoonlijke integraties beschrijven aparte sandbox- en productietoegang en een API voor laadplanning. | Productietoegang voor één particulier voertuig, laadcommando's voor deze Passat, kosten en voorwaarden. |
| Legacy Car-Net/MBB | Experimentele commandoroute voor oudere MQB-auto's, waaronder Passat GTE, wordt onderzocht. | Betrouwbare ondersteuning: de beheerder meldt juist weigeringen bij de B8 GTE's vanaf 2020 in de testdiscussie. |
| VW EU Data Act | Levert voertuiggegevens. De connector documenteert uitdrukkelijk dat geen commando's mogelijk zijn. | Kan deze laadplanner niet uitvoeren. |

## Smartcar: eerste kandidaat om toegang te toetsen

De [officiële Python-SDK](https://github.com/smartcar/python-sdk) beschrijft het registreren van een eigen toepassing met client-ID, client-secret en callbackadres. De bestuurder verleent vervolgens per voertuig toestemming. De SDK staat in onderhoudsmodus en wordt voor nieuwe integraties vervangen door directe HTTP-aanroepen; gebruik de actuele API bij een eventuele implementatie.

De [Home Assistant-integratie](https://github.com/wbyoung/smartcar) beschrijft onder meer de toestemming **Control charging (start/stop & target charge)** en implementeert een laadschakelaar. De documentatie zegt expliciet dat functies afhangen van model, bouwjaar, land, accountplan en toestemming. Een Volkswagen ID.4 wordt als voorbeeld getoond; dat bewijst geen ondersteuning van de Passat GTE. Een [gebruikersmelding](https://github.com/wbyoung/smartcar/issues/110) meldt werkende laadbediening met een betaald Smartcar-account, maar is geen proef met onze auto.

Controlepunten vóór er code wordt aangepast:

1. [Compatibiliteit](https://smartcar.com/product/compatible-vehicles): specifiek Volkswagen Passat GTE, 2020, Nederland, inclusief laadstart én laadstop. Alleen accustatus kunnen lezen is onvoldoende.
2. [Tarieven](https://smartcar.com/pricing#pricing): welk plan laat echte laadcommando's toe voor één voertuig? Een gratis ontwikkelaccount garandeert dat niet.
3. Productietoegang en toestemming: is persoonlijk gebruik toegestaan en kan deze auto daadwerkelijk worden gekoppeld?
4. Eén gecontroleerde stop/start-proef met actuele statusbevestiging. Pas daarna de bestaande worker aanpassen.

De huidige planner controleert tijdens een actieve planning ongeveer elke drie minuten op onverwacht hervatten. Dat verbruik moet bij een eventuele betaalde API opnieuw worden begroot. Communitydocumentatie noemt gratis quota, maar die zijn hier niet als actueel of voldoende bevestigd. Met minder statusaanvragen of webhooks veranderen ook de actualiteit en bevestigingstijden; neem bestaande garanties dus niet automatisch over.

Conceptvraag om ondersteuning en prijs te laten bevestigen; niet verstuurd:

> Ik wil uitsluitend mijn eigen Volkswagen Passat GTE uit 2020 in Nederland bedienen. Hij laadt met een gewone 230V-stopcontactlader. Ondersteunt uw huidige productie-API voor deze auto laadstart en laadstop, plus kabelstatus, laadstatus en het tijdstip van die status? Kan ik als particulier één voertuig koppelen, welk abonnement is daarvoor nodig en wat zijn de kosten? Mijn doel is een eenmalige laadpauze met een gekozen hervattingstijd, doorgaans 00:00. Zijn er bijzonderheden bij het koppelen of bij de actualiteit van statusupdates?

## Enode: productieaccount is de eerste drempel

De [officiële Enode LinkKit-SDK](https://github.com/enode/enode-link-ios) verwijst naar [Enodes ontwikkelaarsdocumentatie](https://developers.enode.com/docs/link-sdks). Dat bevestigt dat apps een Enode-koppelstroom kunnen integreren, maar niet wie Vattenfalls leverancier is.

De onafhankelijke integratie [Enode-for-HA](https://github.com/drlauridsen/Enode-for-HA) waarschuwt expliciet dat echte voertuigen **productietoegang van Enode** vereisen, dat die niet vanzelf aan individuele gebruikers wordt gegeven en dat gratis voortzetting niet gegarandeerd is. De publieke sandbox is daarom geen bewijs van toegang tot de echte auto.

Het openbare project [solar-charge-relay](https://github.com/peterkoczan/solar-charge-relay) beschrijft laadplanning en uitvoering via Enode. De quickstart gebruikt sandbox-auto's en noemt een verkoopovereenkomst als voorwaarde voor productie. Het is een voorbeeld van een mogelijke architectuur, geen geverifieerde oplossing voor deze Passat.

Een gebruiker noemt [Tibber met Enode als andere VW-toegang](https://github.com/robinostlund/homeassistant-volkswagencarnet/issues/977). Dit is een praktijkmelding, geen officiële verklaring over Vattenfall. Vraag eerst of Enode persoonlijk gebruik met deze auto en laadcommando's toestaat en wat dat kost; schrijf vóór die bevestiging geen vervangende worker.

## Legacy MQB/MBB is geen betrouwbare uitweg voor dit bouwjaar

In [de MBB-testdiscussie](https://github.com/its-me-prash/vwgroup-connect-ha/issues/584) noemt de beheerder Golf GTE en Passat GTE als doelgroep. De route is expliciet experimenteel. In een recente correctie wordt gemeld dat de B8 GTE's vanaf 2020 in die discussie dezelfde weigering van de lijst met toegestane acties krijgen. Ook bij enkele oudere auto's die die stap wel passeerden, werd de uiteindelijke actie geweigerd.

Dit bewijst niet dat ieder exemplaar onmogelijk is, maar levert geen basis om de huidige planner door deze route te vervangen of de eigenaar om een S-PIN te vragen voor nog een onbewezen integratie.

## Wat met de bestaande website kan worden hergebruikt

Als een leverancier productiebediening voor deze auto bevestigt, kunnen de telefooninterface, tijdkeuze, eenmalige planning en een deel van de Google Cloud-inrichting blijven dienen. De voertuigadapter, toestemming/tokens, statusverversing en eventuele webhooks moeten dan worden aangepast aan de leverancier. Voorlopig blijft [de bestaande VW-koppeling geblokkeerd](VW-STATUS.md).

Er is geen leverancier gecontacteerd, geen nieuw account aangemaakt, geen betaald plan gekozen en geen voertuiggegevens naar Smartcar of Enode gestuurd. De uiteindelijke leverancier van Vattenfall en de goedkoopste werkende route zijn nog niet vastgesteld.
