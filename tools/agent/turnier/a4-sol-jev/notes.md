# Notes of agent 4 "SolJev"

(nothing learnt yet)

## Auftakt, Spielzeit 0:00
- Regeln und beide lokalen Spielskills gelesen. Schiedsrichter hat noch pausiert; keine Spielorder erteilt.
- Jev wartet auf eigene Gruendung. Sicherheitsregel in ctl: Port 7605 explizit, keine Pause/Tempo-/Angriffsbefehle. Automatische Aufruestung deaktiviert: Ziel Einwohner, Frieden, liquide bleiben.
- Neustart wird nach dem wartenden Opening erwartet; danach Log kontrollieren. Alte Einzelspielerhinweise zu Tempo, Save und Engine ignorieren (AGENT.md hat Vorrang).

- Bei 0:02:21 noch keine Gruendung: opening() hielt gecachte paused-Antwort ueber alle 15s-Versuche. CACHE.clear() vor jedem Opening-Lesen ergaenzt. Nur eigenen Python-Treiber beendet, Runner startet ihn neu; Syntax geprueft.

## Review 0:10
- Insel 14, Zwackau, Kontor 61,41 gegruendet. 14888 Gold, -15/min, noch keine Haeuser.
- Opening-Entladen scheiterte an Regex: zwischen Schiffszeile und cargo steht lies at Kontor. Regex korrigiert, Startladung manuell entladen, unnoetigen Werkzeugkauf gestoppt.
- Opening wartet jetzt auf fahrendes Schiff statt Kurs alle 15s zu ersetzen. Sicherheitsregeln und Neustart inzwischen im laufenden Treiber bestaetigt.

## Runde 1 Ende, 0:14:10
- Zwackau Kontor 61,41 + Markt 58,38, Strasse y41 angeschlossen. Vorrat 34 Holz, 26 Werkzeuge, 10 Nahrung. 14597 Gold, -25/min; noch keine Wohnhaeuser.
- Groesster Zeitverlust: Chat-Rueckkopplung. Pro Handelswort alle Menschen ansprechen + force=True verursachte Dutzende Orders pro Chatabruf. chat_round auf Lesen/Protokoll begrenzt; eigene Mitteilungen max alle 240s. Wegen alter langer Chat-Schleife eigenen Treiber gezielt neu gestartet.
- Naechste Runde: Produktion und Wohnviertel pruefen, Restwerkzeuge entladen, wirtschaftlichen Ausbau priorisieren.

- 0:18:01: 9 Pioniere, 13114 Gold, Nahrung100%, Holz8, Werkzeug40. Zwei Foerster90-94%, Fischer72%. Zwei plan_chapel am Kontor 60,42/62,39 erreichen null Haeuser im Viertel49,29..35. Plan-Kapellen/Taverne/Schule aus generischer Kontorplatzierung entfernt; Versorgungsregel nach tatsaechlich unversorgten Haeusern statt hartem Gesamtgebaeudelimit. Standorte nach Reichweite zur Hausgruppe sortiert.

## Review 0:23
- 27 Pioniere in 15 Haeusern (state insgesamt39), 13464 Gold, Bilanz +9, Nahrung100%, Holz8, Werkzeuge26. Keine Gefahr, keine Strassen-/Markt-/Kapellenluecke mehr.
- Wartephasen weitgehend Holz-Nachproduktion; Hausplatz separat gelesen und gueltig. Zwei Foerster-Fanggebiete zaehlen im Treiber als forest-Felder und bleiben zum Holzertrag reserviert.
- Kapellenkorrektur bestaetigt: neue Kapelle47,29 beseitigt saemtliche Hauswarnungen. Naechster Schritt40 Pioniere, danach Stoff/Alkoholketten.

## Runde 2, 0:28
- 20 Haeuser, 38 Pioniere, 13079 Gold, +15/min, Nahrung100%. Manuell Haus47,37 und Schaffarm44,33 gebaut.
- Fehler von mir: Schaffarm passt am Stadtrand, ist aber durch Hausblock und Gebietsgrenze ohne Strassenweg! Erst Markt42,35 (find-site bestaetigt) muss Land erschliessen. Farm noch0%. Nicht weitere Farmen blind setzen.
- Foerster auf54/41% gefallen; dritter Foerster50,45 am Strassennetz plus Waldpflanzung als Holzreserve. Naechster Schritt10t Holz fuer Markt42,35 sichern, dann Farm verbinden.

