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

## Klar til prod (bygget)
- Generalprøve på migrationen: gammel prod-kode laver databasen, ny kode opgraderer den (SQLite og SQL Server bestået).
- Billeder i Azure Blob Storage i prod (scriptet opretter kontoen), med knap til at kopiere gamle billeder op.
- Fejlmails til leverandøren og oppetidstjek hver time (GitHub Actions, kun når `PROD_URL` er sat).
- "Klar til prod"-liste under Fakturering, som viser, hvilke indstillinger der mangler.
- Databehandleraftale, som kundens admin (eller huset) accepterer ved første login. Udkast, indtil en jurist har
  godkendt teksten (`DPA_FINAL=1`).
- Privatlivsside for gæster (dansk/engelsk) med link fra skærmen.
- Go-live-trin i `docs/azure.md` (B1, betalt SQL, domæne, beskyttelse af `production`).

## To-trins-login (bygget)
- Kodeapp (Microsoft/Google Authenticator) og 10 engangskoder. Påkrævet for leverandøren og husene i prod
  (`MFA_REQUIRED`), frivilligt for kunde-admins under "Sikkerhed".
- Administratorer kan nulstille en brugers to-trins-login ("Nulstil to-trins" under Adgang). Leverandøren har en
  nødknap (`ADMIN_MFA_RESET`).
- Et link til ny adgangskode springer ikke andet trin over. Til/fra logger andre sessioner ud.

## Nodd som platform: de næste moduler
Mads' ønske (november 2026): flere moduler i samme system, så alt samles ét sted.

1. **CRM (kun leverandøren): bygget.** Knappen "CRM" i topbaren. Overblik (omsætning pr. md., åben og vægtet
   pipeline, vundet i måneden, dagens opfølgninger, seneste aktivitet), pipeline med træk og slip, firmaliste med
   søgning og CSV, og et kort pr. firma med stamdata, kontakter, salgsmuligheder, opgaver og tidslinje. Koblede
   kunder viser omsætning, besøg, seneste login og databehandleraftale, og tidslinjen får fakturaer fra Nodd.
   "Hent dem" opretter de eksisterende kunder og huse. Morgenmail med dagens opfølgninger i prod.
   Senere: mails direkte fra CRM, påmindelse om fornyelse, tilbud som PDF, flere brugere (sælgere).
2. **Tidsregistrering for medarbejdere: bygget** (tilkøbet "Tidsregistrering", 249 kr./md. for op til 25
   medarbejdere). Siden 1. juli 2024 skal arbejdsgivere i Danmark registrere medarbejdernes daglige arbejdstid og
   gemme den i 5 år. Medarbejdere stempler ind og ud på receptionsskærmen (knappen "Medarbejder" og en 4-cifret PIN)
   eller på telefonen (personligt link), hvor de også kan se deres egne registreringer. Fanen "Tid" i admin:
   ugeskema med normtid og over/under, hvem der er på arbejde nu, manglende udstemplinger, rettelser med log,
   godkendelse pr. uge og CSV til Danløn/Salary. Automatisk pause ved dage over 6 timer. Medarbejdere, der er
   stemplet ind, står på evakueringslisten.
   Senere: ferie og fravær, flere arbejdssteder/projekter, direkte overførsel til Danløn/Salary, påmindelse om
   glemt udstempling.
3. **Integrationer i stedet for egen bogføring og løn.** Bogføringsloven kræver anmeldte, godkendte systemer, og
   løn kræver indberetning til eIndkomst, ATP, ferie og pension. Derfor: fakturaer sendes til e-conomic, Dinero
   eller Billy, og timer eksporteres til Danløn eller Salary.
4. Andre moduler, der passer: adgangskort og nøgler, gæsteparkering, helpdesk til huset (fejlmeldinger), skabe,
   kantine/POS.

## Admin på engelsk (bygget)
- Sproget vælges på login-siden (Dansk · English) og skiftes med knappen i topbaren. Det gemmes på brugeren og følger
  med til andre enheder. Nye brugere arver sproget fra den, der inviterer, og invitationsmails følger sproget.
