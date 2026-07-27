# Rautakierto

Täyskehon A/B/C-saliohjelma puhelimeen: kertoo vuorossa olevan ohjelman, näyttää liikkeet/sarjat/painot, ja laskee treenit viikko/kk/vuosi-tasolla. Data tallentuu puhelimen selaimeen, ja vienti/tuonti-napeilla otat varmuuskopion milloin tahansa.

## Käyttöönotto GitHub Pagesilla (n. 5 min)

1. Luo GitHubiin uusi repositorio, esim. nimellä `rautakierto` (voi olla julkinen tai yksityinen — yksityinenkin toimii Pagesin kanssa, jos tilisi tukee sitä).
2. Lataa tämän kansion kaikki tiedostot (`index.html`, `manifest.json`, `sw.js`, `icon.png`) repositorion juureen. Helpoin tapa: GitHubin web-käyttöliittymässä *Add file → Upload files*, raahaa tiedostot sisään ja commitoi.
3. Mene repositoriossa **Settings → Pages**.
4. Kohtaan "Source" valitse **Deploy from a branch**, branch **main**, kansio **/ (root)**. Tallenna.
5. Odota 1-2 minuuttia. GitHub näyttää osoitteen muodossa:
   `https://KÄYTTÄJÄNIMESI.github.io/rautakierto/`
6. Avaa osoite puhelimen selaimella (Chrome).
7. Chromen valikosta (⋮) valitse **"Lisää aloitusnäytölle"** tai **"Asenna sovellus"**. Appi ilmestyy kotinäytölle omalla kuvakkeella ja avautuu ilman selaimen osoiteriviä.

## Datan tallennus

Painot ja treenihistoria tallentuvat puhelimen selaimen muistiin (localStorage). Tämä toimii hyvin normaalikäytössä, mutta jos vaihdat puhelinta, tyhjennät selaimen tiedot, tai haluat vain varmuuden vuoksi säännöllisen varmuuskopion:

- **Vie tiedosto** (Tilastot-välilehti) lataa kaiken datan JSON-tiedostona puhelimeesi.
- **Tuo tiedosto** palauttaa aiemmin viedyn JSON-tiedoston, jos data on kadonnut tai vaihdat laitetta.

Suosittelen viemään varmuuskopion esim. kerran kuukaudessa, tai aina kun teet muutoksia joita et halua menettää.

## Ohjelman C painojen lisääminen

Ohjelma C:n liikkeille ei ole vielä tallennettu painoja appiin (koodissa `kg:null`). Kun teet ohjelman C ensimmäistä kertaa, syötä painot suoraan appiin kenttiin — ne tallentuvat automaattisesti.

## Sisällön muokkaaminen jatkossa

Liikkeet, sarjat ja toistomäärät on määritelty `index.html`-tiedoston alussa olevassa `DEFAULT_DATA`-objektissa. Jos haluat muuttaa ohjelman sisältöä pysyvästi (esim. vaihtaa liikkeen), muokkaa tätä kohtaa ja lataa päivitetty tiedosto GitHubiin uudelleen. Tämä ei nollaa käyttäjän jo tallentamaa dataa selaimessa, koska sovellus lukee tallennetun datan ensisijaisesti.
