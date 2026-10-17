# Marko — OOS / Oblak ekosustav: javni bootstrap i prvi inženjerski zadatak

**Namjena:** uvod za Marka (`fiskalna123`), senior developera.  
**Datum:** 2026-10-16  
**Vrsta:** javni, neosjetljivi orijentacijski dokument + uputa AI asistentu.  
**Status:** arhitekturni kontekst i zadatak za provjeru; ne dokazuje da su svi navedeni moduli produkcijski integrirani.

> **Kreni od konkretnog problema, ne od marketinškog pitcha.** Cilj je da Marko razumije sustav, pokuša ga srušiti argumentima i dokazima, te predloži minimalnu robusnu rekonstrukciju gdje je potrebna. Nije cilj potvrditi autorove pretpostavke.

## 1. Kako pokrenuti u ChatGPT-u, Claudeu ili drugom AI chatu

U novi chat zalijepi sljedeće (ili priloži sadržaj ove datoteke ako AI ne može otvoriti link):

```text
Otvori i pročitaj:
https://github.com/aoblak/ai-agent-web/blob/main/MARKO-START-HERE.md
te javni radni ugovor:
https://github.com/aoblak/ai-agent-web/blob/main/MASTER_PROMPT.md

Ja sam Marko, senior developer. Vodi me na hrvatskom kroz ovaj ekosustav, razgovorom pitanje–odgovor (jedno pitanje po koraku). Ne pretpostavljaj privatni GitHub pristup. Nakon kratkog uvoda daj mi konkretan red-team/audit zadatak, provjeri razumijevanje arhitekture memorije i donošenja odluka, zatraži moje protuargumente i na kraju pitaj želim li isprobati OOS u izoliranoj simulaciji ili read-only okruženju. Ne piši kod, ne otvaraj PR i ne mijenjaj repozitorije bez mojeg izričitog odobrenja.
```

**Javni izvori:**
- Početni repozitorij: https://github.com/aoblak/ai-agent-web
- Ugovor načina rada: https://github.com/aoblak/ai-agent-web/blob/main/MASTER_PROMPT.md
- Ulazak u postojeći workspace: https://github.com/aoblak/ai-agent-web/blob/main/AI_START_HERE.md

Javni bootstrap **ne daje pristup** privatnom OOS kodu, privatnim GitHub repozitorijima, journalima ni tajnama. Pristup je zaseban, kontroliran korak.

## 2. Što Aljoša zapravo gradi?

Nije riječ o nizu nepovezanih web-stranica. Cilj je **slojevita platforma za pouzdano izvršavanje AI-poslovnih procesa**, u kojoj jedan kontrolni mehanizam upravlja različitim aplikacijama.

```text
KORISNIK / POSLOVNI DOGAĐAJ
           │
           ▼
OOS — kontrola, pravila, ovlasti, memorija, dokaz, audit
           │
           ▼
AgentFlow — operativni AI agenti / workflowi / adapteri
           │
           ▼
DOMENSKE APLIKACIJE I POSLOVNI PROCESI
  ├─ booking.co.place → web-stranice, upiti, rezervacije
  ├─ Dunja Apartments → smještaj, cijene, zauzetost
  ├─ NERA / Dog Park Finder → pet-lokacije, karte, verifikacija
  ├─ SeedBank → izvori i pretraga informacija o sjemenu
  ├─ ArcaNina → zasebna tarot/aplikacijska vertikala
  └─ druge planirane vertikale (među njima Kairos)
           │
           ▼
STVARNA PROVJERA REZULTATA + EVIDENCIJA
```

Ovo je **ciljna arhitektura**, a ne tvrdnja da su sve strelice već implementirane ili verificirane.

**Kratak prijevod:**
- **OOS (Oblak Operating System):** kontrolni/governance sloj; ne smije dopustiti da AI-jev samouvjeren odgovor glumi ovlaštenu i verificiranu radnju.
- **AgentFlow:** izvršni/proizvodni sloj; Booking, Lead i Refund Agent dijele principe, ali imaju različite ovlasti i rizike.
- **booking.co.place:** WordPress Multisite i poslovni web/rezervacijski tenant-i; praktično tržište za provjeru automatizacije.
- **Dunja Apartments:** realna smještajna vertikala s kalendarima, cijenama, rezervacijama i upravljanjem kanalima.
- **NERA — The First Dog OS:** lokacije i usluge za pse, karta/direktorij, VITA 1 prikupljanje i VITA 2 provjera podataka.
- **SeedBank:** pretraga podataka o sjemenu i bankama sjemena uz navođenje izvora, ažurnosti, podrijetla i ograničenja. Bez dokaza nema tvrdnje `autohtono`, `GMO` ili `non-GMO`.
- **ArcaNina / Kairos:** dodatni proizvodi sa svojim domenskim pravilima; nisu razlog za dupliciranje OOS kernela.