## Runde 2 Ende, 0:30:50
- 40 Pioniere,20 Haeuser, insgesamt61 Einwohner laut state (andere Gebaeudebewohner mitgezaehlt).12569 Gold,-7/min,Nahrung100%.
- Jev hat Markt52,37 gebaut; Schaffarm nun ohne Strassenwarnung,26% und1.8t Wollpuffer. Weberei56,38 soeben gebaut, noch0%. Dritter Foerster50,45 bei86%, andere75/78%.
- Naechste Runde: Stoff im Lager und erste Siedler kontrollieren; keine weiteren Kapellen auf Verdacht. Stoff/Alkohol und Ziegel fuer naechsten Ausbau, Liquiditaet bleibt ausreichend.

- 0:34: Planerfehler klar: strategy.setup uebergibt crops_half als crops2 (=voll geeignete zweite Insel im Planer). Dadurch winery auf wine(half) statt Rumkette auf sugar(full). crops2 jetzt nur volle Heimatfruechte. Fuer ersten Aufstieg begrenztes Alkoholangebot buy12 zu65 eingerichtet (max780 Gold), eigener Stoff laeuft19% und holt Rohwolle.

## Review 0:36:06
- Erste16 Siedler +37 Pioniere; state74 insgesamt.11941Gold,Bilanz-26 inkl. Einkaufswirkung. Stoff100%,Nahrung100%, Alkohol0% aber Siedlerzufriedenheit128 bei Steuer128. Alkohol ist folglich fuer erste Aufstiege nicht zwingend, Stoff hat gereicht.
- Holz2t: Hausaufstiege verbrauchen Holznachwuchs. Begrenzten Holzzukauf bis25t zu22 eingerichtet (550Gold Zielpuffer), um Rohstoff-/Backstein-/Rumbau nicht dauerhaft zu blockieren. Nach Lieferung beenden. Foerster50,41/50,45 nur31/35%, Waldpflanzen am vollen Gebiet erfolglos; neue Westflaechen nach Markt benoetigt.

- 0:40:54: state101 Einwohner,45Siedler+33Pioniere,10856Gold. Nahrung/Stoff100%,Alkohol0%,Ziegel7t. Steuerzyklus144->128 wiederholt blockiert Upgrades und kostet Befehle. Steuererhoehung jetzt nur bei allen Guetern>=90%; entspricht supply first. Einfachere dauerhafte Regel statt fehlgeschlagene Steuern zu merken. Neustart pruefen.

## Runde3 Ende 0:45:30
- state122Einwohner,29Pioniere+60Siedler,8878Gold,Bilanz-129,Nahrung/Stoff100%. Produktion Rum jetzt gebaut, Zucker mangels vorbereiteter Felder0%.
- Direkte Feldsanierung38,37: nur eigene T/: im6x6Fenster, Wald entfernen, einzelne Zuckerfelder bauen, Strassen erhalten. Laeuft ueber eigenen Port. Neue-Plantagen-Regel in run() entsprechend korrigiert; nur unmittelbar nach erfolgreichem Neubau, um vorhandene reife Felder nicht blind abzureissen.
- Nachertrag/Ausgaben pruefen, Alkohol-/Holzzukaeufe nach Lieferung stoppen, westlichen Markt und weitere Rohstoffflaechen erschliessen. Steuerregel: keine Erhoehung bei Versorgung<90%, Neustart bestaetigt.

- 0:48:46:137Einwohner(state),85Siedler+18Pioniere,8067Gold. Bilanz-127 bei taxes161/running155: Bau/Einkaufsnachlauf beachten, nicht reine laufende Gebaeudebilanz. Lager70t trotz max20tVorrat: unnnoetiger Kontorupgrade aus Regel ohne Bedarfspruefung. Regel jetzt nur ab85% belegter Lagerkapazitaet. Alkoholzukauf beendet (bisher0 geliefert, Siedler bei128 zufrieden), Holz weiter dringend.

