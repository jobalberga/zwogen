# Installatie op Synology

**De gebruikte VW-koppeling wordt momenteel geweigerd.** Deze NAS-installatie verhelpt dat niet. Zie eerst [de VW-status](VW-STATUS.md). Dit document beschrijft onze eigen webapp; voor de afweging met Home Assistant, zie [Home Assistant en gratis laadbediening](HOME-ASSISTANT.md).

Dit is de installatie voor gebruik op je thuiswifi, zonder betaald hostingabonnement. De NAS moet aan blijven en internettoegang hebben om Volkswagen te bereiken. Er is geen koppeling met de Apple TV nodig.

## Eerst controleren op de DS223j

Open DSM → **Package Center** en zoek **Container Manager**. Als dat pakket beschikbaar is, kan deze installatie worden gebruikt. Het image ondersteunt zowel ARM64 als x86-64: op de DS223j wordt de ARM64-versie van Python gebruikt. Ondersteuning en de geïnstalleerde DSM-versie moeten op je eigen NAS worden bevestigd; de app is nog niet op jouw NAS getest.

Container Manager en de app gebruiken extra geheugen en processorcapaciteit. Voor de draaiende app is een limiet van 384 MB ingesteld. Het bouwen vraagt tijdelijk extra ruimte en capaciteit. Draai de NAS niet op een schema waarbij hij voor de gekozen starttijd wordt uitgeschakeld.

## Bestanden plaatsen

1. Download de code van branch `codex/passat-midnight` in repository `jobalberga/zwogen` op GitHub. Kies **Code → Download ZIP**. Pak de bestanden uit.
2. Maak in **File Station** de map `docker/na-de-spits` en plaats daar de uitgepakte projectbestanden. `compose.yaml`, `Dockerfile`, `requirements.txt` en de map `passat_charge` moeten direct in die map staan.
3. Kopieer `.env.nas.example` naar `.env` in diezelfde map en vul de vier waarden in. Gebruik daarvoor een teksteditor op je eigen computer of NAS. Wachtwoorden horen alleen in dat privébestand.

| Instelling | Waarde |
| --- | --- |
| `APP_PASSWORD` | Een apart wachtwoord voor deze site, minimaal 12 tekens. |
| `VW_USERNAME` | Het e-mailadres van je VW-account. |
| `VW_PASSWORD` | Het wachtwoord van dat VW-account. |
| `VW_VIN` | Het chassisnummer van je Passat. |

Laat de enkele aanhalingstekens om de waarden staan. De meegeleverde configuratie gebruikt HTTP binnen je thuisnetwerk (`COOKIE_SECURE=0`). Voor toegang via een HTTPS-reverse-proxy op de NAS zet je dit op `1` en kun je `PASSAT_BIND_IP=127.0.0.1` gebruiken.

## Project starten

1. Open **Container Manager → Project → Maken**.
2. Gebruik als projectnaam `na-de-spits` en als pad de map `docker/na-de-spits`.
3. Gebruik het bestaande bestand `compose.yaml`. Start het project. Een apart Web Station-portaal is voor deze installatie niet nodig.
4. Wacht tot de bouw klaar is en de container draait. Het image wordt lokaal op de NAS gebouwd; de eerste keer kan dit enkele minuten duren.
5. Open op je telefoon, verbonden met je thuiswifi: `http://IP-ADRES-VAN-JE-NAS:18080`. Vervang het adres door het lokale IP-adres dat DSM voor de NAS toont. Log in met het gekozen app-wachtwoord.

Daarna controleer je de echte accustand en de VW-meettijd. Sluit de laadkabel aan en kies bij **Starten om** een tijd en maak een eenmalige planning. Controleer de eerste keer ook in de VW-app dat de auto het pauzeren bevestigt. De fysieke VW-koppeling is pas na die controle en de eerste start op de gekozen tijd getest.

Deze configuratie is bedoeld voor thuiswifi. De router hoeft hiervoor niet te worden aangepast. Voor toegang buitenshuis kan later een bestaande VPN of een HTTPS-reverse-proxy worden gebruikt; Synology QuickConnect alleen is geen gegarandeerde route naar deze containerpoort.

## Gegevens en herstarten

De opdracht, sessiesleutel en VW-tokens staan in het Docker-volume `passat-data` van het project. De container draait als gebruiker 10001, zonder rootrechten. Docker beheert de rechten en eigendom van het volume. Verwijder dit volume niet bij een update of herstart: daarin staat ook een eventuele openstaande laadopdracht. Houd ook `.env` privé en bewaar een veilige kopie.

`restart: unless-stopped` zorgt dat het project na een normale NAS-herstart terugkomt. Controleer wel of Container Manager mee start. Een handmatig gestopte container moet handmatig weer worden gestart. Een gemiste laadopdracht verloopt na het startvenster; hij wordt niet een nacht later ingehaald.

Voor installatie via een terminal vanuit de projectmap:

```sh
docker compose up -d --build
docker compose ps
```

Een update gebruikt hetzelfde commando nadat je de nieuwe projectbestanden hebt geplaatst. Bewaar je bestaande `.env` en volume.

## Wat is getest

De container is lokaal op x86-64 gebouwd en gestart. Inloggen via HTTP, de gebruiker zonder rootrechten, de permanente opslag, het behoud van een opdracht na herstart en de meegeleverde Nederlandse tijdzonegegevens zijn gecontroleerd. Alle 40 app-tests slagen. Voor ARM64 is gecontroleerd dat alle vereiste pakketten als kant-en-klaar pakket beschikbaar zijn. Uitvoeren op ARM64, de beschikbaarheid van Container Manager op jouw DSM en de koppeling met jouw Passat moeten op de NAS nog worden bevestigd.