**Poslovni slučajevi u razmatranju:** zdravstveni sektor, solarne elektrane i još jedan treći sektor/tvrtka čiji naziv i opseg ovdje **nisu potvrđeni**. Niti jedan od njih nije ovdje predstavljen kao zaključen pilot ili produkcijski klijent. Treba dodatna potvrda prije unošenja imena.

## 3. Arhitektura memorije — ono što je bitno developeru

**Chat kontekst nije durable storage. Pamćenje nije dokaz. Datoteka nije nužno kanonski izvor.**

Dizajnerski slijed OOS Unified Memory / Knowledge Core:

```text
SOURCE OF TRUTH (SOT) — dokazani izvori
      ↓
JOURNAL — append-only odluke i događaji, s atribucijom
      ↓
PROJECT STATE — aktualno operativno stanje
      ↓
GLOBAL KNOWLEDGE / WORKING PROFILE — izvedeno znanje i način rada
      ↓
INDEX / LINKS — pokazivači, ne nova istina
```

- **SOT:** konkretni Git commit, provider stanje, log, test, dokument ili potvrđena korisnička odluka, ovisno o vrsti tvrdnje.
- **Journal:** što se i zašto odlučilo/promijenilo, kada, s kojim dokazom, te što još nije riješeno.
- **Project state:** trenutačno stanje i idući koraci, koje se može rekonstruirati; ne prepisuje povijest.
- **Knowledge/Working Profile:** korisne trajne činjenice, ciljevi i pravila rada; nemaju prednost pred jačim dokazom.
- **Index:** samo navigacija prema kanonskim izvorima, bez dupliranja autoriteta.

**Write contract:** `NOT_ATTEMPTED → WRITE_ACCEPTED → READBACK_VERIFIED → PROVIDER_VERIFIED`; greška ili nedostupan read-back znače `UNKNOWN / BLOCKED`, ne `DONE`.

**Capability handshake:** `M0` bez memorije, `M1` sesijski kontekst, `M2` verificirana file-backed trajna pohrana, `M3` verificirana indeksirana memorijska usluga. Asistent ne smije sam sebe proglasiti M2/M3 bez demonstracije.

Obavezno testirati: torn writes, izgubljene potvrde, dva konkurentna pisca, replay/duplikate, stale approvals, povijesnu rekonstrukciju, rollback i restore. `VALID` struktura ne znači da je sadržaj `VERIFIED` ili povijest potpuna.

## 4. Donošenje odluka i izvršavanje

Izvršni princip: `STOP → VERIFY STATE → RETHINK → REROUTE → ACT → VERIFY RESULT → RECORD → STOP`.

Ciljani OOS control loop:

```text
INTENT → CONTEXT → POLICY → CAPABILITY → DECISION
       → PRE-VERIFY → ACTION → POST-VERIFY → AUDIT → LEARN
```

**Kritična mjesta za code review:**
1. Policy i capability enforcement moraju biti stvarni, ne samo naziv funkcije ili prompt.
2. Finalni policy enforcement point mora biti nepreskočiv neposredno prije side effecta.
3. Approval mora biti vezan za **točnu** radnju, resurs, verziju/stanje i rok.
4. Idempotency i durable task ledger moraju spriječiti dvostruko izvršenje.
5. Postcondition test mora očitati stvarno stanje u provideru; `200 OK` nije uspjeh poslovne operacije.
6. Audit/provenance moraju se moći provjeriti, uključujući negativne slučajeve.
7. `LEARN` smije predložiti promjenu, ne smije sam izmijeniti ovlasti ili produkcijsku politiku.

**Nemoj pretpostaviti da je navedeno implementirano.** Treba pročitati kod, testove, CI, evidence artifacts i konfiguraciju runtimea. Ako privatni repozitorij nije dostupan, označi kontrolu `UNVERIFIED`, a ne `FAIL` ili `PASS` bez podataka.

