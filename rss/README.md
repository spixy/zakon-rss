# RSS feedy noviel zákonov (CZ a SK)

Dva statické RSS feedy, ktoré dvakrát denne (o 06:00 a 18:00 SEČ, v lete o 07:00 a 19:00) vygeneruje GitHub Actions a zverejní GitHub Pages. Nie je potrebný žiadny server.

Keď sa obsah feedu zmení, workflow ho uloží aj do priečinka [`feeds/`](../feeds) v tomto repozitári. Vzniká tak história feedov a repozitár zostáva aktívny, takže GitHub naplánovaný beh po 60 dňoch nevypne.

| Feed | Adresa | Obsah |
|---|---|---|
| Česko | https://spixy.github.io/zakon-rss/cz.xml | zmeny predpisov Sbírky zákonů (zákony, nariadenia vlády, vyhlášky, nálezy ÚS) |
| Slovensko | https://spixy.github.io/zakon-rss/sk.xml | zmeny predpisov Zbierky zákonov |

## Čo je položka feedu

Jedna položka zodpovedá **jednej zmene predpisu, ktorá nadobúda účinnosť** (jeden commit vo verejnom git repozitári s históriou predpisov danej krajiny).

- **Dátum (`pubDate`)** je deň účinnosti, nie deň zverejnenia.
- **Nadpis** obsahuje číslo a názov predpisu.
- **Popis** uvádza, čo sa zmenilo (pri CZ až po paragrafy) a obsahuje odkazy na oficiálny text (e-Sbírka / Slov-Lex).
- **Rozsah:** zmeny s účinnosťou za posledných 90 dní a vyhlásené zmeny s účinnosťou do roka dopredu, najviac 300 položiek.
- **Vynechané:** opravy e-Sbírky staršieho znenia, obecné vyhlášky / VZN, návrhy zákonov a dokumentačné commity.

## Nasadenie (raz)

1. Vytvor na GitHube repozitár a nahraj doň tento priečinok (`rss/`, `.github/workflows/rss.yml`, `.gitignore`).
2. V repozitári otvor **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. V **Settings → Secrets and variables → Actions → New repository secret** pridaj dva secrets so zdrojovými repozitármi vo tvare `vlastník/názov`:
   - `CZ_SOURCE_REPO`
   - `SK_SOURCE_REPO`
4. V karte **Actions** spusti workflow **RSS noviel** cez *Run workflow*. Ďalej sa spúšťa sám dvakrát denne. Čas behu sa mení v `cron` v `.github/workflows/rss.yml` (v UTC).
5. Feedy budú na `https://<účet>.github.io/<repozitár>/cz.xml` a `…/sk.xml`. Na `…/index.html` je ich zoznam.

Pri súkromnom repozitári sú GitHub Pages dostupné len v platených plánoch. Verejný repozitár funguje zadarmo.

## Lokálne spustenie

Najprv nastav premenné `CZ_SOURCE_REPO` a `SK_SOURCE_REPO` (rovnaké hodnoty ako secrets), potom:

```bash
python rss/generate.py --cache .cache --out public
```

Potrebný je Python 3.9+ a git. Prvý beh stiahne len commity bez obsahu súborov (CZ ~55 MB, SK ~10 MB) a trvá ~30 s. Ďalšie behy sťahujú iba nové commity.

Užitočné parametre:

| Parameter | Význam |
|---|---|
| `--days 90` | koľko dní dozadu podľa účinnosti |
| `--ahead 365` | koľko dní dopredu |
| `--max-items 300` | najviac položiek vo feede |
| `--only sk` | len jedna krajina |

## Obmedzenia

- **Čerstvosť závisí od zdrojového repozitára.** Feed je taký aktuálny, ako repozitár s históriou predpisov. Pri SK sa dáta zatiaľ dopĺňajú v dávkach.
- **SK neuvádza paragrafy.** Slov-Lex uvádza novelu len pre celé znenie, takže SK položky nehovoria, ktoré paragrafy sa zmenili. Pri zmenách označených „najstaršia verzia v tomto zázname“ ide o aktuálne znenie bez dohľadanej novely.
- **Uspávanie workflowu.** GitHub automaticky vypne naplánované workflowy, ak v repozitári 60 dní nebola žiadna aktivita. Commity feedov tomu bránia, ak sa feed aspoň raz za 60 dní zmení. Ak by sa predsa len vypol, znova sa zapína v karte Actions.
- **Právna záväznosť.** Právne záväzný je len text vyhlásený v Zbierke zákonov / Sbírce zákonů.

Dáta: e-Sbírka (Ministerstvo vnitra ČR) a Slov-Lex (Ministerstvo spravodlivosti SR).