## Review 0:52
- 104Siedler/12Pioniere,state150.7723Gold. Stoff/Nahrung100%,Alkohol0. Zuckerplantage45% und5t Bestand bleiben liegen; aktueller Markt weit weg. Markt40,35 ist gueltiger Platz und noetig fuer kurze Abholung.
- Reserviere15t nachwachsendes Holz auf Schiff5 am eigenen Kontor, damit automatische Hausaufstiege es nicht vor Marktbau verbrauchen. Danach15t entladen und Markt40,35 bauen, verbinden. Native Ubleck verkauft nur Gewuerze; kein Holz. Fremde Kontorangebote ausschliesslich ueber o1602-ctl7605 gelesen.

- 0:56:31: Holzreserve15t gesammelt, entladen, Markt42,35 gebaut und Strasse42,38..40 angeschlossen. 114Siedler+14Pioniere(state162),7733Gold, Alkohol100% zeitweise knapp0.2t, Zucker6t im Lager.
- Steuer nach Vorratsverbesserung bis192 gestiegen, danach99Zufriedenheit. Zweite Steuerlogik tax_down_X setzte pauschal128 und widersprach schrittweiser tune_taxes-Regel. Pauschalreset deaktiviert; nach schrittweiser Senkung90s Erholung vor naechster Erhoehung. Ziel stabile volle Zufriedenheit statt Pendeln.

## Runde4 Ende 0:59:29
- state171Einwohner,130Siedler+4Pioniere,7215Gold. Steuern275,Laufkosten165,Bilanz-4 (Bau/Einkaufsnachlauf). Nahrung/Stoff/Alkohol100%,Food8.7t beobachtungsbeduerftig.27Haeuser.
- Markt42,35 erschliesst neue Wald-/Wiesenplaetze: Foerster37,21 score40,Schafe36,29 score54. Bisherige near_market nutzt Manhattan14 obwohl Markt echten Radius16 hat: auf moegliche unnoetig verworfene Standorte pruefen. Nachertrag130Siedler, Steuer176 zufrieden128.
- Naechste Runde: zweiter Fischer wegen fallendemFood, Rohstoffflaechen nutzen, Werkzeugkette ab120Siedlern pruefen. Direkte Korrekturen plus Regeltests weiter nur7605.

- 1:02:146Siedler,Stoff/Alkohol100%,Food6.6t faellt. Zweiten Fischer64,34 gebaut und4neueStrassentiles verbunden.
- near_market-Test bestaetigt unnoetigen Ausschluss: Kreisabstand<=16 statt Manhattan14 eroeffnet Foerster37,21(score40) und Schafe28,30(score64), beide ueber bereits geprueften reachable-Pfad erreichbar. Regel entsprechend korrigiert. Bestehende Catchment-/Strassenpruefungen bleiben aktiv.

- 1:03: zweite Zuckerplantage35,30 erfolgreich mit29Feldern (Log bestaetigt neue Regel);0% noch Reifezeit. 'does not grow here' beim Nachpflanzen bereits vorhandener Felder ist nicht gleich gescheitertem Erstbau.
- Fischer53,50 zeitgleich von Jev gebaut; nun3Huetten. Food5.6t, aber noch100%. Steuer192 bei allen Guetern100% ergibt wiederholt99Zufriedenheit;176 war128. TAX_LIMIT merkt daher gescheiterte Obergrenze bis Versorgungssignatur sich aendert. Verhindert dauerndes192->176->192-Pendeln bei identischen Guetern.

## Review1:06
- 160Siedler,204Einwohner(state),5828Gold,Steuern330/Kosten205,Bilanz-7. Food6.5t wieder steigend,Alkohol100%,Stoff3.7t faellt. Alte Schaffarm44,33 wegen Markt/Bebauung nur5Wiesen/4%: Ersatzfarm28,30(score64) gebaut und7Strassentiles angeschlossen. Holzkauf beendet bei20t Holz.
- Eigener Regelbug gefunden: field_of(forester)=forest; neue Crop-Vorbereitung rodet deshalb beim Foerster37,21 Wald und pflanzt31Setzlinge neu. Unnoetig und kostet Reifezeit. forest jetzt ausdruecklich aus Rodungszweig ausgeschlossen. Syntax/Neustart kontrollieren.
- Vor weiteren Marktplatzbauten Catchment von Schafen schuetzen; nicht nur Ackerfenster schuetzen! Erwaege konkrete sheep_farm-Pufferregel; alte Farm nach Ersatzproduktion abschalten.