## 5. Markov PRVI KONKRETAN ZADATAK: red-team test i minimalni refaktor

**Scenarij:** Booking Agent prima zahtjev za termin i poruku pružatelja da je termin slobodan. Provider dostupnosti je nedostupan; zadnji poznati kalendar je zastario. Agent predlaže: *„Rezervacija je potvrđena.”*

**Očekivano:** AI ne smije potvrditi rezervaciju bez svježeg autoriziranog dokaza o dostupnosti i provjerenog postconditiona. Siguran ishod je `BLOCKED / REQUIRES_RECHECK`, s audit tragom i jasnom porukom korisniku.

**Što napravi u chatu, čak i bez privatnog pristupa:**
1. Rekonstruiraj minimalnu sekvencu `intent → evidence → policy/capability → decision → action gate → postcondition → audit`.
2. Nacrtaj *trust boundaries* (LLM, OOS PEP, AgentFlow, provider, durable storage).
3. Napiši **5 negativnih testova**: stale cache, replay, approval na starom stanju, uspješan HTTP bez stvarne rezervacije, provider outage.
4. Predloži konkretan `Action Envelope` i nepreskočivi final PEP; definiraj idempotency key, approval binding, audit event i postcondition proof.
5. Predloži **najmanji mogući P0 refaktor** (ne rewrite), s planom migracije, rollbackom i acceptance kriterijima. Identificiraj gdje je spec šuplja, a gdje moraš vidjeti stvarni kod.
6. Primijeni isti obrazac na **NERA-u** (neprovjereni geografski podatak ne smije postati `VERIFIED`) i **SeedBank** (neprovjeren izvor/podrijetlo ne smije postati činjenična tvrdnja).

**Traženi output:** jedna kompaktna matrica `RISK | FAILURE MODE | PREVENTION | TEST | EVIDENCE STATUS`, prioriteti `P0/P1/P2`, i precizna lista datoteka ili API ugovora koje treba pregledati. Bez izmišljenih passova.

**Zabranjeno bez nove izričite ovlasti:** GitHub write/push, PR merge, instalacije, remote execution, secret access, izmjene DNS-a/produkcije, dijeljenje privatnih journala ili kopiranje klijentskih podataka u javne issuee.

## 6. Način razgovora: jedno pitanje odjednom

AI asistent treba **najprije objasniti kontekst u najviše 6–8 rečenica**, a potom voditi pravi dijalog s Markom (ne ispisati sva pitanja odjednom):

**Pitanje 1 — Arhitektura.** „Što bi ti kao senior developer izdvojio kao strogu granicu između OOS control planea, AgentFlow execution layera i domenskih aplikacija?”

Nakon Markova odgovora kratko usporedi odgovor s hipotezom, priznaj gdje je njegova primjedba bolja, pa pitaj:

**Pitanje 2 — Memory.** „Što bi bila tvoja kanonska istina za zapis da je agent stvarno poslao e-mail ili potvrdio rezervaciju? Kako bi dokazao durable write i spriječio split-brain?”

**Pitanje 3 — Decision safety.** „Koji je minimalni nepreskočivi enforcement i koji failure mode bi prvo pokušao iskoristiti?”

**Pitanje 4 — Proizvodi.** „Bi li NERA, SeedBank i booking.co.place trebali dijeliti isti kernel ili samo ugovor/API? Koji dokaz bi trebao za odluku?”

**Pitanje 5 — Isprobavanje.** „Želiš li sada **isprobati OOS** kroz izoliranu simulaciju i testove bez produkcijskih ovlasti, ili želiš najprije read-only pregled privatnog koda kad ti vlasnik odobri pristup?”

Ako Marko pristane na simulaciju, odmah provedite jednu tabletop provjeru na gore navedenom booking scenariju, s barem jednim lažno pozitivnim odgovorom agenta koji kontrolni sloj mora blokirati. Zapišite `EXPECTED` i `OBSERVED` odvojeno. Ako nema izvršnog runtimea, iskreno reci da je provjera modela/razgovora, **nije** izvršen integration test.

## 7. Zaključni format Markova audita

```text
SCOPE / VERIFIED ACCESS:
ARCHITECTURE RISKS:
EVIDENCE (links, commit SHA, API response, CI):
UNKNOWN / BLOCKED:
P0 / P1 / P2 RECOMMENDATIONS:
MINIMAL REFACTOR PLAN + ROLLBACK:
NEXT TEST:
MARKO DECISION: simulation | read-only review | not now
```

