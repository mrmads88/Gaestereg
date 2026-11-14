# Nodd køreplan

Ønsker fra Mads, samlet november 2026. Hver fase udrulles til dev, testes og sendes på mail, før den næste starter.
Alt skal kunne køre gratis i dev. Prod opgraderes først, når der er en betalende kunde.

## Fase 1: Overblik og fundament (udrullet)
- Kundeskifter i topbaren med søgning, "Senest åbnet" og Ctrl+K / ⌘K. Admin husker sidste kunde.
- Kunde- og partnerlisten bruger det samme antal databaseforespørgsler, uanset antal kunder (test).
- Begrænsning af loginforsøg pr. IP og e-mail. Begrænsning af "glemt adgangskode".
- Skærmstatus (online/offline) i admin. Ligger i hukommelsen, så skærmen aldrig vækker databasen.
- Sletning af én gæsts data (ét besøg eller alle med samme mobilnummer) af hensyn til GDPR.
- Billeder går gennem et lagringslag (`media.storage`), så de kan flyttes til Azure Blob Storage med én ændring.

## Fase 2: Gæsteoplevelse (udrullet)
- WiFi-navn og -kode på kvitteringsskærmen og gæstekortet.
- Knappen "Pakke/levering", der giver godsmodtager eller reception besked.
- Åbningstider og en "Vi har lukket"-tekst uden for åbningstid.
- Flere gæster på én gang (gruppe til samme møde).
- Husregler, fortrolighedsaftale eller sikkerhedsinstruks, som gæsten accepterer ved check-ind.
- Værten svarer fra et link i SMS'en ("kommer om 5 min"), og svaret vises på skærmen.
- Påmindelse til receptionen, hvis værten ikke reagerer inden for X minutter (timer i hukommelsen, ingen polling).
- Teams-besked ud over SMS (Workflows-webhook pr. firma).
- Svarlinket gør SMS'en ca. 50 tegn længere (ofte 2 SMS'er). Kan senere forkortes med et kortere token.

## Fase 3: Forhåndsregistrering (udrullet)
- Værten inviterer en gæst. Gæsten får SMS/mail med QR-kode og kode.
- Check-ind ved skærmen med QR (kamera) eller kode.
- Check-ind på gæstens egen telefon via QR på døren (billig pakke uden tablet). Plakat til A4 under "QR til døren".
- Værter uden login har et personligt invitationslink (`/i/<token>`), som kan laves om.
- Kamera-scanning bruger browserens indbyggede QR-læser (BarcodeDetector), som findes i Chrome på Android og ChromeOS. Andre steder tastes koden.

## Fase 4: Kontorhotel (udrullet)
- Fælles skærm til hele huset: gæsten vælger firma og derefter person. Styres af partneren.
- "Hvem er i huset" og evakueringsliste på tværs af firmaer, med én knap på telefonen.
- Besøgsstatistik pr. firma pr. måned (kan bruges til at fakturere lejerne).
- Faste gæster (håndværkere osv.) får en kode, der kan bruges igen indtil en dato. Ikke genkendelse på mobilnummer: så kunne alle ved skærmen se, hvem et nummer tilhører.
- Besøgsstatistik gemmes som anonyme tællere pr. firma pr. måned (`visit_stats`), så den overlever, at besøgene slettes efter 30 dage.

## Fase 5: Mødelokaler og forplejning
**5a (lokaler, booking og lokaleskærm) og 5b (forplejning) er bygget.** Mangler: modul-til/fra under Abonnement,
bestilling af forplejning fra admins bookingformular og LED-test på en rigtig mødelokale-tablet.

Bygget i 5b:
- Køkkener (`Kitchen`) hos firmaet eller huset, eget køkken eller ekstern leverandør, med mail/SMS til bestillinger,
  varsel i timer og en besked til dem, der bestiller. Menu (`MenuItem`) med billede, kategori, pris, enhed og mærker
  (vegetar, glutenfri osv.). "Opret eksempelmenu" til hurtig start.
- Bestilling i bookingskuffen: menukort med billeder og +/−. Varer "pr. person" følger antal deltagere.
  Serveringstid, allergier og omkostningssted. Kan rettes eller fjernes bagefter fra "Dine bookinger".
- Køkkenet får mail og SMS ved ny, ændret og annulleret bestilling, uden mødets titel. Køkkenets side `/kitchen/<token>`:
  dagens bestillinger, samlet pakkeliste, Bekræft/Leveret og print. Svarer fra hukommelsen.
- Bestillinger og faktureringsgrundlag pr. måned i admin med CSV til Excel.