- Alt i admin oversættes, også fejlbeskeder fra serveren og prislistens tekster. Medarbejdernes sider (tid, booking,
  køkken, rapport, evakuering) følger browserens sprog (eller `?lang=en`).
- Dansk er stadig kildeteksten. Ordbogen ligger i `app/static/i18n-en.js`, og en test sikrer, at nye tekster kommer med.
- Senere: flere sprog (svensk, norsk, tysk) med samme ordbog-format; priser og fakturaer forbliver på dansk.

## Hjælp og guides (bygget)
- Hjælpecentret på `/hjaelp`: 15 guides (kom i gang, skærm, personer, invitationer, QR til døren, besøg og GDPR,
  nødbesked, lokaler, forplejning, infoskærme, tidsregistrering, stempling for medarbejdere, overblik, adgang og
  kontorhotel) med søgning, filter pr. rolle, dansk/engelsk, print og direkte links (`/hjaelp#tid`).
- "?" ved de vigtigste overskrifter i admin med en kort forklaring og et link til guiden. Knappen "Hjælp" i topbaren
  og et link på login-siden.
- Leverandørens egen guide (login, ny kode, mistet telefon): `docs/leverandoer-guide.md`.
- Senere: korte videoer/GIF'er i guiderne, en "første gang"-rundvisning i admin og hjælp i lokale- og bookingsiden.

## Opsætningsguide og demo (bygget)
- "+ Ny kunde" åbner en guide i fem trin: navn og pakke (med tilkøb), logo/farve/velkomst, de første personer,
  skærmlink og QR-plakat, og kundens administrator. Huse ("+ Nyt firma") får samme guide uden pakker.
- "Kom i gang"-tjeklisten øverst på kunden krydser selv af: logo, personer, skærm tændt, første gæst, administrator,
  databehandleraftale og pakke. Kan skjules.
- Demo til salgsmøder (venstre side, kun leverandøren): Nordlys Arkitekter med alle moduler og et års data, og
  Havnehuset med to lejere og fælles skærm. Nulstilles med ét klik. Sender aldrig rigtige beskeder, faktureres ikke
  og er ikke i CRM eller månedsrapporter.
- Senere: hent logo og farve fra kundens hjemmeside, en kundevendt demo med eget login (kun læse), rundvisning første
  gang en kunde logger ind.

## Integrationer (fundament bygget)
Mads' ønske (november 2026): alle regnskabsprogrammer og systemer som ServiceNow, Salesforce, Salary osv.
- Tilkøbet "Integrationer og API" (199 kr./md.). Fanen Integrationer på firmaet og huset, og leverandørens egne under
  Fakturering.
- Webhooks: gæst tjekket ind/ud, pakke modtaget, booking oprettet/aflyst, nødbesked start/slut, uge godkendt og (for
  leverandøren) faktura godkendt. Signeret, nye forsøg i 12 timer, log med "Prøv igen", testknap. Virker med
  Power Automate, Make, Zapier, ServiceNow Flow og Salesforce Flow, og dermed tusindvis af systemer.
- API v1 med nøgler: besøg, personer (og personsync fra HR/Microsoft 365), bookinger og arbejdstid.
- Katalog "Forbind med" og guiden "Integrationer og API" i hjælpecentret.

Næste: direkte koblinger, der ikke kræver Make/Zapier:
1. Regnskab for leverandørens fakturaer: e-conomic, Dinero, Billy (dokumentationen kunne ikke hentes fra dette
   miljø; kræver adgang til restdocs.e-conomic.com, www.billy.dk og api.dinero.dk samt testkonti).
2. Løn: Salary og Danløn (timer fra tidsregistreringen).
3. Microsoft 365/Entra: personliste og Teams.
4. ServiceNow og Salesforce som færdige apps (OAuth) i stedet for webhooks.

## Venter på prod / en kunde
- Automatisk personliste fra Microsoft 365 (kræver kundens samtykke i deres Microsoft-opsætning).
- Juridisk godkendelse af databehandleraftalens tekst (`DPA_FINAL=1`).
