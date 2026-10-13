# Neovisni suradnik — OOS početni ulaz

Ovaj javni ulaz povezuje **zajednički operativni ugovor** s **vlastitim privatnim radnim prostorom drugog korisnika**. Cilj postavljanja uključuje svih pet slojeva memorije i zasebnu provjerenu instalaciju OOS programskog sustava. Učitavanje ovog dokumenta samo po sebi nije instalacija. Zajednički kod i arhitektura mogu se ponovno upotrijebiti; tuđa privatna memorija ne prenosi se. Ne sadrži privatne podatke, vjerodajnice ni ovlasti pristupa.

## 1. Učitaj zajednička pravila

Pročitaj https://raw.githubusercontent.com/aoblak/ai-agent-web/main/MASTER_PROMPT.md
Alternativni prikaz: https://github.com/aoblak/ai-agent-web/blob/main/MASTER_PROMPT.md

Zabilježi stvarno učitanu verziju i razriješeni Git commit. Pri pripremi ovog ulaza provjeren je bootstrap v1.2.3 na commitu `0fb69403f2fa6126c851ac73e3073351f52c165c`; to nije tvrdnja da taj commit zauvijek ostaje aktualan. Ako aktualnu reviziju ne možeš utvrditi, navedi ograničenje. Ne izmišljaj uspješno učitavanje.

Primijeni zajednička pravila u granicama ovlasti ovog korisnika. Korisnik ovog razgovora zasebna je osoba: projektne identitete, osobne podatke, profil, odluke, zadatke i dnevnik izvornog autora ne nasljeđuje. Zajednička pravila nisu ovlaštenje za čitanje privatnih izvora ili slanje poruka.

## 2. Pitaj gdje spremati i zatraži stvarni pristup

GitHub korisničko ime uzmi iz korisnikove poruke; ako nedostaje, pitaj. Ime u poruci nije dokaz identiteta povezanog računa.

Nakon učitavanja bootstrapa pitaj:
> Gdje na svom GitHub računu želiš spremati datoteke i trajnu memoriju: u postojeći privatni repozitorij koji odabereš ili u novi privatni repozitorij oos-workspace?

Prije stvaranja ili upisa potvrdi točan račun, repozitorij, privatnu vidljivost i opseg izmjena s njegovim vlasnikom. Ne smatraj ovaj javni dokument vlasnikovim odobrenjem.

Provjeri dostupne alate za GitHub čitanje, stvaranje repozitorija i upis. Ako je povezivanje ili dodatno odobrenje potrebno i podržano, pokreni stvarni postupak aplikacije te objasni traženi opseg. Ne tvrdi da je dijalog prikazan prije potvrde alata; razgovorno „da” ne zamjenjuje obvezno odobrenje aplikacije. Nikad ne traži lozinku ili token u poruci, datoteci ili repozitoriju.

Ako alat nedostaje, objasni točno što nedostaje i pripremi datoteke za ručni unos u odabrani repozitorij. Ne pokušavaj preuzeti ovlasti drugog računa. Ne stvaraj javni repozitorij kao zamjenu za privatni. Ne pretpostavljaj da read-only konektor može spremati memoriju.

## 3. Postavi cijelu arhitekturu memorije i izvršne komponente

Zahtjev nije samo četiri početne datoteke. Obvezna hijerarhija je:
**SOURCE OF TRUTH → JOURNAL → PROJECT STATE → GLOBAL KNOWLEDGE → INDEX/LINKS**.
Najprije mapiraj postojeće kanonske lokacije; ne stvaraj dodatni master ili paralelno stanje.
Samo za novi odobreni prostor koristi čistu strukturu:

| Sloj | Kanonsko mjesto | Pravilo |
| --- | --- | --- |
| SOT | Izvorni artefakti/točni Git commitovi; `docs/SOURCES.md` kao registar izvora | Sačuvaj original, identitet, reviziju i vidljivost |
| Journal | `docs/MASTER_JOURNAL.md` | Vlastiti početno prazan dnevnik; događaje dopisuj, ispravke poveži |
| Project State | `docs/PROJECT_STATE.md` | Trenutno stanje s dokazima; nije drugi dnevnik |
| Global Knowledge | `docs/KNOWLEDGE.md` | Samo potvrđeno znanje povezano s izvorima i odlukama |
| Index/Links | `docs/INDEX.md` i izvedeni `docs/INDEX.json` | Lokatori, hashovi, statusi; nisu autoritet iznad izvora |

Ulazne upute su `AI_START_HERE.md`, `AGENTS.md` i isti `MASTER_PROMPT.md`.
U ovom novom rasporedu ne stvaraj dodatni `JOURNAL.md` ili `registry/state.yaml`.
Ako oni već postoje kod korisnika, zadrži njegov kanon i pripremi kompatibilno mapiranje;
ne pokreći generator preko postojećeg prostora.

### 3.1 Izvršna priprema OOS memorijskog/kontekstnog sloja

Ovaj PR uključuje `scripts/prepare_collaborator_workspace.py`. Generator koristi
postojeći javni OOS Context kod, bez kopiranja Aljošina dnevnika, stanja ili profila.
Izvor izvršnog alata je točno `4a71d44acf4f402ceee16fc3a0f4172555e70785` (PR #10,
verzija pod recenzijom; nije tvrdnja da je prihvaćena na mainu).
Preuzmi ovaj ulaz i generator iz istog provjerenog commita PR-a #12. U lokalnom
Git checkoutu javnog repozitorija osiguraj dostupnost navedenog izvornog commita:

```sh
git fetch origin 4a71d44acf4f402ceee16fc3a0f4172555e70785
python3 scripts/prepare_collaborator_workspace.py /odabrani/novi/lokalni/paket --repository Fiskalna123/oos-workspace
python3 /odabrani/novi/lokalni/paket/scripts/oos_context.py --root /odabrani/novi/lokalni/paket validate
```

Putanju i repozitorij zamijeni stvarnim korisnikovim izborom; primjer nije odobrenje.
Generator odbija postojeće odredište, priprema svih pet slojeva, uključuje postojeći
validator i `guarded_continue`, provjerava hashove i lokalni ponovni dohvat.
Ne stvara GitHub repozitorij, ne upisuje na Markov račun i ne instalira puni runtime.
`LOCAL_CONTEXT_PREPARED` označava samo lokalno pripremljen kontekstni sloj.

Prije upisa pokaži datoteke i pribavi korisnikovo odobrenje konkretnog privatnog
odredišta. Nakon odobrenog branch/PR postupka ponovno dohvati udaljeni commit,
provjeri sadržaj i privatnost. Memorija je vanjska pohrana koju svaki chat mora
učitati; nisu instalirani automatska sinkronizacija ni skriveni pozadinski procesi.
Za nastavak izvršavanja `guarded_continue` mora biti povezan s autentificiranim
kanalom i kontrolom ponovljene isporuke; sama tekstualna potvrda nije dokaz autora.

### 3.2 Obvezno postavljanje punog OOS runtimea

Nemoj proglasiti cijeli zahtjev dovršenim nakon memorijskog sloja. Potreban je i
OOS programski runtime, s dokazom instalacije i prolaznih testova. On nije isti
program kao `oos_context.py`.

1. U dostupnom ovlaštenom izvornom kanalu utvrdi točan odobreni OOS commit,
   komponente, ovisnosti, instalacijske upute i pripadajuće testove.
2. Koristi izdvojenu distribuciju koda odobrenu za suradnika. Ne zrcali privatni
   repozitorij ni njegovu Git povijest jer sadrže tuđe dnevnike i operativne podatke.
   Iz javnog ulaza ne zaključuj da je privatni izvor dostupan.
3. U Markovu odobrenom prostoru prikaži konkretan paket i plan instalacije;
   instaliraj odobrene komponente, konfiguriraj njegov identitet i njegove izvore.
   Vjerodajnice idu samo u njegov odobreni secret store. Troškovi i vanjske radnje
   zahtijevaju njegova odgovarajuća ovlaštenja.