Bygget i 5a:
- Lokaler hos firmaet eller huset (`Room`), bookinger (`Booking`), fanen "Lokaler" i admin og et kort på husets side.
- Værtens bookingside `/b/<token>` (samme personlige link som invitationerne): dage, lokalekort med billeder, tidslinje og en
  skuffe med titel, tid, deltagere, opstilling og udstyr.
- Lokaleskærmen `/room/<token>`: grøn/orange/rød, ur, igangværende og næste møde, "Book nu" 15/30/60 min. LED via
  `window.NoddLED.setColor`, `Android.setLed` eller Fully Kiosk. Svarer fra hukommelsen, så databasen kan sove.
- Diskretion i tre lag (skærm → firma → hus), standard "kun optaget". Husets admins ser firmaernes møder som skærmen gør.

Moduler pr. kunde (Gæster, Lokaler, Forplejning), som slås til under Abonnement.
Lokaler og køkken kan høre til huset (partneren), så alle firmaer i et kontorhotel kan booke de samme lokaler.

**Booking**
- Lokaler med billeder, kapacitet, opstillinger (fx biograf, U-bord, ø-borde) og udstyr, der kan tilvælges.
- Forplejning fra husets eget køkken eller en ekstern leverandør: menu med billeder, priser og antal.
- Simpelt og indbydende bookingflow. Store billeder og tydelige priser. Nemt at angive antal.
- Ordreoversigt til køkkenet: hvad skal leveres hvor og hvornår.

**Lokaleskærm (tablet ved døren)**
- Dato og tid. Stor statusfarve: rød = optaget, grøn = ledigt.
- Igangværende møde og næste møde. "Book nu" direkte på skærmen.
- LED-lys på tablets, der har det (fx Qbic, IAdea, Philips), via deres indbyggede browser. Ellers farves skærmen.
- **Diskretion:** mødetitler må ikke afsløre fortrolige ting (fx "fyringsrunde 1") for andre firmaer eller gæster.
  Indstillingen findes i tre lag, hvor det mest specifikke vinder: hus → firma → skærm.
  Valg: "Vis mødetitel", "Vis kun arrangør", "Vis kun Optaget". Standard er "Vis kun Optaget".
- Samme look som gæsteskærmen: kundens logo, farver og stor, letlæselig tekst.

**Senere**
- Outlook-tilføjelse (manifest), hvor man booker lokale og forplejning fra en mødeindkaldelse.
  Visningen skal tilpasses Outlooks små paneler, så tekst og billeder ikke bliver små og svære at læse.
- Synk med lokalepostkasser i Microsoft 365, så bookinger fra Outlook og Nodd ikke kolliderer.

## Fase 6: Pakker, tilkøb og fakturering (bygget)
Moduler følger af det, kunden har købt (`billing.py`, `modules.py`). Kunden er et firma eller et hus. Har huset et modul,
gælder det for alle husets firmaer.

Prisforslag (kr. ekskl. moms, kan rettes under Fakturering → Prisliste):

| Pakke | Pris/md. | Indhold |
|---|---|---|
| Start | 349 | Gæsteskærm, besked til værten, invitationer, pakker, evakuering, 100 SMS |
| Plus | 649 | Start + selvbetjening, overblik og månedsrapport, 300 SMS |
| Komplet | 1.195 | Plus + mødelokaler (5), forplejning, infoskærm, 500 SMS |
| Hus | 2.495 | Husets skærm, 10 firmaer, alle moduler for alle firmaer, 1.000 SMS |

Tilkøb pr. md.: Mødelokaler 349, Forplejning 249, Selvbetjening 149, Overblik/rapport 99, Infoskærm 199,
ekstra skærm 99, ekstra lokale 49, ekstra firma i huset 99. Forbrug: SMS ud over pakken 0,39 kr./stk. (bagud).
Engangs: opsætning 1.495, tablet med gulvstander 4.495. Årsbetaling: 2 måneder gratis.

Tankerne bag: pakkerne er nemme at sælge og forstå, og tilkøb dækker resten. SMS er den eneste reelle variable udgift,
så den er med i pakken op til et loft og afregnes derefter. Hus-pakken er billigere pr. firma end Komplet, så
kontorhoteller har en grund til at samle firmaerne hos sig.

- Fakturering forud pr. måned, kvartal eller år. Tilmelding midt i en periode udregnes pr. dag og kommer automatisk
  med på næste faktura. Opsigelse af betalt tid krediteres.
- Rabat: fast på kunden (%), pr. produkt (%), særpris pr. produkt og engangsrabatter.
- Fakturakørsel laver kladder, der kan godkendes (nummer fra 1001) og hentes som CSV til bogføringen.

Mangler: grænser (5 lokaler, 10 firmaer, skærme) håndhæves ikke automatisk endnu; integration med e-conomic eller
Dinero, så fakturaer sendes derfra; kunden kan ikke selv se sin pakke i admin.