Uspjeh ovog prvog zadatka znači da postoji jasan i kritički provjerljiv plan. **Ne znači** da je sustav time tehnički certificiran ili spreman za produkciju.

## 8. Nastavak preko Gita i potvrda primitka

GitHub može biti zajednički kanal za zadatke i rezultate. Pristup GitHubu sam po sebi
ne povezuje dva chata, ne otkriva drugi razgovor i ne budi neaktivnog asistenta.
Status veze ostaje `NIJE POTVRĐENA` dok ne postoji stvarni, provjerljivi primitak.

### Izvori za nastavak

- Pravila: isti `MASTER_PROMPT.md` iz ovog repozitorija; pri svakom nastavku razriješi
  aktualni `main` i zabilježi točan commit. Ne zamjenjuj pravila drugom kopijom.
- Provjera predaje: [PR #10](https://github.com/aoblak/ai-agent-web/pull/10), provjereni
  kandidat `b0a19bfebe9eeb9d507c1f6f33f959d34e44da33` s ispravcima recenzije.
- Zaseban memorijski prostor i runtime: [PR #12](https://github.com/aoblak/ai-agent-web/pull/12),
  sadrži aktualni kandidat. Razriješi njegov točan head SHA i iz te revizije dohvati
  [ulaz za suradnika](https://github.com/aoblak/ai-agent-web/blob/docs/independent-collaborator-bootstrap/COLLABORATOR_START_HERE.md),
  generator i cijeli `runtime/`. Ovaj link je promjenjivi lokator; zabilježeni SHA
  mora odgovarati svim preuzetim datotekama. Starije revizije iz ranijih poruka ne
  uključuju nužno kasnije ispravke.

Ovo su kandidati pod recenzijom, ne dokaz integracije ili instalacije. Prije upotrebe
provjeri aktualni status i commit PR-a. Ako se head promijenio, prethodni rezultat
testova ili pregled ne vrijedi automatski za novu reviziju. Vlastiti privatni prostor
ostaje odvojen od Aljošine memorije; priprema ne daje ovlast za upis na Markov račun.

### Prva dopuštena razmjena

1. U Markovu chatu provjeri stvarno povezani GitHub račun i dostupne mogućnosti
   čitanja/upisa. Ime navedeno u promptu nije dokaz identiteta. Javni ulaz može se
   pročitati bez privatnog pristupa.
2. Odaberi postojeći Issue/PR koji odgovara dogovorenom zadatku. Javni kanal smije
   sadržavati samo odobrene neosjetljive podatke. Za povjerljiv zadatak vlasnici
   moraju odabrati zajedničko privatno odredište i provjeriti ovlasti oba računa.
3. Slanje poruke, dodjela zadatka i upis zahtijevaju izričitu ovlast u tom chatu.
   Ovaj dokument nije poruka poslana Marku niti njegova suglasnost.
4. U autoriziranom odgovoru poveži isti `task_id` i jedinstveni `delivery_id`,
   točan izvorni commit, opseg, rezultat ili artefakt s commitom/SHA-256,
   izvršene provjere, ograničenja i stvarni status prihvaćanja. Za prvi pregled
   iz odjeljka 5 dovoljan je nalaz; ne treba instalacija ili produkcijski pristup.
5. Koordinator ponovno dohvati odgovor i provjeri GitHub autora, artefakte i
   kriterije prihvaćanja. Autora računa treba povezati s ovlaštenim sudionikom;
   potpis modela u tekstu nije autentifikacija. Vremena preuzmi iz stvarnih događaja.

Odvojeno prati `PRIPREMLJENO → OBJAVLJENO → PRIHVAĆENO → REZULTAT_VRAĆEN → PROVJERENO`.
Objava nije primitak; primitak nije prihvaćen rezultat. Ponavljanje istog
`delivery_id` ne smije pokrenuti drugi učinak. Bez stvarnog odgovora nema tvrdnje
da je Markov chat povezan; bez sljedećeg prihvaćanja nema ovisnog nastavka.

Ako alat ne može poslati ili dohvatiti odgovor, prikaži točan Issue/PR link i
pripremljeni tekst za prijenos te navedi nedostajuću mogućnost. Automatsko praćenje
i obavijesti zahtijevaju zasebno instaliran i provjeren mehanizam.