4. Pokreni testove instaliranog commita, provjeri lokalni rad i udaljeno spremljene
   datoteke. Zabilježi stvarno implementirane komponente, ne popis ideja iz README-a.
5. Ako čista distribucija ili ovlašten pristup nisu dostupni, status punog runtimea
   ostaje `BLOCKED — nedostaje odobreni distribucijski paket/točan izvor i pristup`.
   Dovrši nezavisni memorijski sloj, ali ne zamijeni puni OOS njime i ne traži od
   Marka da izmišlja arhitekturu. Odgovornost za distribuciju ostaje na koordinatoru.

Novi prostor počinje bez naslijeđenih osobnih projekata i odluka. Nepoznate vrijednosti
ostaju UNKNOWN/null. Tehnički odabir odredišta zaseban je postupak postavljanja prema
izričitoj uputi korisnika. Pet profilnih pitanja iz zajedničkog bootstrapa ostaje zaseban
uvodni razgovor, bez dodatnih pitanja u tom intervjuu i bez ponavljanja poznatih odgovora.

## 4. Omogući povezivanje preko Gita bez spajanja privatnih memorija

Privatna memorija svakog vlasnika ostaje u njegovu prostoru. Zajednički kanal sadrži samo odobrene zadatke, rezultate i izvore.

Kandidat za javne, neosjetljive zadatke je postojeći https://github.com/aoblak/ai-agent-web/issues
To je kandidat, ne dokaz dodijeljene uloge, pristupa upisu ili aktivne komunikacije. Za povjerljivu suradnju vlasnici odabiru postojeći zajednički privatni repozitorij i potvrđuju stvarne ovlasti oba računa. Ne objavljuj privatne podatke u javni Issue.

Prije prve razmjene potvrdi odredište, sudionike, dopušteni sadržaj, odgovornog koordinatora i ovlaštenje za slanje. Ne mijenjaj podjelu uloga izvornog tima; suradniku dodijeli samo konkretno dogovoreni zadatak.

U postojeći Issue/PR uključi:
- stabilni ID zadatka i zasebni ID isporuke;
- vlasnika, pošiljatelja, primatelja i prethodnu fazu;
- opseg, ovisnosti i kriterije prihvaćanja;
- točan repozitorij i nepromjenjivi izvorni commit;
- rezultat/artefakt, njegov commit ili SHA-256 i dokaze provjere;
- stvarno opažene statuse i vremena slanja, prihvaćanja i povrata.

Primatelj mora provjeriti identitet preko autentificiranog kanala; ime u tekstu i hash sami ne dokazuju autora. Nedostajući rezultat, pogrešan hash, neodobreno zastarjeli izvor, ponovljena isporuka, sukob vlasništva ili neprovjerena prethodna faza blokiraju ovisni nastavak. Istom ID-u isporuke ne pripisuj drugi učinak. Nastavak zahtijeva provjerljiv rezultat prethodnika i stvarno prihvaćanje sljedećeg vlasnika.

Ako kanal nije dostupan, vrati sanitiziran paket za ručni prijenos. Status je PRIPREMLJENO, a ne POSLANO/PRIHVAĆENO. GitHub objava nije dokaz da ju je drugi chat pročitao; tekstualne upute ne bude drugi chat i ne instaliraju automatizaciju.

## 5. Završna provjera postavljanja

Izvijesti odvojeno:
1. Bootstrap: učitana verzija/commit ili konkretan problem.
2. Privatni prostor: URL, vlasnik, vidljivost i stvarne dozvole.
3. Trajna pohrana: udaljeni zapis, provjereni commit i prihvaćena grana ili točna blokada.
4. Puni OOS runtime: točan instalirani commit, komponente i rezultati testova ili konkretni BLOCKED status.
5. Suradnja: odabrani kanal, ovlasti i stanje stvarne isporuke/prihvaćanja, ili NIJE POVEZANO.

Dokaz preuzimanja ovog dokumenta nije dokaz instaliranog OOS-a, trajne memorije ili međusobne komunikacije.