- 1:10:44:227Einwohner,171Siedler,4872Gold,Stoff73% (0Vorrat). NeueFarm28,30 laeuft69%,5tWolle liegen dort, inStadt0. Transportweg trotz rechnerischemRadius zu lang. Markt31,24 gueltig und wiesenfrei (no-road), reserviere14Holz auf Schiff fuer Bau. Stoff buy10 Preis auf50 vomSpiel begrenzt, Siedlersteuer numerischeKlasse1 auf160 gesenkt. Tax akzeptiert Klassenname nicht; fehlgeschlagenen Versuch korrigiert.
- 2Tavernen bereitsgebaut (61,35 und38,28), aberBuergergueter fehlen: Zusatzkosten30/min. Nicht weiter solcheGebaeude vor Versorgung bauen.

## Runde5 Ende1:15:42
- 240Einwohner(state),182Siedler+4Pioniere,5188Gold,Bilanz+24,Steuern348/Kosten250. Nahrung/Stoff/Alkohol kurz zuvor100%,Stoff0.4t fragil.
- Zweite Holzreserve14t erfolgreich, Markt31,24 gebaut,1Strassentile zum Netz. Farm28,30 bei65%,Wolle3t dort: kuerzereAbholung nun moeglich. Wool->Weberei36% bisher knapp. Weiteren Stoffzukauf beenden sobald Lager nachhaltigwaechst.
- Wiederholtbestaetigte Regeln in lokaleSkills aufnehmen: keine halbfrucht als vollzweiteInsel, oeffentlicheBauten nachHaeuserreichweite, SchafweidenvorWohnung schuetzen, Steuer176 statt192 bei100%Guetern, Feldererstvorbereiten und nur Nutzpflanzenroden.

## Review1:20
- Markt31,24 wirkt:4tWolle erstmalsimStadtlager,Webereiarbeitet. ZweiteFarm24,22 vomTreibergebaut,60% und3tWolle. Stoffnochknapp/29%-100% schwankend, Steuer144haelt128. Nahrung stabil8t. Werkzeuge0t wartenaufHaendler.
- Foerster36,33 ausgeschaltet: seinRadiusueberlappt beideZuckerfenster und kann NutzpflanzenalsBaeume faellen. ranked_sites fuerFoerster schliesst nun jede Nutzpflanzenfenster-Ueberschneidung aus. NeuerFoerster36,13 vomTreiber bei90%.
- Gewuerzabholung am entdeckten NativeKontor7,0 versucht: load20 verweigert(nothing moved), trotzangezeigtemHandel/Gewuerz20tPreis0. KeinGewuerz erhalten,SchiffleerzurueckamHeimkontor. KeineGratisware angenommen; spaeterbezahlteHandelsangebotepruefen.

## Review1:24:13
- 279Einwohner,26Pioniere+192Siedler,4716Gold,Bilanz+123,Steuern447/Kosten295. AlleGueter100%,Stoff0.4t mitWolle4tFragil. Werkzeuge0t verhindert Aufstiege; Haendlerkauf25t zu75bleibt.
- Sols oeffentlichesKontor11,0 verkauft50tHolzzu10. Schiff5 nach402,97 (Sea~ imPort-Map11,57,17-69,28, vierTilesnebenKontor61,21) geschickt. Ziel40tHolzfuer400Gold, danachHeim188,242. Vorherige native-Abholung scheiterte moeglicherweiseanLandziel;sail_to hielt nachgescheitertemLandweg stillesSchifffuerangekommen. Kuenftig echteSeekachel+Positionpruefen!

