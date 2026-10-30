# Home Assistant en gratis laadbediening

Actuele voorkeur: geen maandabonnement voor laadbediening. Het Smartcar-account staat op **Free**. De auto is gekoppeld, maar er zijn nog geen laadrechten of werkende laadcommando's bevestigd. Het prijsblad toont voertuigcommando's bij **Build**; de gekozen signaalselectie wordt op Free geweigerd.

## Wat Home Assistant oplost

Home Assistant kan thuis een planning uitvoeren en een bediening op de telefoon bieden. Een cloudabonnement voor Home Assistant is daarvoor niet verplicht. Er moet wel een eigen apparaat blijven draaien. De Apple TV is een Apple Woning-hub, geen ondersteunde Home Assistant-server. Gebruik van de bestaande DS223j als Home Assistant-host vereist eerst controle van DSM, Container Manager en beschikbare capaciteit; Home Assistant is nog niet op deze NAS getest.

Home Assistant voegt geen toegangsrechten bij Volkswagen toe. Een andere planner of een andere host verandert de 403 van de gebruikte VW-aanmeldroute niet.

## Welke voertuigkoppeling kan hij gebruiken?

- **Smartcar:** de [Home Assistant-integratie](https://github.com/wbyoung/smartcar) gebruikt dezelfde Smartcar-dienst en dezelfde accountrechten als een eigen webapp. De broncode implementeert laadstart en laadstop. De documentatie zegt expliciet dat beschikbaarheid afhangt van voertuig, land, plan en toestemming. Home Assistant maakt betaalde Smartcar-functies dus niet gratis.
- **De oudere gratis VW-koppelingen:** deze gebruikten onofficiële VW-aanmeldroutes die door gewijzigde toegang bij VW zijn geraakt. De bekende 403 is geen probleem dat verdwijnt door Home Assistant te installeren. Zie [de VW-status](VW-STATUS.md).
- **VW Group Connect / legacy Car-Net-MBB:** er is [een experimentele commandoroute](https://github.com/its-me-prash/vwgroup-connect-ha/issues/584) voor sommige oudere MQB-auto's. De beheerder meldt in die discussie juist weigeringen bij de geteste B8 GTE's vanaf 2020. Dit is geen bewezen gratis oplossing voor onze Passat.
- **VW EU Data Act:** alleen voertuiggegevens; geen laadstart of laadstop.

Een praktische overstap naar Home Assistant is daarom pas zinvol voor deze laadtaak als eerst een werkende voertuigkoppeling is bewezen. Een nieuwe NAS-installatie bouwen terwijl dezelfde toegang ontbreekt, lost de laadbediening niet op.

## Gratis routes die nog onderzocht kunnen worden

1. **De ingebouwde e-Manager/laadtimer van de Passat.** Controleer op de echte auto de mogelijkheden voor voorkeurtijden, minimumlading, vertrektijd en eenmalig activeren. Er is nog geen passende combinatie bevestigd die exact het gewenste gedrag geeft.
2. **Acties van de officiële VW-app in iPhone Opdrachten.** Alleen als de geïnstalleerde app echte acties voor laadstart en laadstop aanbiedt, is dit een kandidaat. Alleen de app openen is onvoldoende voor onbemande bediening terwijl de telefoon is vergrendeld. Beschikbaarheid van die laadacties is nog niet bevestigd.
3. **Tijdregeling bij de stroomtoevoer.** Dit vergt geschikte hardware voor langdurig EV-laden en controle dat de stopcontactlader vanzelf hervat zodra stroom terugkomt. Apple Woning en de Apple TV zouden de tijdregeling kunnen verzorgen; Home Assistant is daarvoor niet noodzakelijk. De bestaande laadkabel en schakeling zijn nog niet geïdentificeerd of getest.

Deze opties hebben geen aangetoonde betaalde voertuig-API nodig, maar zijn nog geen geteste vervanging van de huidige planner. Er is geen Home Assistant-installatie uitgevoerd en geen apparaat of abonnement aangeschaft.