## Fase 7: Overblik og månedsrapport (bygget)
- Overblik `/admin/rapport?tenant_id=|partner_id=&period=` (måned `2026-11`, kvartal `2026-Q4` eller år `2026`):
  gæster med udvikling mod forrige periode og 13 måneders tendens, pakker, mødebookinger, belægning pr. lokale
  (hverdage kl. 8–17), bookinger pr. ugedag, forplejning pr. måned, mest bestilte, pr. omkostningssted eller firma, og
  pr. firma i huset. Tabelvisning af alle tal, CSV til Excel og print/PDF i A4 på tværs (3 sider).
- Ingen navne på gæster og ingen mødetitler, så det kan vises på direktionsmøder. White-label med kundens logo og farve.
- Månedsrapport på mail den 1. kl. 7 til `report_email` (firmaets egne admins eller huset bestemmer), med nøgletal,
  top-lister, link til overblikket og CSV vedhæftet. `report_runs` sikrer, at hver rapport kun sendes én gang.
  Planlæggeren er en tråd i appen; den indhenter manglende rapporter ved opstart (F1 sover efter 20 min. uden trafik).
- Kræver modulet `reports` (Plus, Komplet, Hus eller tilkøb). Leverandøren kan altid åbne overblikket og vise det.

Senere: sammenligning mellem firmaer i et hus over tid, travleste tidspunkter for gæster (kræver statistik pr. time).

## Fase 8: Infoskærme (bygget)
- Infoskærm pr. firma eller hus på `/s/<token>` (åbnes i tv'ets browser). White-label, tema firmafarve/mørk/lys,
  opsætning med sidebar eller fuld skærm, virker på tværs og på højkant.
- Playliste af slides, der skifter med blød overgang: velkomst, tekst/nyhed (med billede), billede, dagens gæster
  (kun firma eller fornavn + forbogstav), mødelokaler (ledig/optaget, diskretion gælder), dagens menu (tekst pr.
  ugedag) og QR-kode. Hver slide kan begrænses til ugedage og tidsrum. Slides uden indhold i dag springes over.
- Sidebar: ur, vejr (Open-Meteo, hentes af skærmen selv), mødelokaler, forventede gæster, gæste-wifi, menu og QR.
  Felter, der ikke kan være der, skjules. Nyhedsbånd nederst.
- Editor i admin (fanen Infoskærme og husets side) med levende forhåndsvisning, billedupload og nyt link.
- Kræver modulet `signage` (Komplet, Hus eller tilkøb). Mødelokale-blokken kræver `rooms`.
- Skærmens data caches i hukommelsen og tømmes ved admin-ændringer, bookinger og invitationer.

Senere: video, RSS/nyheder fra en hjemmeside, kantinens rigtige menu (når kantine/POS kommer), nødbesked på alle skærme.

## Nødbesked på alle skærme (bygget)
- Rød knap "Nødbesked" øverst på firmaet og huset i admin. Typer: Evakuering (rød, hele skærmen), Vigtig besked
  (orange, hele skærmen) og Information (bånd øverst). Tekst kan rettes, og beskeden kan slutte af sig selv.
- Vises på gæsteskærme (også gæstens telefon), lokaleskærme (LED rød) og infoskærme inden for 15 sekunder.
  Et husets besked når alle husets og firmaernes skærme. Den vigtigste aktive besked vinder.
- Brandvagten kan starte og afslutte evakuering fra evakueringslisten på telefonen uden login.
- Svarer fra hukommelsen (`alerts.py`), så skærmenes polling ikke rammer databasen. Gælder alle pakker.

- SMS, mail og Teams til personerne ved Evakuering og Vigtig besked (aldrig Information). **Slukket som standard**:
  slås til pr. hus eller firma af leverandøren eller huset (`alert_notify`). Vinduet viser antal og anslået SMS-pris,
  og personerne får "Afblæst", når beskeden slutter. Hvert nummer/hver adresse én gang. Brandvagtens knap følger
  indstillingen. SMS'erne logges i beskedloggen og tæller med i forbruget på fakturaen. Kræver GatewayAPI og live i prod.

Senere: lyd på skærmene, skabeloner pr. hus.

## Venter på prod / en kunde
- Oppetids-tjek og fejlmails. Et tjek hver anden time ville vække dev-databasen og bruge det gratis forbrug op.
- Billeder i Azure Blob Storage (koster et par kroner om måneden). Koden er klar (fase 1).
- Automatisk personliste fra Microsoft 365 (kræver kundens samtykke i deres Microsoft-opsætning).
- Databehandleraftale, som kunden accepterer ved første login. Mekanismen er nem, men teksten skal være juridisk godkendt.
- To-trins-login for partnere.