## Runde6 Ende1:29:35
- 303Einwohner,49Pioniere+192Siedler,60Haeuser,4651Gold,Bilanz+160. Nahrung/Stoff/Alkohol100%;Food5.5t fallend. Werkzeuge0seitvielenMinuten ist klarerFlaschenhals, Pionierwachstumflaechigweiter.
- Holzhandel beiSol erfolgreich:5t fuer50Gold, retourundentladen. Fremdes' sells wood50t' meintLagergrenze, nicht50t frei. EchteSea402,97 amKontor11,0 funktioniert, nichtLandziel. sail_to prueft nun Zielnaehe<=6 statt nur idle.
- PreisexperimentWerkzeuge: Solbietet105, wir75 undbekommenkaumLieferung. UnsereKauforder15t zu105 (statt25tzu75), max1575GoldPuffer. VermutungPreiswettbewerb, nochkeinbewiesenerMechanismus. NachLieferungbestaetigen; keinblindesHochbieten.
- SiedlersteuerfesteObergrenze176 (192 mehrfach99ZufriedenheitundWegzug). Forester-Crop-Konfliktgesperrt,36,33weiteroff. NeueWeiden/Hausblockschutzwirkungbeobachten.

## Review1:38:05
- Food0t/Supply92%,320Einwohner,202Siedler,5284Gold. Cloth7.3t100%,Alkohol6.6t100%. Hausbauunter8tFoodvorerstgesperrt; Nachfragewachstumstoppt. Reserviere8tWerkzeugaufSchiff(fuer2Fischer), erste2tgesichert.
- Neustart hatteWerkzeugkauf75ueberschrieben, Experimentdadurchunterbrochen. Automatiknun105und15tZielunter6000Gold; Buy-tools-OptionentferntkeinenNahrungskaufmehr. Foodbuy20zu26bestehenlassen. KandidatenFischer60,26score28 und48,53score23, nachWerkzeuglieferungbauen/anschliessen.

## Runde7 Ende1:44:02
- 304EinwohnernachHunger-Rueckgang275,190Siedler+49Pioniere,5212Gold,Bilanz+108. Food94% ohneLager,Stoff10t100%,Alkohol6.8t100%.64Haeuserfastvoll. FoodpausebeiHausbauaktivbis8tReserve.
- Werkzeugreserveerst5tinnerhalb160s, dann1t separatgesichert. Fischer60,26 gebaut(Anschluss ueberbereitsvorhandenePierkacheln; Helfer meldet falsch no way, SpielkeineROADwarnung). FuenfterFischer48,53 gebaut/angeschlossen.
- Preis150fuerWerkzeuge wirdauf140begrenzt, also105nichtHoechstpreis. KonkreteOrder15tzu140. EinigeWerkzeuglieferungenjetztanwesend; automatischeOrdernoch105beiNeustart, vornaechstemNeustartanpassennachBedarf. KeineKausalitaetbewiesen.
- NaechsteRunde: Foerderleistungder5Fischerpruefen, beiFood>=8weiterHaeuser. EigeneWerkzeugkettealswichtigeUnabhaengigkeitvorbereiten: Mine1000Gold/10Tools/20Holz/5Ziegel,Smelter200/3/1/4,Toolmaker150/3/2/5. Erzsite33,46Wegpruefen, Material16Tools reservieren stattallesaHausaufstieg.

## Review1:50:52
- 339Einwohner,52Pioniere+222Siedler,5833Gold,Bilanz+174,alleGueter100%. Food4.1t langsamsteigend,Cloth12t,Alkohol6.7t,Holz90/Ziegel90voll.
- EigeneWerkzeugkette: Erz33,46 mit reachable(1x2) bestaetigt. Reserviere16ToolsaufsSchiff5 fuerMine+Schmelze+Toolmaker, bisher2t. AutomatischeKauforderbeiBootstrapnun140max,15tunter6000Geld.
- ZweiineffizientealteFoerster50,45 und50,41 beiHolz90ausgeschaltet(sparen10/min). WennHolzunter30spaeterwiedereinschaltenfallsnoetig. Cropkonflikt-Foerster36,33 bleibtpermanentoff. GuteNordfoerster37,21und36,13wartenaufLagerraum.
