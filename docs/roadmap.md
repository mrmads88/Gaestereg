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

## Fase 2: Gæsteoplevelse
- WiFi-navn og -kode på kvitteringsskærmen og gæstekortet.
- Knappen "Pakke/levering", der giver godsmodtager eller reception besked.
- Åbningstider og en "Vi har lukket"-tekst uden for åbningstid.
- Flere gæster på én gang (gruppe til samme møde).
- Husregler, fortrolighedsaftale eller sikkerhedsinstruks, som gæsten accepterer ved check-ind.
- Værten svarer fra et link i SMS'en ("kommer om 5 min"), og svaret vises på skærmen.
- Påmindelse til en anden (fx receptionen), hvis værten ikke reagerer inden for X minutter. Skal ske uden at polle databasen.
- Teams-besked i stedet for eller ud over SMS (indgående webhook pr. firma).

## Fase 3: Forhåndsregistrering
- Værten inviterer en gæst. Gæsten får SMS/mail med QR-kode og kode.
- Check-ind ved skærmen med QR (kamera) eller kode.
- Check-ind på gæstens egen telefon via QR på døren (billig pakke uden tablet).

## Fase 4: Kontorhotel
- Fælles skærm til hele huset: gæsten vælger firma og derefter person. Styres af partneren.
- "Hvem er i huset" og evakueringsliste på tværs af firmaer, med én knap på telefonen.
- Besøgsstatistik pr. firma pr. måned (kan bruges til at fakturere lejerne).
- Faste gæster (håndværkere osv.) genkendes på mobilnummer.

## Fase 5: Mødelokaler og forplejning
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

## Venter på prod / en kunde
- Oppetids-tjek og fejlmails. Et tjek hver anden time ville vække dev-databasen og bruge det gratis forbrug op.
- Billeder i Azure Blob Storage (koster et par kroner om måneden). Koden er klar (fase 1).
- Automatisk personliste fra Microsoft 365 (kræver kundens samtykke i deres Microsoft-opsætning).
- Databehandleraftale, som kunden accepterer ved første login. Mekanismen er nem, men teksten skal være juridisk godkendt.
- To-trins-login for partnere.
