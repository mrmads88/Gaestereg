# Guide til leverandøren (Mads)

Denne guide er til dig som leverandør af Nodd. Kundernes guides ligger i hjælpecentret på `/hjaelp`
(indholdet i `app/static/help-content.js`).

## Log ind som leverandør

1. Find admin-koden: [portal.azure.com](https://portal.azure.com) → app'en (dev: `gaestereg-dev-6d413b`)
   → **Settings → Environment variables** → `ADMIN_PASSWORD` → **Show value**.
   Eller med Azure CLI:
   `az webapp config appsettings list --name gaestereg-dev-6d413b --resource-group rg_gaestereg_app_dev --query "[?name=='ADMIN_PASSWORD'].value" -o tsv`
2. Åbn `/admin`, tryk **Leverandør-login** nederst, og indsæt koden (ingen e-mail).
3. Har du to-trins-login, skriver du derefter koden fra kodeappen (eller en engangskode).
   I prod er to-trins-login påkrævet og sættes op ved første login.

## Hvis det driller

| Problem | Løsning |
|---|---|
| "Forkert adgangskode" | Tjek, at hele koden er kopieret uden mellemrum. Efter 10 forkerte forsøg: vent 15 minutter. |
| Ny admin-kode | Ret `ADMIN_PASSWORD` under Environment variables og gem. App'en genstarter af sig selv (ca. et minut). |
| Mistet telefon og engangskoder | Sæt `ADMIN_MFA_RESET=1`, gem, log ind og sæt to-trins-login op igen under **Sikkerhed**. Slet derefter indstillingen. |
| En kunde-admin er låst ude | Under kundens **Adgang**: "Link til ny adgangskode" eller "Nulstil to-trins". |

## Ny kunde

Tryk **+ Ny kunde**. Guiden tager navn og pakke (og tilkøb), logo og farve, de første personer, skærmlink/QR-plakat og
kundens administrator. Bagefter viser **Kom i gang** øverst på kunden, hvad der mangler.

## Demo til salgsmøder

I venstre side under kunderne: **Opret demo** (eller **Nulstil** før et møde). Demoen er:

- **Nordlys Arkitekter (demo)**: Komplet + Tidsregistrering, 8 personer, besøg de sidste 60 dage og et års statistik,
  3 mødelokaler med bookinger, kantine med menu og bestillinger, infoskærm og arbejdstid. Skærm: `/k/demo-nordlys`.
  Medarbejdernes PIN er `1234`.
- **Havnehuset (demo)**: kontorhotel med to lejere og fælles husskærm (`/k/demo-havnehus`), husets lokaler og café.

Demo-kunderne sender aldrig rigtige SMS'er eller mails (heller ikke i prod), faktureres ikke, får ingen månedsrapport
og kommer ikke med i CRM'et.

## Daglige steder

- **CRM**: knappen CRM i topbaren.
- **Fakturering og Klar til prod**: knappen Fakturering.
- **Sprog**: English/Dansk i topbaren.
- **Hjælp**: knappen Hjælp åbner hjælpecentret, som du også kan sende til kunder (`/hjaelp#guide-id`, fx `/hjaelp#tid`).
